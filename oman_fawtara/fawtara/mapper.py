"""ERPNext → canonical Fawtara invoice mapping."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, flt, get_time, getdate

from oman_fawtara.fawtara.applicability import fawtara_settings
from oman_fawtara.vat.calc import D, round_money


def _country_code(country):
	if not country:
		return None
	return (frappe.get_cached_value("Country", country, "code") or "").upper()


def _address(name):
	if not name:
		return {}
	a = frappe.get_cached_doc("Address", name)
	return {
		"street": a.address_line1,
		"street2": a.address_line2,
		"city": a.city,
		"postal_code": a.pincode,
		"state": a.state,
		"country_code": _country_code(a.country),
	}


def _company_party(company, registration, s):
	reg = frappe.get_cached_doc("Oman VAT Registration", registration)
	addr = _address(reg.address) if reg.address else {}
	if not addr.get("country_code"):
		addr["country_code"] = "OM"
	idents = []
	if reg.commercial_registration_no:
		idents.append({"id": reg.commercial_registration_no, "scheme": s.cr_scheme_id or None})
	return {
		"name": reg.legal_name or company,
		"trade_name": reg.trade_name,
		"vrn": reg.vatin,
		"legal_id": reg.commercial_registration_no,
		"legal_id_scheme": s.cr_scheme_id or None,
		"identifiers": idents,
		"endpoint_id": reg.peppol_participant_id or reg.vatin,
		"endpoint_scheme": s.endpoint_scheme or None,
		"address": addr,
		"contact_email": reg.contact_email,
		"contact_phone": reg.contact_phone,
	}


def _external_party(party_type, party, vrn, address_name, s):
	p = frappe.get_cached_doc(party_type, party)
	addr = _address(address_name)
	country = p.get("oman_party_country") or p.get("country")
	if not addr.get("country_code"):
		addr["country_code"] = _country_code(country) or "OM"
	name_field = "customer_name" if party_type == "Customer" else "supplier_name"
	return {
		"name": p.get(name_field) or party,
		"vrn": vrn or p.get("tax_id"),
		"legal_id": p.get("oman_cr_number"),
		"legal_id_scheme": s.cr_scheme_id or None,
		"identifiers": [{"id": p.oman_cr_number, "scheme": s.cr_scheme_id or None}] if p.get("oman_cr_number") else [],
		"endpoint_id": p.get("oman_peppol_id"),
		"endpoint_scheme": s.endpoint_scheme or None if p.get("oman_peppol_id") else None,
		"address": addr,
		"contact_email": p.get("email_id"),
		"vat_status": p.get("oman_vat_status"),
	}


def document_type(doc) -> str:
	self_billed = doc.doctype == "Purchase Invoice" and cint(doc.get("oman_self_billing"))
	if cint(doc.get("is_return")):
		return "Self-billed Credit Note" if self_billed else "Credit Note"
	if cint(doc.get("is_debit_note")):
		return "Debit Note"
	return "Self-billed Invoice" if self_billed else "Invoice"


def build(doc) -> dict:
	s = fawtara_settings()
	reg = doc.oman_vat_registration
	self_billed = doc.doctype == "Purchase Invoice"
	sign = -1 if cint(doc.get("is_return")) else 1  # credit notes are expressed with positive amounts
	cur = doc.currency
	places = 3 if cur in ("OMR", "BHD", "KWD") else 2
	conv = D(doc.conversion_rate or 1)

	if self_billed:
		supplier = _external_party("Supplier", doc.supplier, doc.get("tax_id"), doc.get("supplier_address"), s)
		customer = _company_party(doc.company, reg, s)
	else:
		supplier = _company_party(doc.company, reg, s)
		customer = _external_party("Customer", doc.customer, doc.get("tax_id"), doc.get("customer_address"), s)

	lines, groups = [], {}
	for i in doc.items:
		treatment = frappe.get_cached_doc("Oman VAT Treatment", i.oman_vat_treatment) if i.get("oman_vat_treatment") else None
		category = (treatment.tax_category_code if treatment else None) or "S"
		rate = flt(i.get("oman_vat_rate"))
		vat_omr = D(i.get("oman_input_vat") if self_billed else i.get("oman_output_vat"))
		if treatment and cint(treatment.is_reverse_charge):
			vat_omr = D(0)
		line_tax = round_money(abs(vat_omr) / conv, places)
		ext = round_money(abs(D(i.net_amount)), places)
		lines.append(
			{
				"id": str(i.idx),
				"name": i.item_name or i.item_code,
				"description": (i.description or "")[:500] if s.include_line_description else None,
				"item_code": i.item_code,
				"quantity": abs(flt(i.qty)),
				"unit_code": frappe.get_cached_value("UOM", i.uom, "oman_unece_code") if i.uom else None,
				"unit_price": abs(flt(i.net_rate)),
				"line_extension_amount": float(ext),
				"tax_category": category,
				"tax_rate": rate if category == "S" else (rate if category == "AE" else 0),
				"tax_amount": float(line_tax),
				"classification_code": frappe.get_cached_value("Item", i.item_code, "customs_tariff_number") if i.item_code else None,
			}
		)
		key = (category, rate if category in ("S", "AE") else 0)
		g = groups.setdefault(key, {"category": category, "rate": key[1], "taxable": D(0), "tax": D(0),
			"exemption_code": treatment.exemption_reason_code if treatment else None,
			"exemption_reason": treatment.exemption_reason if treatment else None})
		g["taxable"] += ext
		g["tax"] += line_tax

	# Use the ERPNext document totals as the authority for the tax total; the
	# per-category split comes from the per-line figures.
	subtotals = [
		{**g, "taxable": float(round_money(g["taxable"], places)), "tax": float(round_money(g["tax"], places))}
		for g in groups.values()
	]
	line_total = round_money(sum(D(l["line_extension_amount"]) for l in lines), places)
	tax_total = round_money(sum(D(st["tax"]) for st in subtotals), places)
	inclusive = line_total + tax_total
	rounding = (
		D(0)
		if cint(doc.get("disable_rounded_total"))
		else round_money(D(doc.get("rounding_adjustment")) * sign, places)
	)
	prepaid = round_money(abs(D(doc.get("total_advance"))), places)
	payable = inclusive - prepaid + rounding

	billing_refs = []
	if doc.get("return_against"):
		orig = frappe.db.get_value(doc.doctype, doc.return_against, ["name", "posting_date", "oman_fawtara_uuid"], as_dict=True)
		billing_refs.append({"id": orig.name, "issue_date": str(orig.posting_date), "uuid": orig.oman_fawtara_uuid})
	add_refs = []
	if doc.get("oman_bayan_reference"):
		add_refs.append({"id": doc.oman_bayan_reference, "type_code": "BAYAN", "scheme": "BAYAN",
			"description": _("Customs declaration")})
	if doc.get("oman_import_declaration"):
		bay = frappe.db.get_value("Oman Import Declaration", doc.oman_import_declaration, "declaration_number")
		if bay and bay != doc.get("oman_bayan_reference"):
			add_refs.append({"id": bay, "type_code": "BAYAN", "scheme": "BAYAN"})

	buyer_type = doc.get("oman_buyer_type") or ("B2B" if customer.get("vrn") else "B2C")
	any_rc = any(l["tax_category"] == "AE" for l in lines)
	any_export = any(
		frappe.get_cached_value("Oman VAT Code", i.oman_vat_code, "is_export") for i in doc.items if i.get("oman_vat_code")
	)
	flags = {
		"b2b": buyer_type == "B2B",
		"b2c": buyer_type == "B2C",
		"b2g": buyer_type == "B2G",
		"buyer_registered": (customer.get("vat_status") == "Registered") if not self_billed else True,
		"self_billing": self_billed,
		"reverse_charge": any_rc,
		"export": bool(any_export),
		"import": bool(add_refs) and self_billed,
	}
	tax_point = doc.get("oman_tax_point_date")
	return {
		"uuid": doc.oman_fawtara_uuid,
		"invoice_number": doc.name,
		"issue_date": str(getdate(doc.posting_date)),
		"issue_time": str(get_time(doc.posting_time))[:8] if doc.get("posting_time") else None,
		"due_date": str(doc.due_date) if doc.get("due_date") and not cint(doc.get("is_return")) else None,
		"tax_point_date": str(tax_point) if tax_point and str(tax_point) != str(doc.posting_date) else None,
		"document_type": document_type(doc),
		"type_code": None,
		"transaction_flags_code": _flags_code(flags, s),
		"flags": flags,
		"currency": cur,
		"tax_currency": "OMR",
		"exchange_rate": float(conv),
		"notes": [n for n in (doc.get("oman_einvoice_note"),) if n],
		"buyer_reference": doc.get("po_no") or doc.get("oman_buyer_reference"),
		"order_reference": doc.get("po_no"),
		"billing_references": billing_refs,
		"additional_references": add_refs,
		"adjustment_reason": doc.get("oman_adjustment_reason"),
		"adjustment_reason_code": frappe.get_cached_value("Oman Fawtara Settings", None, "default_adjustment_reason_code"),
		"supplier": supplier,
		"customer": customer,
		"delivery_date": str(doc.oman_supply_date) if doc.get("oman_supply_date") else None,
		"delivery_country": _country_code(doc.get("oman_export_destination")) if doc.get("oman_export_destination") else None,
		"payment_means_code": s.default_payment_means_code,
		"payment_terms": doc.get("payment_terms_template"),
		"lines": lines,
		"tax_subtotals": subtotals,
		"tax_total": float(tax_total),
		"tax_total_tax_currency": float(round_money(abs(D(doc.get("oman_total_output_vat") if not self_billed else doc.get("oman_total_input_vat"))), 3)),
		"line_extension_total": float(line_total),
		"tax_exclusive_total": float(line_total),
		"tax_inclusive_total": float(inclusive),
		"prepaid_amount": float(prepaid),
		"rounding_amount": float(rounding),
		"payable_amount": float(payable),
		"erpnext_grand_total": abs(flt(doc.grand_total)),
	}


def _flags_code(flags, s) -> str | None:
	"""Optional transaction-flag string carried in the type code ``name`` attribute.

	Some PINT country profiles encode B2B/B2C, self-billing, export and
	reverse-charge as a positional flag string. Enable and order the flags in
	Oman Fawtara Settings according to the OTA specification in force.
	"""
	if not cint(s.use_transaction_flags):
		return None
	order = [f.strip() for f in (s.transaction_flag_order or "").split(",") if f.strip()]
	return "".join("1" if flags.get(f) else "0" for f in order) or None


def config() -> dict:
	s = fawtara_settings()
	return {
		"customization_id": s.customization_id,
		"profile_id": s.profile_id,
		"profile_execution_id": s.profile_execution_id,
		"include_line_tax_amount": cint(s.include_line_tax_amount),
		"include_ubl_version": cint(s.include_ubl_version),
		"credit_note_root": cint(s.use_credit_note_root),
		"require_endpoint": cint(s.require_endpoint),
		"vrn_pattern": frappe.get_cached_value("Oman VAT Settings", None, "vrn_pattern"),
		"tolerance": str(s.local_tolerance or "0.01"),
	}
