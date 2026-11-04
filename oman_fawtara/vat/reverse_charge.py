"""Reverse Charge Engine.

Imported services (and any purchase matched by a ``Reverse Charge`` rule) are
self-assessed by the Oman recipient: output VAT is accounted for and the
eligible part is reclaimed as input VAT. The supplier payable is never
touched — the self-assessment is posted as a separate, linked journal
(``Journal Entry`` mode, default) or validated against paired add/deduct
tax rows on the invoice (``Tax Template`` mode).
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, flt

from oman_fawtara.vat import calc
from oman_fawtara.vat.recovery import make_journal_entry, nonrecoverable_debit_account
from oman_fawtara.vat.utils import settings


def rcm_lines(doc):
	return [i for i in doc.items if cint(i.get("oman_reverse_charge"))]


def validate_tax_template_mode(doc, mapping, analysis):
	"""In Tax Template mode the invoice must carry matching RCM tax rows."""
	if settings().reverse_charge_posting == "Tax Template" and rcm_lines(doc):
		out_acc = mapping.rcm_output_vat_account
		in_acc = mapping.rcm_input_vat_account or mapping.input_vat_account
		out_total = sum(flt(t.base_tax_amount_after_discount_amount) for t in doc.taxes if t.account_head == out_acc)
		in_total = sum(flt(t.base_tax_amount_after_discount_amount) for t in doc.taxes if t.account_head == in_acc)
		expected = sum(flt(l["rcm_output"]) for l in analysis.lines if l["reverse_charge"])
		ok, diff = calc.reconcile(out_total, expected, calc.line_tolerance(len(analysis.lines)))
		if not ok or abs(flt(out_total) - flt(in_total)) > 0.005:
			analysis.add("RCM_TAX_ROWS", "Error", _(
				"Reverse-charge tax rows do not match the self-assessed VAT ({0} OMR). Add a 'Deduct' row on "
				"{1} and an 'Add' row on {2} of equal amount."
			).format(expected, out_acc, in_acc))


def create_entry(doc, mapping):
	if settings().reverse_charge_posting != "Journal Entry":
		return None
	lines = rcm_lines(doc)
	if not lines:
		return None
	e = frappe.new_doc("Oman Reverse Charge Entry")
	e.company = doc.company
	e.vat_registration = doc.oman_vat_registration
	e.purchase_invoice = doc.name
	e.supplier = doc.supplier
	e.supplier_country = doc.get("oman_party_country")
	e.posting_date = doc.posting_date
	e.tax_point_date = doc.oman_tax_point_date
	for i in lines:
		e.append(
			"items",
			{
				"invoice_item": i.name,
				"item_code": i.item_code,
				"treatment": i.oman_vat_treatment,
				"taxable_amount": i.oman_taxable_amount,
				"vat_rate": i.oman_vat_rate,
				"output_vat": i.oman_input_vat,
				"recovery_percentage": i.oman_recovery_percentage,
				"recoverable_vat": i.oman_recoverable_vat,
				"nonrecoverable_vat": i.oman_nonrecoverable_vat,
				"nonrecoverable_account": nonrecoverable_debit_account(doc, i, mapping)
				if flt(i.oman_nonrecoverable_vat)
				else None,
				"cost_center": i.cost_center,
			},
		)
	e.flags.ignore_permissions = True
	e.insert()
	e.submit()
	return e


def post_entry_journal(entry, mapping):
	out_acc = mapping.rcm_output_vat_account or mapping.output_vat_account
	in_acc = mapping.rcm_input_vat_account or mapping.input_vat_account
	lines = []
	for r in entry.items:
		lines.append((in_acc, r.recoverable_vat, 0, r.cost_center))
		if flt(r.nonrecoverable_vat):
			lines.append((r.nonrecoverable_account, r.nonrecoverable_vat, 0, r.cost_center))
		lines.append((out_acc, 0, r.output_vat, r.cost_center))
	return make_journal_entry(
		company=entry.company,
		posting_date=entry.posting_date,
		lines=lines,
		remark=_("Oman VAT reverse charge self-assessment for {0}").format(entry.purchase_invoice),
		source_doctype=entry.doctype,
		source_name=entry.name,
	)
