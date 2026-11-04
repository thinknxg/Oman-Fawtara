"""VAT Import Engine: customs (Bayan) declarations and import VAT."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt

from oman_fawtara.vat import calc, rules
from oman_fawtara.vat.recovery import make_journal_entry
from oman_fawtara.vat.utils import get_account_mapping, settings


def validate_declaration(d):
	if not d.declaration_number:
		frappe.throw(_("Customs declaration (Bayan) number is required."))
	d.declaration_number = d.declaration_number.strip().upper()
	dup = frappe.db.get_value(
		"Oman Import Declaration",
		{"company": d.company, "declaration_number": d.declaration_number, "docstatus": ["<", 2], "name": ["!=", d.name]},
	)
	if dup:
		frappe.throw(_("Customs declaration {0} is already recorded in {1}.").format(d.declaration_number, dup),
			title=_("Duplicate import document"))

	# Duplicate claim: the same purchase invoice on two active declarations
	for row in d.invoices:
		other = frappe.db.sql(
			"""select p.name from `tabOman Import Declaration Invoice` c
			join `tabOman Import Declaration` p on p.name = c.parent
			where c.purchase_invoice=%s and p.docstatus < 2 and p.name != %s""",
			(row.purchase_invoice, d.name or ""),
		)
		if other:
			frappe.throw(_("Purchase Invoice {0} is already linked to import declaration {1}.").format(
				row.purchase_invoice, other[0][0]))

	treatment = settings().import_of_goods_treatment
	d.vat_rate, d.rate_reference = rules.get_rate(treatment, None, d.declaration_date)
	d.vat_base = flt(d.customs_value) + flt(d.customs_duty) + flt(d.other_charges)
	d.computed_vat = float(calc.vat_on(d.vat_base, d.vat_rate))
	if not flt(d.import_vat):
		d.import_vat = d.computed_vat
	d.vat_difference = flt(d.import_vat) - flt(d.computed_vat)
	recoverable, nonrecoverable = calc.split_recovery(d.import_vat, d.recovery_percentage if d.recovery_percentage is not None else 100)
	d.recoverable_vat = float(recoverable)
	d.nonrecoverable_vat = float(nonrecoverable)
	if abs(d.vat_difference) > 0.005:
		frappe.msgprint(
			_("Customs-assessed VAT {0} differs from {1}% of the VAT base ({2}). The customs figure is used.").format(
				d.import_vat, d.vat_rate, d.computed_vat),
			indicator="orange",
		)


def post_declaration(d):
	if not d.post_journal_entry:
		return None
	m = get_account_mapping(d.company, d.vat_registration)
	debit_input = m.import_vat_account or m.input_vat_account
	if d.payment_method == "Deferred via VAT Return":
		credit = m.import_vat_payable_account or m.output_vat_account
	else:
		credit = m.customs_vat_clearing_account
	if not credit:
		frappe.throw(_("Configure the import VAT credit account in Oman VAT Account Mapping."))
	lines = [(debit_input, d.recoverable_vat, 0, None)]
	if flt(d.nonrecoverable_vat):
		lines.append((m.nonrecoverable_vat_account, d.nonrecoverable_vat, 0, None))
	lines.append((credit, 0, d.import_vat, None))
	return make_journal_entry(
		company=d.company,
		posting_date=d.clearance_date or d.declaration_date,
		lines=lines,
		remark=_("Import VAT on customs declaration {0}").format(d.declaration_number),
		source_doctype=d.doctype,
		source_name=d.name,
	)


def declaration_lines(d) -> list[dict]:
	s = settings()
	treatment = s.import_of_goods_treatment
	code = frappe.db.get_value("Oman VAT Code", {"treatment": treatment, "disabled": 0}, "name", order_by="is_default desc")
	deferred = d.payment_method == "Deferred via VAT Return"
	return [
		{
			"row": None,
			"item_code": None,
			"treatment": treatment,
			"vat_code": code,
			"rate": d.vat_rate,
			"rate_ref": d.rate_reference,
			"supply_category": "Goods",
			"taxable": flt(d.vat_base),
			"output_vat": 0,
			"input_vat": flt(d.import_vat),
			"recovery_pct": flt(d.recovery_percentage),
			"recoverable": flt(d.recoverable_vat),
			"nonrecoverable": flt(d.nonrecoverable_vat),
			# Postponed import VAT is self-accounted on the return (output side)
			"rcm_output": flt(d.import_vat) if deferred else 0,
			"reverse_charge": 1 if deferred else 0,
			"is_import": 1,
			"recovery_status": "Recoverable" if flt(d.recovery_percentage) >= 100 else "Partially Recoverable",
		}
	]
