"""UBL 2.1 / Peppol PINT (Oman profile) XML generation.

Pure module: input is the canonical invoice dictionary produced by
``fawtara.mapper``; output is UTF-8 XML bytes. The CustomizationID, ProfileID,
endpoint scheme and code lists come from ``Oman Fawtara Settings`` so the
generator follows the published PINT-OM specification version configured on
the site without code changes.

Note: the official OTA PINT-OM specification and data dictionary are the
authority for element usage. Validate generated XML with the accredited
service provider's test environment before go-live.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from decimal import Decimal

NS = {
	"Invoice": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
	"CreditNote": "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2",
	"cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
	"cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
}

TYPE_CODES = {
	"Invoice": "380",
	"Credit Note": "381",
	"Debit Note": "383",
	"Self-billed Invoice": "389",
	"Self-billed Credit Note": "261",
}

ET.register_namespace("cac", NS["cac"])
ET.register_namespace("cbc", NS["cbc"])


def _q(prefix, tag):
	return f"{{{NS[prefix]}}}{tag}"


def _amt(value, places) -> str:
	d = Decimal(str(value or 0)).quantize(Decimal(1).scaleb(-places))
	return f"{d:.{places}f}"


class _B:
	def __init__(self, places_by_currency: dict):
		self.places = places_by_currency

	def cbc(self, parent, tag, text=None, **attrs):
		if text is None or text == "":
			return None
		el = ET.SubElement(parent, _q("cbc", tag), {k: str(v) for k, v in attrs.items() if v is not None})
		el.text = str(text)
		return el

	def cac(self, parent, tag):
		return ET.SubElement(parent, _q("cac", tag))

	def money(self, parent, tag, value, currency):
		return self.cbc(parent, tag, _amt(value, self.places.get(currency, 2)), currencyID=currency)


def _party(b: _B, parent, tag, p: dict):
	wrap = b.cac(parent, tag)
	party = b.cac(wrap, "Party")
	if p.get("endpoint_id"):
		b.cbc(party, "EndpointID", p["endpoint_id"], schemeID=p.get("endpoint_scheme"))
	for ident in p.get("identifiers") or []:
		pid = b.cac(party, "PartyIdentification")
		b.cbc(pid, "ID", ident["id"], schemeID=ident.get("scheme"))
	if p.get("trade_name"):
		pn = b.cac(party, "PartyName")
		b.cbc(pn, "Name", p["trade_name"])
	addr = p.get("address") or {}
	if addr:
		pa = b.cac(party, "PostalAddress")
		b.cbc(pa, "StreetName", addr.get("street"))
		b.cbc(pa, "AdditionalStreetName", addr.get("street2"))
		b.cbc(pa, "CityName", addr.get("city"))
		b.cbc(pa, "PostalZone", addr.get("postal_code"))
		b.cbc(pa, "CountrySubentity", addr.get("state"))
		c = b.cac(pa, "Country")
		b.cbc(c, "IdentificationCode", (addr.get("country_code") or "").upper())
	if p.get("vrn"):
		pts = b.cac(party, "PartyTaxScheme")
		b.cbc(pts, "CompanyID", p["vrn"])
		ts = b.cac(pts, "TaxScheme")
		b.cbc(ts, "ID", "VAT")
	ple = b.cac(party, "PartyLegalEntity")
	b.cbc(ple, "RegistrationName", p.get("name"))
	b.cbc(ple, "CompanyID", p.get("legal_id"), schemeID=p.get("legal_id_scheme"))
	if p.get("contact_email") or p.get("contact_phone"):
		ct = b.cac(party, "Contact")
		b.cbc(ct, "Telephone", p.get("contact_phone"))
		b.cbc(ct, "ElectronicMail", p.get("contact_email"))


def _tax_category(b: _B, parent, tag, category, rate, exemption_code=None, exemption_reason=None):
	tc = b.cac(parent, tag)
	b.cbc(tc, "ID", category)
	b.cbc(tc, "Percent", _amt(rate, 2))
	b.cbc(tc, "TaxExemptionReasonCode", exemption_code)
	b.cbc(tc, "TaxExemptionReason", exemption_reason)
	ts = b.cac(tc, "TaxScheme")
	b.cbc(ts, "ID", "VAT")
	return tc


def generate(inv: dict, cfg: dict) -> bytes:
	"""Build the XML for a canonical invoice ``inv`` using configuration ``cfg``."""
	is_cn = inv["document_type"] in ("Credit Note", "Self-billed Credit Note") and cfg.get("credit_note_root", True)
	root_name = "CreditNote" if is_cn else "Invoice"
	ET.register_namespace("", NS[root_name])
	root = ET.Element(f"{{{NS[root_name]}}}{root_name}")
	cur = inv["currency"]
	tax_cur = inv.get("tax_currency") or "OMR"
	b = _B({**{"OMR": 3, "BHD": 3, "KWD": 3, "JOD": 3}, **cfg.get("currency_places", {})})

	b.cbc(root, "UBLVersionID", "2.1") if cfg.get("include_ubl_version") else None
	b.cbc(root, "CustomizationID", cfg["customization_id"])
	b.cbc(root, "ProfileID", cfg["profile_id"])
	if cfg.get("profile_execution_id"):
		b.cbc(root, "ProfileExecutionID", cfg["profile_execution_id"])
	b.cbc(root, "ID", inv["invoice_number"])
	b.cbc(root, "UUID", inv["uuid"])
	b.cbc(root, "IssueDate", inv["issue_date"])
	b.cbc(root, "IssueTime", inv.get("issue_time"))
	if is_cn:
		b.cbc(root, "TaxPointDate", inv.get("tax_point_date"))
		b.cbc(root, "CreditNoteTypeCode", inv.get("type_code") or TYPE_CODES[inv["document_type"]],
			name=inv.get("transaction_flags_code"))
	else:
		b.cbc(root, "DueDate", inv.get("due_date"))
		b.cbc(root, "InvoiceTypeCode", inv.get("type_code") or TYPE_CODES[inv["document_type"]],
			name=inv.get("transaction_flags_code"))
	for note in inv.get("notes") or []:
		b.cbc(root, "Note", note)
	if not is_cn:
		b.cbc(root, "TaxPointDate", inv.get("tax_point_date"))
	b.cbc(root, "DocumentCurrencyCode", cur)
	if tax_cur and tax_cur != cur:
		b.cbc(root, "TaxCurrencyCode", tax_cur)
	b.cbc(root, "BuyerReference", inv.get("buyer_reference"))
	if inv.get("supply_period"):
		ip = b.cac(root, "InvoicePeriod")
		b.cbc(ip, "StartDate", inv["supply_period"].get("start"))
		b.cbc(ip, "EndDate", inv["supply_period"].get("end"))
	if is_cn and inv.get("adjustment_reason"):
		dr = b.cac(root, "DiscrepancyResponse")
		b.cbc(dr, "ResponseCode", inv.get("adjustment_reason_code"))
		b.cbc(dr, "Description", inv["adjustment_reason"])
	if inv.get("order_reference"):
		orf = b.cac(root, "OrderReference")
		b.cbc(orf, "ID", inv["order_reference"])
	for ref in inv.get("billing_references") or []:
		br = b.cac(root, "BillingReference")
		idr = b.cac(br, "InvoiceDocumentReference")
		b.cbc(idr, "ID", ref["id"])
		b.cbc(idr, "UUID", ref.get("uuid"))
		b.cbc(idr, "IssueDate", ref.get("issue_date"))
	for ref in inv.get("additional_references") or []:
		adr = b.cac(root, "AdditionalDocumentReference")
		b.cbc(adr, "ID", ref["id"], schemeID=ref.get("scheme"))
		b.cbc(adr, "DocumentTypeCode", ref.get("type_code"))
		b.cbc(adr, "DocumentDescription", ref.get("description"))

	_party(b, root, "AccountingSupplierParty", inv["supplier"])
	_party(b, root, "AccountingCustomerParty", inv["customer"])

	if inv.get("delivery_date") or inv.get("delivery_country"):
		dl = b.cac(root, "Delivery")
		b.cbc(dl, "ActualDeliveryDate", inv.get("delivery_date"))
		if inv.get("delivery_country"):
			loc = b.cac(dl, "DeliveryLocation")
			ad = b.cac(loc, "Address")
			c = b.cac(ad, "Country")
			b.cbc(c, "IdentificationCode", inv["delivery_country"])
	if inv.get("payment_means_code"):
		pm = b.cac(root, "PaymentMeans")
		b.cbc(pm, "PaymentMeansCode", inv["payment_means_code"])
		if inv.get("payee_iban"):
			acct = b.cac(pm, "PayeeFinancialAccount")
			b.cbc(acct, "ID", inv["payee_iban"])
	if inv.get("payment_terms"):
		pt = b.cac(root, "PaymentTerms")
		b.cbc(pt, "Note", inv["payment_terms"])

	# Document level tax total (document currency) with subtotals
	tt = b.cac(root, "TaxTotal")
	b.money(tt, "TaxAmount", inv["tax_total"], cur)
	for st in inv["tax_subtotals"]:
		sub = b.cac(tt, "TaxSubtotal")
		b.money(sub, "TaxableAmount", st["taxable"], cur)
		b.money(sub, "TaxAmount", st["tax"], cur)
		_tax_category(b, sub, "TaxCategory", st["category"], st["rate"], st.get("exemption_code"), st.get("exemption_reason"))
	if tax_cur and tax_cur != cur:
		tt2 = b.cac(root, "TaxTotal")
		b.money(tt2, "TaxAmount", inv["tax_total_tax_currency"], tax_cur)

	lmt = b.cac(root, "LegalMonetaryTotal")
	b.money(lmt, "LineExtensionAmount", inv["line_extension_total"], cur)
	b.money(lmt, "TaxExclusiveAmount", inv["tax_exclusive_total"], cur)
	b.money(lmt, "TaxInclusiveAmount", inv["tax_inclusive_total"], cur)
	if inv.get("prepaid_amount"):
		b.money(lmt, "PrepaidAmount", inv["prepaid_amount"], cur)
	if inv.get("rounding_amount"):
		b.money(lmt, "PayableRoundingAmount", inv["rounding_amount"], cur)
	b.money(lmt, "PayableAmount", inv["payable_amount"], cur)

	line_tag = "CreditNoteLine" if is_cn else "InvoiceLine"
	qty_tag = "CreditedQuantity" if is_cn else "InvoicedQuantity"
	for ln in inv["lines"]:
		el = b.cac(root, line_tag)
		b.cbc(el, "ID", ln["id"])
		b.cbc(el, qty_tag, _amt(ln["quantity"], 6).rstrip("0").rstrip(".") or "0", unitCode=ln.get("unit_code") or "C62")
		b.money(el, "LineExtensionAmount", ln["line_extension_amount"], cur)
		if cfg.get("include_line_tax_amount"):
			ltt = b.cac(el, "TaxTotal")
			b.money(ltt, "TaxAmount", ln["tax_amount"], cur)
		it = b.cac(el, "Item")
		b.cbc(it, "Description", ln.get("description"))
		b.cbc(it, "Name", ln["name"])
		if ln.get("item_code"):
			sid = b.cac(it, "SellersItemIdentification")
			b.cbc(sid, "ID", ln["item_code"])
		if ln.get("classification_code"):
			cc = b.cac(it, "CommodityClassification")
			b.cbc(cc, "ItemClassificationCode", ln["classification_code"], listID=ln.get("classification_list"))
		_tax_category(b, it, "ClassifiedTaxCategory", ln["tax_category"], ln["tax_rate"])
		pr = b.cac(el, "Price")
		b.money(pr, "PriceAmount", ln["unit_price"], cur)

	ET.indent(root, space="  ")
	return ET.tostring(root, encoding="utf-8", xml_declaration=True)
