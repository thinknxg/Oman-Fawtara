"""Sales Invoice / Purchase Invoice document events.

ERPNext remains the system of record: it computes taxes, totals and the GL.
These hooks classify, verify and record; they never override the ERPNext tax
total. External (Fawtara) calls are always queued to background workers.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, flt

from oman_fawtara import audit
from oman_fawtara.vat import engine, period, recovery, reverse_charge, transaction
from oman_fawtara.vat.calc import canonical_json
from oman_fawtara.vat.utils import enforcement_blocks, get_account_mapping, get_registration, is_enabled

OMAN_LOCKED_ITEM_FIELDS = (
	"oman_vat_treatment", "oman_vat_code", "oman_vat_rate", "oman_taxable_amount", "oman_output_vat",
	"oman_input_vat", "oman_recovery_percentage", "oman_recoverable_vat", "oman_nonrecoverable_vat",
	"oman_reverse_charge",
)


def _applies(doc) -> bool:
	if not is_enabled() or doc.flags.get("ignore_oman_vat"):
		return False
	return bool(get_registration(doc.company, doc.get("oman_tax_point_date") or doc.posting_date))


# --------------------------------------------------------------------------
# before_validate: put the right Item Tax Template on each line so ERPNext
# computes the correct VAT itself.
# --------------------------------------------------------------------------


def before_validate(doc, method=None):
	if not _applies(doc):
		return
	s = frappe.get_cached_doc("Oman VAT Settings")
	if not cint(s.auto_apply_item_tax_template):
		return
	from erpnext.stock.get_item_details import get_item_tax_map

	ctx = engine.build_context(doc)
	for item in doc.items:
		treatment, code, source = engine.resolve_treatment(ctx, item)
		if source == "default" or not code:
			continue
		template = frappe.db.get_value(
			"Oman VAT Code Template", {"parent": code, "company": doc.company}, "item_tax_template"
		)
		if template and item.item_tax_template != template:
			item.item_tax_template = template
			item.item_tax_rate = get_item_tax_map(doc=doc.as_dict(), tax_template=template, as_json=True)


def validate(doc, method=None):
	if not _applies(doc):
		return
	analysis = engine.analyse(doc)
	mapping = get_account_mapping(doc.company, doc.oman_vat_registration, raise_if_missing=False)
	if doc.doctype == "Purchase Invoice" and mapping:
		reverse_charge.validate_tax_template_mode(doc, mapping, analysis)
		doc.oman_vat_validation_status = analysis.status
		doc.oman_vat_issues = frappe.as_json(analysis.issues) if analysis.issues else None
	doc.flags.oman_analysis = analysis

	if analysis.issues and doc.docstatus == 0 and not frappe.flags.in_test and not frappe.flags.in_import:
		msgs = [f"<b>{i['severity']}</b>: {i['message']}" for i in analysis.issues]
		frappe.msgprint("<br>".join(msgs), title=_("Oman VAT validation"),
			indicator="red" if analysis.errors else "orange")


def before_submit(doc, method=None):
	if not _applies(doc):
		return
	period.assert_open(doc.company, doc.oman_vat_registration, doc.oman_tax_point_date, _("submit"))
	analysis = doc.flags.get("oman_analysis") or engine.analyse(doc)
	if analysis.errors and enforcement_blocks():
		frappe.throw(
			"<br>".join(f"• {e['message']}" for e in analysis.errors),
			title=_("Oman VAT validation failed"),
		)
	from oman_fawtara.fawtara import queue

	queue.before_invoice_submit(doc)


def on_submit(doc, method=None):
	if not _applies(doc):
		return
	analysis = doc.flags.get("oman_analysis")
	direction = engine.DIRECTION[doc.doctype]
	party_type, party_field = engine.PARTY[doc.doctype]
	is_adj = bool(cint(doc.get("is_return")) or cint(doc.get("is_debit_note")))
	original = {"doctype": doc.doctype, "name": doc.return_against} if doc.get("return_against") else None

	transaction.record(
		doc,
		direction,
		transaction.lines_from_document(doc),
		party_type=party_type,
		party=doc.get(party_field),
		party_vrn=doc.get("tax_id"),
		tax_point=doc.oman_tax_point_date,
		registration=doc.oman_vat_registration,
		is_adjustment=is_adj,
		original=original,
		extra={"validation_status": doc.oman_vat_validation_status, "adjustment_reason": doc.get("oman_adjustment_reason")},
	)

	log = frappe.new_doc("Oman VAT Validation Log")
	log.update(
		{
			"reference_doctype": doc.doctype,
			"reference_name": doc.name,
			"company": doc.company,
			"vat_registration": doc.oman_vat_registration,
			"status": doc.oman_vat_validation_status,
			"error_count": len(analysis.errors) if analysis else 0,
			"warning_count": len(analysis.warnings) if analysis else 0,
			"issues": doc.oman_vat_issues or "[]",
			"ruleset_version": doc.oman_vat_ruleset,
			"tax_point_date": doc.oman_tax_point_date,
		}
	)
	log.flags.ignore_permissions = True
	log.insert()

	mapping = get_account_mapping(doc.company, doc.oman_vat_registration)
	if doc.doctype == "Purchase Invoice":
		alloc = recovery.create_allocation(doc, mapping)
		rcm = reverse_charge.create_entry(doc, mapping)
		overrides = [
			{"row": i.idx, "pct": i.oman_recovery_percentage, "reason": i.get("oman_recovery_override_reason")}
			for i in doc.items
			if cint(i.get("oman_recovery_override"))
		]
		if overrides:
			audit.log_event("Recovery Override", doc.doctype, doc.name, {"overrides": overrides},
				doc.company, doc.oman_vat_registration)
		if alloc or rcm:
			doc.db_set({"oman_recovery_allocation": alloc.name if alloc else None,
				"oman_reverse_charge_entry": rcm.name if rcm else None}, update_modified=False)

	audit.log_event(
		"VAT Document Submitted",
		doc.doctype,
		doc.name,
		{
			"status": doc.oman_vat_validation_status,
			"tax_point": str(doc.oman_tax_point_date),
			"ruleset": doc.oman_vat_ruleset,
			"output_vat": flt(doc.oman_total_output_vat),
			"input_vat": flt(doc.oman_total_input_vat),
			"recoverable": flt(doc.oman_total_recoverable_vat),
			"issues": frappe.parse_json(doc.oman_vat_issues or "[]"),
		},
		doc.company,
		doc.oman_vat_registration,
	)

	from oman_fawtara.fawtara import queue

	queue.on_invoice_submit(doc)


def before_cancel(doc, method=None):
	if not _applies(doc):
		return
	period.assert_open(doc.company, doc.oman_vat_registration, doc.oman_tax_point_date, _("cancel"))
	from oman_fawtara.fawtara import queue

	queue.assert_cancellable(doc)


def on_cancel(doc, method=None):
	if not is_enabled():
		return
	if doc.doctype == "Purchase Invoice":
		recovery.cancel_linked("Oman VAT Recovery Allocation", "purchase_invoice", doc.name)
		recovery.cancel_linked("Oman Reverse Charge Entry", "purchase_invoice", doc.name)
	transaction.cancel_for(doc.doctype, doc.name)
	from oman_fawtara.fawtara import queue

	queue.on_invoice_cancel(doc)
	audit.log_event("VAT Document Cancelled", doc.doctype, doc.name, {}, doc.company, doc.get("oman_vat_registration"))
	doc.ignore_linked_doctypes = tuple(doc.get("ignore_linked_doctypes") or ()) + (
		"Oman VAT Recovery Allocation",
		"Oman Reverse Charge Entry",
		"Oman Fawtara Submission",
	)


def before_update_after_submit(doc, method=None):
	"""VAT figures on a submitted invoice can only change through adjustments."""
	if not is_enabled() or not doc.get_doc_before_save():
		return
	before = doc.get_doc_before_save()
	prev = {r.name: r for r in before.items}
	for item in doc.items:
		old = prev.get(item.name)
		if not old:
			continue
		for f in OMAN_LOCKED_ITEM_FIELDS:
			if item.meta.has_field(f) and str(item.get(f) or "") != str(old.get(f) or ""):
				frappe.throw(_("Row {0}: {1} cannot change after submission. Use an Oman VAT Adjustment.").format(
					item.idx, item.meta.get_label(f)))


# --------------------------------------------------------------------------
# Journal Entry: manual postings on VAT accounts
# --------------------------------------------------------------------------


def journal_before_submit(doc, method=None):
	_journal_guard(doc, _("submit"))


def journal_before_cancel(doc, method=None):
	_journal_guard(doc, _("cancel"))


def _journal_guard(doc, action):
	if not is_enabled() or doc.flags.get("oman_vat_system_entry"):
		return
	from oman_fawtara.vat.utils import has_role, vat_accounts

	accts = vat_accounts(doc.company)
	if not accts or not any(a.account in accts for a in doc.accounts):
		return
	period.assert_open(doc.company, None, doc.posting_date, action)
	s = frappe.get_cached_doc("Oman VAT Settings")
	if cint(s.restrict_manual_vat_journals) and not has_role("Oman VAT Manager", "Oman VAT Approver"):
		frappe.throw(_("Only Oman VAT Managers can post manual Journal Entries on VAT accounts. "
			"Use an Oman VAT Adjustment instead."), frappe.PermissionError)
	audit.log_event("Manual VAT Journal", doc.doctype, doc.name,
		{"action": str(action), "lines": [{"account": a.account, "dr": a.debit, "cr": a.credit} for a in doc.accounts if a.account in accts]},
		doc.company)


# --------------------------------------------------------------------------
# Party masters
# --------------------------------------------------------------------------


def party_validate(doc, method=None):
	if not is_enabled():
		return
	from oman_fawtara.vat.calc import vrn_is_valid

	country = doc.get("oman_party_country") or doc.get("country")
	if doc.get("tax_id") and country in (None, "", "Oman"):
		pattern = frappe.get_cached_value("Oman VAT Settings", None, "vrn_pattern")
		if not vrn_is_valid(doc.tax_id, pattern):
			frappe.msgprint(_("Tax ID {0} does not look like an Oman VAT number.").format(doc.tax_id), indicator="orange")
		elif not doc.get("oman_vat_status"):
			doc.oman_vat_status = "Registered"
	if not doc.get("oman_vat_status"):
		doc.oman_vat_status = "Unregistered" if country in (None, "", "Oman") else "Foreign"


__all__ = ["canonical_json"]
