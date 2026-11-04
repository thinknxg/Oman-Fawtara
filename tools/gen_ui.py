#!/usr/bin/env python3
"""Generate reports, workspace, v16 workspace sidebar and desktop icon."""

import json
import os
import random
import sys

APP = "oman_fawtara"
MODULE = "Oman Fawtara"
TS = "2026-11-04 12:00:00.000000"
random.seed(16)

VAT_ROLES = ["System Manager", "Accounts Manager", "Oman VAT User", "Oman VAT Manager", "Oman VAT Approver", "Auditor"]
F_ROLES = ["System Manager", "Fawtara Manager", "Fawtara Operator", "Oman VAT Manager", "Auditor"]

REGISTER_REPORTS = {
	"Oman Sales VAT Register": "sales",
	"Oman Purchase VAT Register": "purchase",
	"Oman Zero-Rated Sales": "zero_rated",
	"Oman Exempt Supplies": "exempt",
	"Oman Reverse Charge Register": "reverse_charge",
	"Oman Import VAT Register": "imports",
	"Oman Input VAT Recovery": "recovery",
	"Oman VAT Adjustment Register": "adjustments",
}

STD_FILTERS_JS = """[
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company", reqd: 1,
			default: frappe.defaults.get_user_default("Company") },
		{ fieldname: "vat_registration", label: __("VAT Registration"), fieldtype: "Link", options: "Oman VAT Registration",
			get_query: () => ({ filters: { company: frappe.query_report.get_filter_value("company") } }) },
		{ fieldname: "vat_period", label: __("VAT Period"), fieldtype: "Link", options: "Oman VAT Period" },
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date" },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date" },
		{ fieldname: "treatment", label: __("Treatment"), fieldtype: "Link", options: "Oman VAT Treatment" }%s
	]"""


def snake(n):
	import re

	return re.sub(r"[^a-z0-9]+", "_", n.lower()).strip("_")


def write(path, content):
	os.makedirs(os.path.dirname(path), exist_ok=True)
	with open(path, "w") as fh:
		fh.write(content)


def report(root, name, ref, roles, py, js, add_total_row=1):
	s = snake(name)
	base = os.path.join(root, APP, "oman_fawtara", "report", s)
	write(os.path.join(base, "__init__.py"), "")
	doc = {
		"add_total_row": add_total_row,
		"columns": [],
		"creation": TS,
		"disabled": 0,
		"docstatus": 0,
		"doctype": "Report",
		"filters": [],
		"idx": 0,
		"is_standard": "Yes",
		"letterhead": None,
		"modified": TS,
		"modified_by": "Administrator",
		"module": MODULE,
		"name": name,
		"owner": "Administrator",
		"prepared_report": 0,
		"ref_doctype": ref,
		"report_name": name,
		"report_type": "Script Report",
		"roles": [{"role": r} for r in roles],
	}
	write(os.path.join(base, f"{s}.json"), json.dumps(doc, indent=1) + "\n")
	write(os.path.join(base, f"{s}.py"), py)
	write(os.path.join(base, f"{s}.js"), js)


