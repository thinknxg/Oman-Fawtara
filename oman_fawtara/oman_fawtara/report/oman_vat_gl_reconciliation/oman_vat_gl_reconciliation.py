# Copyright (c) 2026, thinkNXG and contributors

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
