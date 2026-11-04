"""VAT Adjustment Engine.

ERPNext credit/debit notes (``is_return`` / ``is_debit_note``) flow through the
invoice engine and are recorded as adjustment transactions linked to the
original invoice. ``Oman VAT Adjustment`` handles everything else: bad-debt
relief, change in consideration, incorrect treatment, previous-period
corrections, input recovery changes and manual statutory adjustments.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import date_diff, flt, getdate

from oman_fawtara.vat import rules
from oman_fawtara.vat.recovery import make_journal_entry
from oman_fawtara.vat.utils import get_account_mapping, get_period_for

OUTPUT_TYPES = {"Sales Credit Note", "Sales Debit Note", "Bad Debt Relief", "Change in Consideration"}


def validate_adjustment(a):
	if not a.reason:
		frappe.throw(_("Adjustment reason is required."))
	if a.original_doctype and a.original_name:
		orig = frappe.get_doc(a.original_doctype, a.original_name)
		if orig.docstatus != 1:
			frappe.throw(_("Original document {0} must be submitted.").format(a.original_name))
		a.original_tax_point = orig.get("oman_tax_point_date") or orig.get("posting_date")
		a.original_treatment = a.original_treatment or (orig.items[0].get("oman_vat_treatment") if orig.get("items") else None)
		if a.vat_registration and a.original_tax_point:
			p = get_period_for(a.vat_registration, a.original_tax_point)
			a.original_period = p.name if p else None
	elif a.adjustment_type not in ("Manual Statutory Adjustment",):
		frappe.throw(_("Reference the original transaction for adjustment type {0}.").format(a.adjustment_type))

	if a.adjustment_type == "Bad Debt Relief":
		_validate_bad_debt(a)

	if not a.direction:
		a.direction = "Output" if a.adjustment_type in OUTPUT_TYPES else "Input"


def _validate_bad_debt(a):
	"""Bad-debt relief conditions are configurable rules (age, write-off evidence)."""
	if a.original_doctype != "Sales Invoice":
		frappe.throw(_("Bad debt relief must reference a Sales Invoice."))
	orig = frappe.get_doc("Sales Invoice", a.original_name)
	for rule in rules.active_rules(a.posting_date, "Sales", "Validation", a.company):
		if rule.check_key == "bad_debt_min_age_days":
			due = orig.get("due_date") or orig.posting_date
			age = date_diff(a.posting_date, due)
			if age < (rule.numeric_value or 0):
				frappe.throw(_("Bad debt relief requires the debt to be overdue at least {0} days (currently {1}). [{2}]").format(
					int(rule.numeric_value), age, rule.rule_code))
	if not a.evidence:
		frappe.throw(_("Attach write-off evidence (Oman VAT Evidence) for bad debt relief."))


def post_adjustment(a):
	if not a.post_journal_entry or not flt(a.vat_adjustment):
		return None
	m = get_account_mapping(a.company, a.vat_registration)
	vat_acc = m.output_vat_account if a.direction == "Output" else m.input_vat_account
	contra = a.contra_account or m.vat_adjustment_account
	if not contra:
		frappe.throw(_("Set a contra account or the VAT Adjustment Account in Oman VAT Account Mapping."))
	amt = flt(a.vat_adjustment)
	# Positive adjustment increases output VAT payable / increases input VAT receivable.
	if a.direction == "Output":
		lines = [(contra, amt, 0, None), (vat_acc, 0, amt, None)] if amt > 0 else [(vat_acc, -amt, 0, None), (contra, 0, -amt, None)]
	else:
		lines = [(vat_acc, amt, 0, None), (contra, 0, amt, None)] if amt > 0 else [(contra, -amt, 0, None), (vat_acc, 0, -amt, None)]
	return make_journal_entry(
		company=a.company,
		posting_date=a.posting_date,
		lines=lines,
		remark=_("Oman VAT adjustment {0}: {1}").format(a.adjustment_type, a.reason),
		source_doctype=a.doctype,
		source_name=a.name,
	)


def adjustment_lines(a) -> list[dict]:
	out = a.direction == "Output"
	return [
		{
			"row": None,
			"item_code": None,
			"treatment": a.original_treatment or a.treatment,
			"vat_code": a.vat_code,
			"rate": 0,
			"rate_ref": None,
			"supply_category": None,
			"taxable": flt(a.taxable_adjustment),
			"output_vat": flt(a.vat_adjustment) if out else 0,
			"input_vat": 0 if out else flt(a.vat_adjustment),
			"recovery_pct": 100,
			"recoverable": 0 if out else flt(a.vat_adjustment),
			"nonrecoverable": 0,
			"rcm_output": 0,
			"reverse_charge": 0,
			"is_import": 0,
			"recovery_status": None,
		}
	]
