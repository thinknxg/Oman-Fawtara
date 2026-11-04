"""Local (pre-submission) validation of the canonical invoice and XML.

Catches structural and arithmetic problems before anything leaves ERPNext.
The accredited service provider and OTA remain the authoritative validators.
"""

from __future__ import annotations

import re
import uuid as uuidlib
from decimal import Decimal

from oman_fawtara.vat.calc import D, round_money, vat_on

CATEGORIES = {"S", "Z", "E", "O", "AE", "G", "K", "L", "M"}


def _err(out, code, message, path=None):
	out.append({"code": code, "message": message, "path": path, "severity": "Error"})


def _warn(out, code, message, path=None):
	out.append({"code": code, "message": message, "path": path, "severity": "Warning"})


def validate_canonical(inv: dict, cfg: dict) -> list[dict]:
	out: list[dict] = []
	places = 3 if inv.get("currency") in ("OMR", "BHD", "KWD") else 2
	tol = Decimal(cfg.get("tolerance", "0.01"))

	for f in ("invoice_number", "uuid", "issue_date", "currency", "document_type"):
		if not inv.get(f):
			_err(out, "MISSING_FIELD", f"Missing {f}", f)
	try:
		uuidlib.UUID(str(inv.get("uuid")))
	except (ValueError, TypeError):
		_err(out, "UUID_FORMAT", "UUID is not a valid RFC 4122 identifier", "uuid")
	if not cfg.get("customization_id"):
		_err(out, "CONFIG_CUSTOMIZATION_ID", "Fawtara CustomizationID is not configured")
	if not cfg.get("profile_id"):
		_err(out, "CONFIG_PROFILE_ID", "Fawtara ProfileID is not configured")

	sup, cus = inv.get("supplier") or {}, inv.get("customer") or {}
	if not sup.get("vrn"):
		_err(out, "SUPPLIER_VRN", "Supplier VAT registration number is required", "supplier.vrn")
	elif cfg.get("vrn_pattern") and not re.fullmatch(cfg["vrn_pattern"], sup["vrn"]):
		_err(out, "SUPPLIER_VRN_FORMAT", f"Supplier VAT number {sup['vrn']} has an invalid format", "supplier.vrn")
	if not sup.get("name"):
		_err(out, "SUPPLIER_NAME", "Supplier legal name is required", "supplier.name")
	if cfg.get("require_endpoint") and not sup.get("endpoint_id"):
		_err(out, "SUPPLIER_ENDPOINT", "Supplier electronic address (EndpointID) is required", "supplier.endpoint_id")
	if cfg.get("require_endpoint") and not sup.get("endpoint_scheme"):
		_err(out, "ENDPOINT_SCHEME", "Endpoint scheme is not configured in Oman Fawtara Settings", "supplier.endpoint_scheme")
	if not (sup.get("address") or {}).get("country_code"):
		_err(out, "SUPPLIER_COUNTRY", "Supplier country code is required", "supplier.address.country_code")

	flags = inv.get("flags") or {}
	if flags.get("b2b") or flags.get("b2g"):
		if not cus.get("name"):
			_err(out, "BUYER_NAME", "Buyer legal name is required for B2B/B2G", "customer.name")
		if flags.get("buyer_registered") and not cus.get("vrn"):
			_err(out, "BUYER_VRN", "VAT-registered buyer must have a VAT number on the invoice", "customer.vrn")
		if cfg.get("require_endpoint") and not cus.get("endpoint_id"):
			_warn(out, "BUYER_ENDPOINT", "Buyer electronic address is missing; delivery via C3 may fail", "customer.endpoint_id")

	if inv["document_type"] in ("Credit Note", "Debit Note", "Self-billed Credit Note") and not inv.get("billing_references"):
		_err(out, "BILLING_REFERENCE", "Credit/debit notes must reference the original invoice", "billing_references")
	if flags.get("import") and not any((r.get("type_code") or "").upper() in ("BAYAN", "CUSTOMS") or r.get("scheme") == "BAYAN"
			for r in inv.get("additional_references") or []):
		_warn(out, "BAYAN_REFERENCE", "Import self-billing without a Bayan customs reference")

	# Line arithmetic
	if not inv.get("lines"):
		_err(out, "NO_LINES", "Invoice has no lines")
	line_sum = D(0)
	for ln in inv.get("lines") or []:
		if ln.get("tax_category") not in CATEGORIES:
			_err(out, "TAX_CATEGORY", f"Line {ln.get('id')}: invalid tax category {ln.get('tax_category')}", f"lines[{ln.get('id')}]")
		line_sum += D(ln["line_extension_amount"])
	if abs(round_money(line_sum, places) - D(inv["line_extension_total"])) > tol:
		_err(out, "LINE_TOTAL", f"Sum of lines {line_sum} ≠ LineExtensionAmount {inv['line_extension_total']}")

	# Tax subtotals
	st_taxable = D(0)
	st_tax = D(0)
	for st in inv.get("tax_subtotals") or []:
		st_taxable += D(st["taxable"])
		st_tax += D(st["tax"])
		if st["category"] in ("Z", "E", "O", "AE", "G") and D(st["tax"]) != 0:
			_err(out, "ZERO_CATEGORY_TAX", f"Category {st['category']} must carry zero tax")
		if st["category"] == "S" and abs(vat_on(st["taxable"], st["rate"], places) - D(st["tax"])) > tol:
			_err(out, "SUBTOTAL_TAX", f"Subtotal {st['category']} {st['rate']}%: tax {st['tax']} ≠ {st['rate']}% × {st['taxable']}")
		if st["category"] in ("E", "O", "AE", "G") and not (st.get("exemption_reason") or st.get("exemption_code")):
			_err(out, "EXEMPTION_REASON", f"Category {st['category']} requires an exemption reason or code")
	if abs(st_taxable - D(inv["tax_exclusive_total"])) > tol:
		_err(out, "TAXABLE_TOTAL", f"Σ taxable {st_taxable} ≠ TaxExclusiveAmount {inv['tax_exclusive_total']}")
	if abs(st_tax - D(inv["tax_total"])) > tol:
		_err(out, "TAX_TOTAL", f"Σ subtotal tax {st_tax} ≠ TaxAmount {inv['tax_total']}")
	if abs(D(inv["tax_exclusive_total"]) + D(inv["tax_total"]) - D(inv["tax_inclusive_total"])) > tol:
		_err(out, "INCLUSIVE_TOTAL", "TaxInclusiveAmount ≠ TaxExclusiveAmount + TaxAmount")
	expected_payable = D(inv["tax_inclusive_total"]) - D(inv.get("prepaid_amount")) + D(inv.get("rounding_amount"))
	if abs(expected_payable - D(inv["payable_amount"])) > tol:
		_err(out, "PAYABLE", f"PayableAmount {inv['payable_amount']} ≠ {expected_payable}")
	if inv.get("erpnext_grand_total") is not None and abs(D(inv["tax_inclusive_total"]) - D(inv["erpnext_grand_total"])) > tol:
		_err(out, "ERPNEXT_TOTAL", f"TaxInclusiveAmount {inv['tax_inclusive_total']} ≠ ERPNext grand total {inv['erpnext_grand_total']}")
	if inv.get("currency") != (inv.get("tax_currency") or "OMR") and not inv.get("tax_total_tax_currency") and D(inv["tax_total"]):
		_err(out, "TAX_CURRENCY_TOTAL", "Tax total in OMR is required for foreign-currency invoices")
	return out


def validate_xml(xml_bytes: bytes, xsd_path: str | None = None) -> list[dict]:
	out: list[dict] = []
	try:
		import xml.etree.ElementTree as ET

		ET.fromstring(xml_bytes)
	except Exception as e:  # noqa: BLE001
		_err(out, "XML_WELLFORMED", f"XML is not well-formed: {e}")
		return out
	if xsd_path:
		try:
			from lxml import etree

			schema = etree.XMLSchema(etree.parse(xsd_path))
			doc = etree.fromstring(xml_bytes)
			if not schema.validate(doc):
				for e in schema.error_log:
					_err(out, "XSD", f"Line {e.line}: {e.message}")
		except ImportError:
			_warn(out, "XSD_UNAVAILABLE", "lxml not available; XSD validation skipped")
		except Exception as e:  # noqa: BLE001
			_warn(out, "XSD_ERROR", f"XSD validation could not run: {e}")
	return out
