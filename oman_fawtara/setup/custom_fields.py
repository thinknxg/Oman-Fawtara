"""Custom fields added to standard ERPNext doctypes (created on install/migrate, removed on uninstall)."""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

ADJ_REASONS = "\nReturn of Goods\nPrice Reduction / Discount\nCancellation of Supply\nChange in Consideration\nIncorrect VAT Treatment\nIncorrect Amount\nBad Debt\nOther"
FAWTARA_STATUS = "\nNot Required\nDraft\nPending\nProcessing\nAccepted\nReported\nAcknowledged\nRejected\nRetry\nCancelled"


def _money(fieldname, label, **kw):
	return {"fieldname": fieldname, "label": label, "fieldtype": "Float", "precision": "3", "read_only": 1,
		"no_copy": 1, **kw}


def _last_field(doctype):
	meta = frappe.get_meta(doctype)
	std = [df.fieldname for df in meta.fields if not df.get("is_custom_field") and not df.fieldname.startswith("oman_")]
	return std[-1] if std else None


def _chain(doctype, fields):
	"""Insert fields in order after the last standard field of ``doctype``."""
	prev = _last_field(doctype)
	out = []
	for f in fields:
		f = dict(f)
		f["insert_after"] = prev
		f.setdefault("translatable", 0)
		out.append(f)
		prev = f["fieldname"]
	return out


def invoice_header(doctype):
	sales = doctype == "Sales Invoice"
	party = "customer" if sales else "supplier"
	fields = [
		{"fieldname": "oman_vat_tab", "label": "Oman VAT", "fieldtype": "Tab Break"},
		{"fieldname": "oman_vat_registration", "label": "VAT Registration", "fieldtype": "Link",
			"options": "Oman VAT Registration", "no_copy": 0},
		{"fieldname": "oman_tax_point_date", "label": "Tax Point Date", "fieldtype": "Date", "no_copy": 1,
			"description": "Leave empty to derive from the supply and invoice dates."},
	]
	if sales:
		fields += [
			{"fieldname": "oman_supply_date", "label": "Date of Supply", "fieldtype": "Date", "no_copy": 1},
			{"fieldname": "oman_buyer_type", "label": "Buyer Type", "fieldtype": "Select", "options": "\nB2B\nB2C\nB2G",
				"fetch_from": "customer.oman_buyer_type_default", "fetch_if_empty": 1},
			{"fieldname": "oman_export_destination", "label": "Export Destination Country", "fieldtype": "Link",
				"options": "Country"},
		]
	else:
		fields += [
			{"fieldname": "oman_self_billing", "label": "Self-billed (buyer issues e-invoice)", "fieldtype": "Check"},
			{"fieldname": "oman_import_declaration", "label": "Customs Import Declaration", "fieldtype": "Link",
				"options": "Oman Import Declaration", "no_copy": 1},
			{"fieldname": "oman_bayan_reference", "label": "Bayan Reference", "fieldtype": "Data", "no_copy": 1},
		]
	fields += [
		{"fieldname": "oman_party_country", "label": "Party Country", "fieldtype": "Link", "options": "Country",
			"fetch_from": f"{party}.oman_party_country", "read_only": 1},
		{"fieldname": "oman_vat_cb1", "fieldtype": "Column Break"},
		{"fieldname": "oman_vat_period", "label": "VAT Period", "fieldtype": "Link", "options": "Oman VAT Period",
			"read_only": 1, "no_copy": 1},
		{"fieldname": "oman_adjustment_reason", "label": "VAT Adjustment Reason", "fieldtype": "Select",
			"options": ADJ_REASONS, "depends_on": "eval:doc.is_return || doc.is_debit_note", "no_copy": 1},
		{"fieldname": "oman_vat_validation_status", "label": "VAT Validation", "fieldtype": "Select",
			"options": "\nPassed\nWarnings\nFailed", "read_only": 1, "no_copy": 1, "in_standard_filter": 1},
		{"fieldname": "oman_vat_ruleset", "label": "Rule-set Version", "fieldtype": "Data", "read_only": 1, "no_copy": 1},
		{"fieldname": "oman_vat_summary_section", "label": "VAT Summary (OMR)", "fieldtype": "Section Break"},
		_money("oman_total_taxable_amount", "Taxable Amount"),
		_money("oman_total_output_vat", "Output VAT"),
		_money("oman_total_input_vat", "Input VAT"),
		{"fieldname": "oman_vat_cb2", "fieldtype": "Column Break"},
		_money("oman_total_recoverable_vat", "Recoverable Input VAT"),
		_money("oman_total_nonrecoverable_vat", "Non-recoverable Input VAT"),
		_money("oman_total_rcm_vat", "Reverse Charge VAT"),
		{"fieldname": "oman_reverse_charge", "label": "Reverse Charge Applies", "fieldtype": "Check", "read_only": 1, "no_copy": 1},
		{"fieldname": "oman_vat_issues", "label": "Validation Issues", "fieldtype": "Code", "options": "JSON",
			"read_only": 1, "no_copy": 1, "collapsible": 1},
	]
	if not sales:
		fields += [
			{"fieldname": "oman_duplicate_check_key", "label": "Duplicate Check Key", "fieldtype": "Data", "hidden": 1,
				"read_only": 1, "no_copy": 1, "search_index": 1},
			{"fieldname": "oman_recovery_allocation", "label": "Recovery Allocation", "fieldtype": "Link",
				"options": "Oman VAT Recovery Allocation", "read_only": 1, "no_copy": 1},
			{"fieldname": "oman_reverse_charge_entry", "label": "Reverse Charge Entry", "fieldtype": "Link",
				"options": "Oman Reverse Charge Entry", "read_only": 1, "no_copy": 1},
		]
	fields += [
		{"fieldname": "oman_fawtara_section", "label": "Fawtara E-invoice", "fieldtype": "Section Break"},
		{"fieldname": "oman_fawtara_status", "label": "Fawtara Status", "fieldtype": "Select", "options": FAWTARA_STATUS,
			"read_only": 1, "no_copy": 1, "allow_on_submit": 1, "in_standard_filter": 1},
		{"fieldname": "oman_fawtara_uuid", "label": "E-invoice UUID", "fieldtype": "Data", "read_only": 1, "no_copy": 1,
			"allow_on_submit": 1, "search_index": 1},
		{"fieldname": "oman_fawtara_submission", "label": "Fawtara Submission", "fieldtype": "Link",
			"options": "Oman Fawtara Submission", "read_only": 1, "no_copy": 1, "allow_on_submit": 1},
		{"fieldname": "oman_fawtara_cb", "fieldtype": "Column Break"},
		{"fieldname": "oman_einvoice_exempt", "label": "No E-invoice Required", "fieldtype": "Check", "no_copy": 1},
		{"fieldname": "oman_einvoice_note", "label": "E-invoice Note", "fieldtype": "Small Text"},
		{"fieldname": "oman_fawtara_note", "label": "Fawtara Note", "fieldtype": "Small Text", "read_only": 1,
			"no_copy": 1, "allow_on_submit": 1},
	]
	return _chain(doctype, fields)


