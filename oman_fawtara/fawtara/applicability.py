"""Fawtara mandate applicability per VAT registration and document."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate


def fawtara_settings():
	return frappe.get_cached_doc("Oman Fawtara Settings")


def mandate_date(registration) -> object | None:
	"""Mandatory start date for a registration.

	Decision No. 189/2026: 1 April 2027 where annual supplies exceed
	OMR 5 million, otherwise 1 October 2027. The assessment (which periods,
	which supplies count) is configurable on Oman Fawtara Settings and the
	registration, and an explicit override always wins.
	"""
	s = fawtara_settings()
	if registration.fawtara_mandate_date_override:
		return getdate(registration.fawtara_mandate_date_override)
	threshold = flt(s.mandate_threshold_omr)
	actual = flt(registration.annual_supplies_reference)
	expected = flt(registration.annual_supplies_expected)
	if threshold and (actual > threshold or expected > threshold):
		return getdate(s.phase_1_date) if s.phase_1_date else None
	return getdate(s.phase_2_date) if s.phase_2_date else None


def registration_live_from(registration):
	"""Earliest date from which invoices are e-invoiced (voluntary/pilot start or mandate)."""
	dates = [d for d in (mandate_date(registration), registration.fawtara_voluntary_start_date) if d]
	return min(getdate(d) for d in dates) if dates else None


def is_eligible(doc) -> tuple[bool, str]:
	s = fawtara_settings()
	if not cint(s.enabled):
		return False, _("Fawtara integration is disabled")
	reg_name = doc.get("oman_vat_registration")
	if not reg_name:
		return False, _("No VAT registration on document")
	reg = frappe.get_cached_doc("Oman VAT Registration", reg_name)
	if not cint(reg.fawtara_enabled):
		return False, _("Fawtara not enabled for registration {0}").format(reg_name)
	live = registration_live_from(reg)
	if not live or getdate(doc.posting_date) < live:
		return False, _("Before Fawtara start date ({0})").format(live)
	if cint(doc.get("oman_einvoice_exempt")):
		return False, _("Marked as not requiring an e-invoice")

	if doc.doctype == "Purchase Invoice":
		if not cint(doc.get("oman_self_billing")):
			return False, _("Purchase invoices are e-invoiced only under self-billing")
		return True, ""

	buyer = doc.get("oman_buyer_type") or "B2B"
	if buyer == "B2C" and not cint(s.include_b2c):
		return False, _("B2C e-invoicing disabled in settings")
	if buyer == "B2G" and not cint(s.include_b2g):
		return False, _("B2G e-invoicing disabled in settings")
	if cint(s.skip_out_of_scope_only):
		natures = {
			frappe.get_cached_value("Oman VAT Treatment", i.oman_vat_treatment, "nature")
			for i in doc.items
			if i.get("oman_vat_treatment")
		}
		if natures == {"Out of Scope"}:
			return False, _("All lines are outside the scope of Oman VAT")
	return True, ""


@frappe.whitelist()
def compute_annual_supplies(registration: str):
	"""Compute reference-period supplies from the VAT ledger for the threshold test."""
	frappe.only_for(("Oman VAT Manager", "Oman VAT Approver", "System Manager"))
	s = fawtara_settings()
	reg = frappe.get_doc("Oman VAT Registration", registration)
	if not (s.threshold_period_start and s.threshold_period_end):
		frappe.throw(_("Set the threshold reference period in Oman Fawtara Settings."))
	total = frappe.db.sql(
		"""select coalesce(sum(d.taxable_amount), 0) from `tabOman VAT Transaction` t
		join `tabOman VAT Transaction Detail` d on d.parent=t.name
		join `tabOman VAT Treatment` tr on tr.name=d.treatment
		where t.vat_registration=%s and t.status='Active' and tr.counts_for_fawtara_threshold=1
		and (t.direction='Sales' or (t.direction='Purchase' and d.reverse_charge=1))
		and t.tax_point_date between %s and %s""",
		(registration, s.threshold_period_start, s.threshold_period_end),
	)[0][0]
	reg.db_set("annual_supplies_computed", flt(total))
	return {"computed": flt(total), "mandate_date": str(mandate_date(reg))}