def gen_reports(root):
	write(os.path.join(root, APP, "oman_fawtara", "report", "__init__.py"), "")
	for name, preset in REGISTER_REPORTS.items():
		extra = ""
		if preset == "recovery":
			extra = ',\n\t\t{ fieldname: "only_restricted", label: __("Only Restricted Recovery"), fieldtype: "Check" }'
		py = (
			"# Copyright (c) 2026, thinkNXG and contributors\n\n"
			"from oman_fawtara.vat.registers import get_register\n\n\n"
			f"def execute(filters=None):\n\treturn get_register(filters, \"{preset}\")\n"
		)
		js = f'frappe.query_reports["{name}"] = {{\n\tfilters: {STD_FILTERS_JS % extra},\n}};\n'
		report(root, name, "Oman VAT Transaction", VAT_ROLES, py, js)

	report(
		root,
		"Oman VAT Return Working Paper",
		"Oman VAT Return",
		VAT_ROLES,
		'''# Copyright (c) 2026, thinkNXG and contributors

import frappe
from frappe import _

from oman_fawtara.vat.returns import preview_boxes


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.get("vat_period"):
		frappe.throw(_("Select a VAT period"))
	rows = preview_boxes(filters.vat_period)
	columns = [
		{"fieldname": "section", "label": _("Section"), "fieldtype": "Data", "width": 160},
		{"fieldname": "box_code", "label": _("Box"), "fieldtype": "Link", "options": "Oman VAT Return Box", "width": 100},
		{"fieldname": "label", "label": _("Description"), "fieldtype": "Data", "width": 420},
		{"fieldname": "value_type", "label": _("Type"), "fieldtype": "Data", "width": 110},
		{"fieldname": "amount", "label": _("Amount (OMR)"), "fieldtype": "Float", "precision": 3, "width": 150},
	]
	return columns, rows
''',
		'''frappe.query_reports["Oman VAT Return Working Paper"] = {
	filters: [
		{ fieldname: "vat_period", label: __("VAT Period"), fieldtype: "Link", options: "Oman VAT Period", reqd: 1 },
	],
};
''',
		add_total_row=0,
	)

	report(
		root,
		"Oman VAT GL Reconciliation",
		"Oman VAT Transaction",
		VAT_ROLES,
		'''# Copyright (c) 2026, thinkNXG and contributors

import frappe
from frappe import _

from oman_fawtara.vat.reconciliation import compute


def execute(filters=None):
	f = frappe._dict(filters or {})
	for k in ("company", "vat_registration", "from_date", "to_date"):
		if not f.get(k):
			frappe.throw(_("{0} is required").format(k.replace("_", " ").title()))
	columns = [
		{"fieldname": "account", "label": _("Account"), "fieldtype": "Link", "options": "Account", "width": 280},
		{"fieldname": "natural_side", "label": _("Side"), "fieldtype": "Data", "width": 80},
		{"fieldname": "register_amount", "label": _("VAT Register"), "fieldtype": "Float", "precision": 3, "width": 150},
		{"fieldname": "gl_amount", "label": _("General Ledger"), "fieldtype": "Float", "precision": 3, "width": 150},
		{"fieldname": "difference", "label": _("Difference"), "fieldtype": "Float", "precision": 3, "width": 130},
	]
	return columns, compute(f.company, f.vat_registration, f.from_date, f.to_date)
''',
		'''frappe.query_reports["Oman VAT GL Reconciliation"] = {
	filters: [
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company", reqd: 1,
			default: frappe.defaults.get_user_default("Company") },
		{ fieldname: "vat_registration", label: __("VAT Registration"), fieldtype: "Link", options: "Oman VAT Registration", reqd: 1 },
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date", reqd: 1 },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date", reqd: 1 },
	],
};
''',
	)

	report(
		root,
		"Oman Fawtara Reconciliation",
		"Oman Fawtara Submission",
		F_ROLES,
		'''# Copyright (c) 2026, thinkNXG and contributors

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
''',
		'''frappe.query_reports["Oman Fawtara Reconciliation"] = {
	filters: [
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company", reqd: 1,
			default: frappe.defaults.get_user_default("Company") },
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date", reqd: 1, default: frappe.datetime.month_start() },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date", reqd: 1, default: frappe.datetime.get_today() },
		{ fieldname: "only_exceptions", label: __("Only Exceptions"), fieldtype: "Check", default: 1 },
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "exception" && data && data.exception) {
			value = `<span style="color: var(--red-600)">${value}</span>`;
		}
		return value;
	},
};
''',
		add_total_row=0,
	)


def rid():
	return "".join(random.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(10))


SHORTCUTS = [
	("VAT Registrations", "DocType", "Oman VAT Registration", "Blue", '{"status":"Active"}', "{} Active"),
	("Current VAT Periods", "DocType", "Oman VAT Period", "Green", '[["Oman VAT Period","status","in",["Open","Under Review"]]]', "{} Open"),
	("Validation Exceptions", "DocType", "Oman VAT Validation Log", "Red", '{"status":"Failed"}', "{} Failed"),
	("Recovery Exceptions", "Report", "Oman Input VAT Recovery", "Orange", None, None),
	("Fawtara Queue", "DocType", "Oman Fawtara Submission", "Yellow", '[["Oman Fawtara Submission","status","in",["Pending","Processing","Retry"]]]', "{} In Progress"),
	("Fawtara Rejections", "DocType", "Oman Fawtara Submission", "Red", '{"status":"Rejected"}', "{} Rejected"),
	("VAT Returns", "DocType", "Oman VAT Return", "Purple", '[["Oman VAT Return","status","not in",["Filed","Locked"]]]', "{} In Progress"),
	("Return Reconciliation", "DocType", "Oman VAT Reconciliation", "Cyan", '{"status":"Differences"}', "{} With Differences"),
	("Period Locks", "DocType", "Oman VAT Period Lock", "Grey", None, None),
	("Fawtara Reconciliation", "Report", "Oman Fawtara Reconciliation", "Pink", None, None),
]