def invoice_item(doctype):
	sales = doctype == "Sales Invoice Item"
	fields = [
		{"fieldname": "oman_vat_section", "label": "Oman VAT", "fieldtype": "Section Break", "collapsible": 1},
		{"fieldname": "oman_vat_treatment", "label": "VAT Treatment", "fieldtype": "Link", "options": "Oman VAT Treatment",
			"in_list_view": 0},
		{"fieldname": "oman_vat_code", "label": "VAT Code", "fieldtype": "Link", "options": "Oman VAT Code"},
		{"fieldname": "oman_vat_source", "label": "Treatment Source", "fieldtype": "Data", "hidden": 1,
			"description": "Empty/line = chosen by user; otherwise derived by the engine and recomputed on save."},
		{"fieldname": "oman_supply_category", "label": "Supply Category", "fieldtype": "Select", "options": "\nGoods\nServices"},
		{"fieldname": "oman_tax_evidence", "label": "Tax Evidence", "fieldtype": "Link", "options": "Oman VAT Evidence"},
		{"fieldname": "oman_vat_rate", "label": "VAT Rate", "fieldtype": "Percent", "read_only": 1, "no_copy": 1},
		{"fieldname": "oman_rate_reference", "label": "Rate Reference", "fieldtype": "Link", "options": "Oman VAT Rate History",
			"read_only": 1, "no_copy": 1, "hidden": 1},
		{"fieldname": "oman_vat_item_cb", "fieldtype": "Column Break"},
		_money("oman_taxable_amount", "Taxable Amount (OMR)"),
		_money("oman_output_vat", "Output VAT (OMR)", hidden=0 if sales else 1),
		_money("oman_input_vat", "Input VAT (OMR)", hidden=1 if sales else 0),
		{"fieldname": "oman_reverse_charge", "label": "Reverse Charge", "fieldtype": "Check", "read_only": 1, "no_copy": 1},
		{"fieldname": "oman_recovery_profile", "label": "Recovery Profile", "fieldtype": "Link",
			"options": "Oman VAT Recovery Profile", "hidden": 1 if sales else 0},
		{"fieldname": "oman_recovery_override", "label": "Override Recovery %", "fieldtype": "Check",
			"hidden": 1 if sales else 0, "no_copy": 1},
		{"fieldname": "oman_recovery_percentage", "label": "Recovery %", "fieldtype": "Percent", "no_copy": 1,
			"hidden": 1 if sales else 0, "read_only_depends_on": "eval:!doc.oman_recovery_override"},
		{"fieldname": "oman_recovery_override_reason", "label": "Override Reason", "fieldtype": "Small Text",
			"depends_on": "oman_recovery_override", "no_copy": 1, "hidden": 1 if sales else 0},
		_money("oman_recoverable_vat", "Recoverable VAT (OMR)", hidden=1 if sales else 0),
		_money("oman_nonrecoverable_vat", "Non-recoverable VAT (OMR)", hidden=1 if sales else 0),
		{"fieldname": "oman_recovery_status", "label": "Recovery Status", "fieldtype": "Data", "read_only": 1,
			"no_copy": 1, "hidden": 1 if sales else 0},
	]
	return _chain(doctype, fields)


