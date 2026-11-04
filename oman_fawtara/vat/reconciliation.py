"""VAT register ↔ General Ledger reconciliation."""

from __future__ import annotations

from collections import defaultdict

import frappe
from frappe.utils import flt

from oman_fawtara.vat.calc import round_money
from oman_fawtara.vat.utils import get_account_mapping

# account roles: (mapping field, natural side)
ROLES = {
	"output": ("output_vat_account", "credit"),
	"input": ("input_vat_account", "debit"),
	"rcm_output": ("rcm_output_vat_account", "credit"),
	"rcm_input": ("rcm_input_vat_account", "debit"),
	"import_input": ("import_vat_account", "debit"),
	"import_payable": ("import_vat_payable_account", "credit"),
}


def _account(m, role):
	acc = m.get(ROLES[role][0])
	if acc:
		return acc
	fallback = {"rcm_output": "output", "rcm_input": "input", "import_input": "input", "import_payable": "output"}
	return _account(m, fallback[role]) if role in fallback else None


def expected_by_account(company, registration, from_date, to_date) -> dict:
	m = get_account_mapping(company, registration)
	exp = defaultdict(float)
	rows = frappe.db.sql(
		"""
		select t.source_doctype, t.direction, t.is_adjustment, d.output_vat, d.input_vat, d.recoverable_vat,
			d.nonrecoverable_vat, d.rcm_output_vat, d.reverse_charge, d.is_import
		from `tabOman VAT Transaction` t join `tabOman VAT Transaction Detail` d on d.parent = t.name
		where t.company=%s and t.vat_registration=%s and t.status='Active'
			and t.posting_date between %s and %s
		""",
		(company, registration, from_date, to_date),
		as_dict=True,
	)
	for r in rows:
		if r.source_doctype == "Oman Import Declaration":
			exp[_account(m, "import_input")] += flt(r.recoverable_vat)
			if r.reverse_charge:
				exp[_account(m, "import_payable")] += flt(r.rcm_output_vat)
			continue
		if r.source_doctype == "Oman VAT Adjustment":
			key = "output" if flt(r.output_vat) else "input"
			exp[_account(m, key)] += flt(r.output_vat) if key == "output" else flt(r.recoverable_vat)
			continue
		if r.direction == "Sales":
			exp[_account(m, "output")] += flt(r.output_vat)
		elif r.reverse_charge:
			exp[_account(m, "rcm_output")] += flt(r.rcm_output_vat)
			exp[_account(m, "rcm_input")] += flt(r.recoverable_vat)
		else:
			# ERPNext books the full charged VAT; the allocation journal moves the
			# non-recoverable part out, leaving the recoverable amount.
			exp[_account(m, "input")] += flt(r.recoverable_vat)
	return m, exp


def gl_movement(company, account, from_date, to_date, side):
	res = frappe.db.sql(
		"""select coalesce(sum(debit),0), coalesce(sum(credit),0) from `tabGL Entry`
		where company=%s and account=%s and is_cancelled=0 and posting_date between %s and %s""",
		(company, account, from_date, to_date),
	)[0]
	dr, cr = flt(res[0]), flt(res[1])
	return dr - cr if side == "debit" else cr - dr


def compute(company, registration, from_date, to_date) -> list[dict]:
	m, exp = expected_by_account(company, registration, from_date, to_date)
	accounts = {}
	for role, (field, side) in ROLES.items():
		acc = _account(m, role)
		if acc and acc not in accounts:
			accounts[acc] = side
	out = []
	for acc, side in accounts.items():
		gl = gl_movement(company, acc, from_date, to_date, side)
		e = exp.get(acc, 0.0)
		out.append(
			{
				"account": acc,
				"natural_side": side.title(),
				"register_amount": float(round_money(e)),
				"gl_amount": float(round_money(gl)),
				"difference": float(round_money(gl - e)),
			}
		)
	return out