CARDS = [
	("VAT Configuration", [
		("Oman VAT Settings", "DocType"), ("Oman VAT Registration", "DocType"), ("Oman VAT Treatment", "DocType"),
		("Oman VAT Code", "DocType"), ("Oman VAT Rule", "DocType"), ("Oman VAT Rate History", "DocType"),
		("Oman VAT Account Mapping", "DocType"), ("Oman VAT Return Box", "DocType"), ("Oman VAT Evidence Type", "DocType")]),
	("VAT Validation", [("Oman VAT Validation Log", "DocType"), ("Oman VAT Evidence", "DocType"),
		("Oman VAT Transaction", "DocType")]),
	("VAT Return", [("Oman VAT Return", "DocType"), ("Oman VAT Return Working Paper", "Report"),
		("Oman VAT Period", "DocType"), ("Oman VAT Period Lock", "DocType"), ("Oman VAT Return Snapshot", "DocType"),
		("Oman VAT Filing Record", "DocType"), ("Oman VAT Reconciliation", "DocType"), ("Oman VAT GL Reconciliation", "Report")]),
	("VAT Recovery", [("Oman VAT Recovery Profile", "DocType"), ("Oman VAT Recovery Rule", "DocType"),
		("Oman VAT Recovery Allocation", "DocType"), ("Oman VAT Recovery Adjustment", "DocType"), ("Oman Input VAT Recovery", "Report")]),
	("Reverse Charge", [("Oman Reverse Charge Entry", "DocType"), ("Oman Reverse Charge Register", "Report")]),
	("Import Register", [("Oman Import Declaration", "DocType"), ("Oman Import VAT Register", "Report")]),
	("Adjustments", [("Oman VAT Adjustment", "DocType"), ("Oman VAT Adjustment Register", "Report")]),
	("Registers", [("Oman Sales VAT Register", "Report"), ("Oman Purchase VAT Register", "Report"),
		("Oman Zero-Rated Sales", "Report"), ("Oman Exempt Supplies", "Report")]),
	("Fawtara Queue", [("Oman Fawtara Submission", "DocType"), ("Oman Fawtara Error Log", "DocType"),
		("Oman Fawtara Submission Log", "DocType"), ("Oman Fawtara Reconciliation", "Report")]),
	("Submission Receipts", [("Oman Fawtara Receipt", "DocType"), ("Oman Fawtara Document", "DocType")]),
	("Fawtara Setup", [("Oman Fawtara Settings", "DocType"), ("Oman Fawtara Provider", "DocType"),
		("Oman Fawtara Certificate", "DocType")]),
	("Audit Trail", [("Oman Compliance Audit Log", "DocType")]),
]


def gen_workspace(root):
	content = [{"id": rid(), "type": "header", "data": {"text": '<span class="h4"><b>Compliance workflow</b></span>', "col": 12}}]
	for s in SHORTCUTS:
		content.append({"id": rid(), "type": "shortcut", "data": {"shortcut_name": s[0], "col": 3}})
	content.append({"id": rid(), "type": "spacer", "data": {"col": 12}})
	content.append({"id": rid(), "type": "header", "data": {"text": '<span class="h4"><b>Quick access</b></span>', "col": 12}})
	for c in CARDS:
		content.append({"id": rid(), "type": "card", "data": {"card_name": c[0], "col": 4}})
	links = []
	for card, items in CARDS:
		links.append({"hidden": 0, "is_query_report": 0, "label": card, "link_count": len(items), "onboard": 0,
			"type": "Card Break"})
		for label, ltype in items:
			links.append({"hidden": 0, "is_query_report": 1 if ltype == "Report" else 0, "label": label,
				"link_count": 0, "link_to": label, "link_type": ltype, "onboard": 0, "type": "Link",
				"dependencies": ""})
	shortcuts = []
	for label, stype, link, color, stats, fmt in SHORTCUTS:
		sc = {"color": color, "doc_view": "List" if stype == "DocType" else "", "label": label, "link_to": link,
			"type": stype}
		if stats:
			sc["stats_filter"] = stats
		if fmt:
			sc["format"] = fmt
		shortcuts.append(sc)
	ws = {
		"app": APP,
		"charts": [],
		"content": json.dumps(content),
		"creation": TS,
		"custom_blocks": [],
		"docstatus": 0,
		"doctype": "Workspace",
		"for_user": "",
		"hide_custom": 0,
		"icon": "receipt-text",
		"idx": 0,
		"indicator_color": "green",
		"is_hidden": 0,
		"label": "Oman Fawtara",
		"link_type": "DocType",
		"links": links,
		"modified": TS,
		"modified_by": "Administrator",
		"module": MODULE,
		"name": "Oman Fawtara",
		"number_cards": [],
		"owner": "Administrator",
		"public": 1,
		"quick_lists": [],
		"roles": [],
		"sequence_id": 50.0,
		"shortcuts": shortcuts,
		"standard": 1,
		"title": "Oman Fawtara",
		"type": "Workspace",
	}
	write(os.path.join(root, APP, "oman_fawtara", "workspace", "oman_fawtara", "oman_fawtara.json"),
		json.dumps(ws, indent=1, ensure_ascii=False) + "\n")