def party(doctype):
	fields = [
		{"fieldname": "oman_vat_section", "label": "Oman VAT", "fieldtype": "Section Break", "collapsible": 1},
		{"fieldname": "oman_vat_status", "label": "Oman VAT Status", "fieldtype": "Select",
			"options": "\nRegistered\nUnregistered\nGovernment\nForeign"},
		{"fieldname": "oman_party_country", "label": "Country (VAT)", "fieldtype": "Link", "options": "Country",
			"default": "Oman"},
		{"fieldname": "oman_cr_number", "label": "Commercial Registration No.", "fieldtype": "Data"},
		{"fieldname": "oman_party_cb", "fieldtype": "Column Break"},
		{"fieldname": "oman_peppol_id", "label": "E-invoice Electronic Address", "fieldtype": "Data"},
	]
	if doctype == "Customer":
		fields.append({"fieldname": "oman_buyer_type_default", "label": "Default Buyer Type", "fieldtype": "Select",
			"options": "\nB2B\nB2C\nB2G"})
	return _chain(doctype, fields)


def get_custom_fields():
	return {
		"Sales Invoice": invoice_header("Sales Invoice"),
		"Purchase Invoice": invoice_header("Purchase Invoice"),
		"Sales Invoice Item": invoice_item("Sales Invoice Item"),
		"Purchase Invoice Item": invoice_item("Purchase Invoice Item"),
		"Customer": party("Customer"),
		"Supplier": party("Supplier"),
		"Item": _chain("Item", [
			{"fieldname": "oman_vat_section", "label": "Oman VAT", "fieldtype": "Section Break", "collapsible": 1},
			{"fieldname": "oman_sales_vat_code", "label": "Default Sales VAT Code", "fieldtype": "Link", "options": "Oman VAT Code"},
			{"fieldname": "oman_purchase_vat_code", "label": "Default Purchase VAT Code", "fieldtype": "Link", "options": "Oman VAT Code"},
			{"fieldname": "oman_supply_category", "label": "Supply Category", "fieldtype": "Select", "options": "\nGoods\nServices"},
		]),
		"UOM": _chain("UOM", [
			{"fieldname": "oman_unece_code", "label": "UN/ECE Rec 20 Unit Code", "fieldtype": "Data"},
		]),
		"Journal Entry": _chain("Journal Entry", [
			{"fieldname": "oman_vat_source_doctype", "label": "Oman VAT Source Type", "fieldtype": "Link",
				"options": "DocType", "read_only": 1, "no_copy": 1},
			{"fieldname": "oman_vat_source_name", "label": "Oman VAT Source", "fieldtype": "Dynamic Link",
				"options": "oman_vat_source_doctype", "read_only": 1, "no_copy": 1},
		]),
	}


def make_custom_fields():
	create_custom_fields(get_custom_fields(), ignore_validate=True, update=True)


def delete_custom_fields():
	for dt, fields in get_custom_fields().items():
		for f in fields:
			name = frappe.db.get_value("Custom Field", {"dt": dt, "fieldname": f["fieldname"]})
			if name:
				frappe.delete_doc("Custom Field", name, ignore_permissions=True, force=True)
		frappe.clear_cache(doctype=dt)
