# Copyright (c) 2026, thinkNXG and contributors

import frappe
from frappe import _


def execute(filters=None):
	f = frappe._dict(filters or {})
	if not (f.get("company") and f.get("from_date") and f.get("to_date")):
		frappe.throw(_("Company, From Date and To Date are required"))
	data = []
	for dt, party, extra in (("Sales Invoice", "customer", ""), ("Purchase Invoice", "supplier", " and i.oman_self_billing = 1")):
		rows = frappe.db.sql(
			f"""
			select '{dt}' as doctype, i.name, i.posting_date, i.{party} as party, i.base_grand_total,
				i.oman_fawtara_uuid as uuid, i.oman_fawtara_status as invoice_status,
				s.name as submission, s.status as submission_status, s.provider_reference, s.provider_accepted_at,
				s.ota_status, s.ota_reported_at, s.ota_acknowledged_at, s.attempt_count
			from `tab{dt}` i
			left join `tabOman Fawtara Submission` s on s.reference_doctype = '{dt}' and s.reference_name = i.name
				and s.status != 'Cancelled' and s.superseded_by is null
			where i.docstatus = 1 and i.company = %(company)s and i.posting_date between %(from_date)s and %(to_date)s
				and coalesce(i.oman_fawtara_status, '') != 'Not Required' {extra}
			order by i.posting_date, i.name
			""",
			f,
			as_dict=True,
		)
		for r in rows:
			if not r.submission:
				r.exception = _("No submission")
			elif r.submission_status == "Rejected":
				r.exception = _("Rejected")
			elif r.submission_status in ("Pending", "Retry", "Processing", "Draft"):
				r.exception = _("Not yet accepted")
			elif r.ota_status not in ("Reported", "Acknowledged"):
				r.exception = _("Accepted by provider, not reported to OTA")
			else:
				r.exception = ""
			if not f.get("only_exceptions") or r.exception:
				data.append(r)
	columns = [
		{"fieldname": "doctype", "label": _("Type"), "fieldtype": "Data", "width": 120},
		{"fieldname": "name", "label": _("Invoice"), "fieldtype": "Dynamic Link", "options": "doctype", "width": 160},
		{"fieldname": "posting_date", "label": _("Date"), "fieldtype": "Date", "width": 100},
		{"fieldname": "party", "label": _("Party"), "fieldtype": "Data", "width": 160},
		{"fieldname": "base_grand_total", "label": _("Grand Total"), "fieldtype": "Currency", "width": 120},
		{"fieldname": "uuid", "label": _("UUID"), "fieldtype": "Data", "width": 140},
		{"fieldname": "submission", "label": _("Submission"), "fieldtype": "Link", "options": "Oman Fawtara Submission", "width": 160},
		{"fieldname": "submission_status", "label": _("Provider Status"), "fieldtype": "Data", "width": 110},
		{"fieldname": "provider_reference", "label": _("Provider Ref"), "fieldtype": "Data", "width": 130},
		{"fieldname": "provider_accepted_at", "label": _("Accepted At"), "fieldtype": "Datetime", "width": 150},
		{"fieldname": "ota_status", "label": _("OTA Status"), "fieldtype": "Data", "width": 110},
		{"fieldname": "ota_reported_at", "label": _("Reported At"), "fieldtype": "Datetime", "width": 150},
		{"fieldname": "attempt_count", "label": _("Attempts"), "fieldtype": "Int", "width": 80},
		{"fieldname": "exception", "label": _("Exception"), "fieldtype": "Data", "width": 240},
	]
	return columns, data
