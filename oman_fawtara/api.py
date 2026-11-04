"""Whitelisted endpoints used by the desk UI and integrations."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import getdate

from oman_fawtara.vat import engine


@frappe.whitelist()
def preview_vat(doc: str | dict):
	"""Run the VAT engine on an unsaved/saved invoice without persisting anything."""
	d = frappe.get_doc(frappe.parse_json(doc))
	d.check_permission("read")
	d.run_method("calculate_taxes_and_totals")
	a = engine.analyse(d, persist=False)
	return {
		"status": a.status,
		"issues": a.issues,
		"totals": a.totals,
		"lines": [{k: (float(v) if hasattr(v, "quantize") else v) for k, v in l.items()} for l in a.lines],
	}


@frappe.whitelist()
def fawtara_preview_xml(doctype: str, name: str):
	from oman_fawtara.fawtara import queue

	doc = frappe.get_doc(doctype, name)
	doc.check_permission("read")
	inv, xml, issues = queue.generate(doc)
	return {"xml": xml.decode("utf-8"), "issues": issues}


@frappe.whitelist()
def dashboard(company: str | None = None):
	"""Numbers for the Oman Fawtara workspace."""
	filters = {"company": company} if company else {}
	today = getdate()
	regs = frappe.get_all("Oman VAT Registration", filters=filters,
		fields=["name", "vatin", "status", "company", "fawtara_enabled"])
	current = frappe.get_all("Oman VAT Period",
		filters={**filters, "from_date": ["<=", today], "to_date": [">=", today]},
		fields=["name", "vat_registration", "status", "due_date"])
	sub_counts = frappe.db.sql(
		"""select status, count(*) n from `tabOman Fawtara Submission`
		{} group by status""".format("where company=%(company)s" if company else ""),
		{"company": company},
		as_dict=True,
	)
	failed_docs = frappe.db.count("Sales Invoice", {**filters, "docstatus": 0, "oman_vat_validation_status": "Failed"}) + \
		frappe.db.count("Purchase Invoice", {**filters, "docstatus": 0, "oman_vat_validation_status": "Failed"})
	pending_evidence = frappe.db.count("Purchase Invoice Item", {"oman_recovery_status": "Pending Evidence", "docstatus": 1})
	return {
		"registrations": regs,
		"current_periods": current,
		"submissions": {r.status: r.n for r in sub_counts},
		"validation_exceptions": failed_docs,
		"recovery_exceptions": pending_evidence,
		"needs_attention": frappe.db.count("Oman Fawtara Submission", {**filters, "needs_attention": 1}),
		"legal_review_pending": not frappe.db.get_single_value("Oman VAT Settings", "legal_review_confirmed"),
	}
