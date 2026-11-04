# Copyright (c) 2026, thinkNXG and contributors

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