def gen_sidebar(root):
	def link(label, link_to, ltype="DocType", icon=None, child=0):
		d = {"child": child, "collapsible": 1, "indent": 0, "keep_closed": 0, "label": label, "link_to": link_to,
			"link_type": ltype, "show_arrow": 0, "type": "Link"}
		if icon:
			d["icon"] = icon
		return d

	def section(label, icon):
		return {"child": 0, "collapsible": 1, "icon": icon, "indent": 1, "keep_closed": 1, "label": label,
			"link_type": "DocType", "show_arrow": 0, "type": "Section Break"}

	items = [
		link("Home", "Oman Fawtara", "Workspace", "house"),
		link("VAT Return", "Oman VAT Return", icon="file-check"),
		link("Fawtara Queue", "Oman Fawtara Submission", icon="send"),
		link("Import Declaration", "Oman Import Declaration", icon="ship"),
		link("VAT Adjustment", "Oman VAT Adjustment", icon="scale"),
		section("Registers", "book-open"),
		*[link(n, n, "Report", child=1) for n in REGISTER_REPORTS],
		link("Oman Fawtara Reconciliation", "Oman Fawtara Reconciliation", "Report", child=1),
		link("Oman VAT GL Reconciliation", "Oman VAT GL Reconciliation", "Report", child=1),
		section("Setup", "settings"),
		*[link(n, n, child=1) for n in ("Oman VAT Settings", "Oman VAT Registration", "Oman VAT Treatment", "Oman VAT Code",
			"Oman VAT Rule", "Oman VAT Rate History", "Oman VAT Account Mapping", "Oman VAT Recovery Profile",
			"Oman VAT Recovery Rule", "Oman Fawtara Settings", "Oman Fawtara Provider", "Oman Fawtara Certificate")],
		section("Audit", "shield-check"),
		*[link(n, n, child=1) for n in ("Oman Compliance Audit Log", "Oman VAT Transaction", "Oman VAT Validation Log",
			"Oman VAT Return Snapshot", "Oman Fawtara Document")],
	]
	sb = {
		"app": APP,
		"creation": TS,
		"docstatus": 0,
		"doctype": "Workspace Sidebar",
		"header_icon": "receipt-text",
		"idx": 0,
		"items": items,
		"modified": TS,
		"modified_by": "Administrator",
		"module": MODULE,
		"name": "Oman Fawtara",
		"owner": "Administrator",
		"standard": 1,
		"title": "Oman Fawtara",
	}
	# Legacy (earlier v16 builds): app-level Workspace Sidebar fixture
	write(os.path.join(root, APP, "workspace_sidebar", "oman_fawtara.json"), json.dumps(sb, indent=1) + "\n")
	# Current v16: module-level Sidebar + app-root Dock
	new_items = [{"added": 0, "hidden": 0, "is_default_module": 0, "open_in_new_tab": 0, **i} for i in items]
	sidebar = {**sb, "doctype": "Sidebar", "header_icon": "quality-seal-duotone", "items": new_items}
	write(os.path.join(root, APP, "oman_fawtara", "sidebar", "oman_fawtara", "oman_fawtara.json"),
		json.dumps(sidebar, indent=1) + "\n")
	dock = {"app": APP, "creation": TS, "docstatus": 0, "doctype": "Dock", "idx": 0, "modified": TS,
		"modified_by": "Administrator", "name": APP, "owner": "Administrator", "standard": 1, "user": "",
		"items": [{"added": 0, "hidden": 0, "icon": "quality-seal-soft", "link_to": "Oman Fawtara",
			"link_type": "Sidebar", "title": "Oman Fawtara"}]}
	write(os.path.join(root, APP, "dock", APP, f"{APP}.json"), json.dumps(dock, indent=1) + "\n")
	icon = {
		"app": APP,
		"creation": TS,
		"docstatus": 0,
		"doctype": "Desktop Icon",
		"hidden": 0,
		"icon": "receipt-text",
		"icon_type": "Link",
		"idx": 50,
		"label": "Oman Fawtara",
		"link_to": "Oman Fawtara",
		"link_type": "Workspace Sidebar",
		"modified": TS,
		"modified_by": "Administrator",
		"name": "Oman Fawtara",
		"owner": "Administrator",
		"parent_icon": "",
		"restrict_removal": 0,
		"roles": [],
		"standard": 1,
	}
	write(os.path.join(root, APP, "desktop_icon", "oman_fawtara.json"), json.dumps(icon, indent=1) + "\n")


if __name__ == "__main__":
	r = sys.argv[1]
	gen_reports(r)
	gen_workspace(r)
	gen_sidebar(r)
	print("ui generated")
