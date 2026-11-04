"""Shared query layer for the Oman VAT register reports."""

from __future__ import annotations

import frappe
from frappe import _

PRESETS = {
	"sales": {"direction": "Sales"},
	"purchase": {"direction": "Purchase"},
	"zero_rated": {"direction": "Sales", "nature": "Zero Rated"},
	"exempt": {"direction": "Sales", "nature": "Exempt"},
	"reverse_charge": {"reverse_charge": 1, "exclude_import_decl": 1},
	"imports": {"is_import": 1},
	"recovery": {"direction": "Purchase"},
	"adjustments": {"is_adjustment": 1},
}

COLUMNS = [
	{"fieldname": "tax_point_date", "label": _("Tax Point"), "fieldtype": "Date", "width": 100},
	{"fieldname": "source_doctype", "label": _("Document Type"), "fieldtype": "Data", "width": 140},
	{"fieldname": "source_name", "label": _("Document"), "fieldtype": "Dynamic Link", "options": "source_doctype", "width": 160},
	{"fieldname": "party", "label": _("Party"), "fieldtype": "Data", "width": 160},
	{"fieldname": "party_vrn", "label": _("VAT No."), "fieldtype": "Data", "width": 130},
	{"fieldname": "party_country", "label": _("Country"), "fieldtype": "Data", "width": 100},
	{"fieldname": "item_code", "label": _("Item"), "fieldtype": "Link", "options": "Item", "width": 130},
	{"fieldname": "treatment", "label": _("Treatment"), "fieldtype": "Link", "options": "Oman VAT Treatment", "width": 130},
	{"fieldname": "vat_code", "label": _("VAT Code"), "fieldtype": "Link", "options": "Oman VAT Code", "width": 110},
	{"fieldname": "rate", "label": _("Rate %"), "fieldtype": "Percent", "width": 70},
	{"fieldname": "taxable_amount", "label": _("Taxable (OMR)"), "fieldtype": "Float", "precision": 3, "width": 120},
	{"fieldname": "output_vat", "label": _("Output VAT"), "fieldtype": "Float", "precision": 3, "width": 110},
	{"fieldname": "input_vat", "label": _("Input VAT"), "fieldtype": "Float", "precision": 3, "width": 110},
	{"fieldname": "recovery_percentage", "label": _("Recovery %"), "fieldtype": "Percent", "width": 90},
	{"fieldname": "recoverable_vat", "label": _("Recoverable"), "fieldtype": "Float", "precision": 3, "width": 110},
	{"fieldname": "nonrecoverable_vat", "label": _("Non-Recoverable"), "fieldtype": "Float", "precision": 3, "width": 120},
	{"fieldname": "rcm_output_vat", "label": _("RCM Output VAT"), "fieldtype": "Float", "precision": 3, "width": 120},
	{"fieldname": "recovery_status", "label": _("Recovery Status"), "fieldtype": "Data", "width": 140},
	{"fieldname": "vat_return", "label": _("VAT Return"), "fieldtype": "Link", "options": "Oman VAT Return", "width": 130},
]


def get_register(filters, preset: str):
	filters = frappe._dict(filters or {})
	p = PRESETS[preset]
	cond = ["t.status = 'Active'"]
	vals = {}
	for key in ("company", "vat_registration"):
		if filters.get(key):
			cond.append(f"t.{key} = %({key})s")
			vals[key] = filters[key]
	if filters.get("from_date"):
		cond.append("t.tax_point_date >= %(from_date)s")
		vals["from_date"] = filters.from_date
	if filters.get("to_date"):
		cond.append("t.tax_point_date <= %(to_date)s")
		vals["to_date"] = filters.to_date
	if filters.get("vat_period"):
		cond.append("t.vat_period = %(vat_period)s")
		vals["vat_period"] = filters.vat_period
	if filters.get("treatment"):
		cond.append("d.treatment = %(treatment)s")
		vals["treatment"] = filters.treatment
	if p.get("direction"):
		cond.append("t.direction = %(direction)s")
		vals["direction"] = p["direction"]
	if p.get("nature"):
		cond.append("tr.nature = %(nature)s")
		vals["nature"] = p["nature"]
	if p.get("reverse_charge"):
		cond.append("d.reverse_charge = 1")
	if p.get("exclude_import_decl"):
		cond.append("t.source_doctype != 'Oman Import Declaration'")
	if p.get("is_import"):
		cond.append("d.is_import = 1")
	if p.get("is_adjustment"):
		cond.append("t.is_adjustment = 1")
	if preset == "recovery" and filters.get("only_restricted"):
		cond.append("d.recovery_percentage < 100")

	data = frappe.db.sql(
		f"""
		select t.tax_point_date, t.source_doctype, t.source_name, t.party, t.party_vrn, t.party_country,
			d.item_code, d.treatment, d.vat_code, d.rate, d.taxable_amount, d.output_vat, d.input_vat,
			d.recovery_percentage, d.recoverable_vat, d.nonrecoverable_vat, d.rcm_output_vat,
			d.recovery_status, t.vat_return
		from `tabOman VAT Transaction` t
		join `tabOman VAT Transaction Detail` d on d.parent = t.name
		left join `tabOman VAT Treatment` tr on tr.name = d.treatment
		where {' and '.join(cond)}
		order by t.tax_point_date, t.source_name, d.idx
		""",
		vals,
		as_dict=True,
	)
	return COLUMNS, data


STANDARD_FILTERS = [
	{"fieldname": "company", "label": "Company", "fieldtype": "Link", "options": "Company", "reqd": 1},
	{"fieldname": "vat_registration", "label": "VAT Registration", "fieldtype": "Link", "options": "Oman VAT Registration"},
	{"fieldname": "vat_period", "label": "VAT Period", "fieldtype": "Link", "options": "Oman VAT Period"},
	{"fieldname": "from_date", "label": "From Date", "fieldtype": "Date"},
	{"fieldname": "to_date", "label": "To Date", "fieldtype": "Date"},
	{"fieldname": "treatment", "label": "Treatment", "fieldtype": "Link", "options": "Oman VAT Treatment"},
]
