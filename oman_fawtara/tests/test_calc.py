"""Pure unit tests (no database) for tax arithmetic, XML generation and local validation."""

import unittest
import uuid
import xml.etree.ElementTree as ET
from decimal import Decimal

from oman_fawtara.fawtara import local_validation, xml_generator
from oman_fawtara.vat import calc

CFG = {"customization_id": "urn:peppol:pint:billing-1@om-1", "profile_id": "urn:peppol:bis:billing",
	"vrn_pattern": r"^OM\d{10}$", "tolerance": "0.01", "require_endpoint": 1}


def canonical(doc_type="Invoice", currency="OMR"):
	return {
		"uuid": str(uuid.uuid4()), "invoice_number": "SINV-0001", "issue_date": "2026-11-04", "document_type": doc_type,
		"currency": currency, "tax_currency": "OMR", "flags": {"b2b": True, "buyer_registered": True},
		"billing_references": [{"id": "SINV-0000", "issue_date": "2026-10-01"}] if doc_type == "Credit Note" else [],
		"supplier": {"name": "Seller LLC", "vrn": "OM1100000001", "endpoint_id": "OM1100000001", "endpoint_scheme": "9999",
			"address": {"country_code": "OM", "city": "Muscat"}},
		"customer": {"name": "Buyer LLC", "vrn": "OM1100000002", "endpoint_id": "OM1100000002", "endpoint_scheme": "9999",
			"address": {"country_code": "OM"}},
		"lines": [
			{"id": "1", "name": "Product A", "quantity": 1, "unit_price": 100, "line_extension_amount": 100,
				"tax_category": "S", "tax_rate": 5, "tax_amount": 5},
			{"id": "2", "name": "Product B", "quantity": 2, "unit_price": 25, "line_extension_amount": 50,
				"tax_category": "Z", "tax_rate": 0, "tax_amount": 0},
			{"id": "3", "name": "Product C", "quantity": 1, "unit_price": 30, "line_extension_amount": 30,
				"tax_category": "E", "tax_rate": 0, "tax_amount": 0},
		],
		"tax_subtotals": [
			{"category": "S", "rate": 5, "taxable": 100, "tax": 5},
			{"category": "Z", "rate": 0, "taxable": 50, "tax": 0},
			{"category": "E", "rate": 0, "taxable": 30, "tax": 0, "exemption_code": "VATEX-OM-EXEMPT", "exemption_reason": "Exempt"},
		],
		"tax_total": 5, "tax_total_tax_currency": 5, "line_extension_total": 180, "tax_exclusive_total": 180,
		"tax_inclusive_total": 185, "prepaid_amount": 0, "rounding_amount": 0, "payable_amount": 185,
		"erpnext_grand_total": 185,
	}


class TestArithmetic(unittest.TestCase):
	def test_standard_rate(self):
		r = calc.compute_line(direction="Sales", taxable=100, rate=5, charges_vat=True, charged_vat=5)
		self.assertEqual(r.output_vat, Decimal("5.000"))

	def test_zero_and_exempt_are_distinct_but_zero(self):
		for _t in ("Zero Rated", "Exempt"):
			r = calc.compute_line(direction="Sales", taxable=100, rate=0, charges_vat=False, charged_vat=0)
			self.assertEqual(r.output_vat, Decimal("0"))

	def test_partial_recovery_40(self):
		r = calc.compute_line(direction="Purchase", taxable=100, rate=5, charges_vat=True, recovery_pct=40, charged_vat=5)
		self.assertEqual((r.input_vat, r.recoverable, r.nonrecoverable), (Decimal("5.000"), Decimal("2.000"), Decimal("3.000")))

	def test_split_always_sums(self):
		for vat in ("0.001", "1.235", "7.777", "1000.005"):
			for pct in (0, 1, 33.33, 40, 66.67, 99.99, 100):
				rec, non = calc.split_recovery(vat, pct)
				self.assertEqual(rec + non, calc.round_money(vat))

	def test_reverse_charge(self):
		r = calc.compute_line(direction="Purchase", taxable=200, rate=5, charges_vat=False, reverse_charge=True, recovery_pct=100)
		self.assertEqual((r.rcm_output, r.input_vat, r.rcm_input), (Decimal("10.000"),) * 3)

	def test_inclusive(self):
		self.assertEqual(calc.taxable_from_inclusive("105", 5), Decimal("100.000"))

	def test_half_up_baisa(self):
		self.assertEqual(calc.vat_on("0.01", 5), Decimal("0.001"))  # 0.0005 -> 0.001

	def test_apportionment(self):
		self.assertEqual(calc.apportionment_ratio(600, 1000), Decimal("60.00"))
		self.assertEqual(calc.apportionment_ratio(0, 0), Decimal("100"))

	def test_backoff(self):
		self.assertEqual([calc.backoff_seconds(a, 60) for a in (1, 2, 3, 4)], [60, 120, 240, 480])
		self.assertEqual(calc.backoff_seconds(30, 60, cap=3600), 3600)

	def test_invoice_number_normalisation(self):
		self.assertEqual(calc.normalize_invoice_number("INV-0012"), calc.normalize_invoice_number("inv 12"))
		self.assertNotEqual(calc.normalize_invoice_number("INV-12"), calc.normalize_invoice_number("INV-120"))

	def test_vrn(self):
		self.assertTrue(calc.vrn_is_valid("OM1100012345"))
		self.assertFalse(calc.vrn_is_valid("OM11000123"))

	def test_chain_hash(self):
		a = calc.chain_hash(None, {"x": 1})
		self.assertNotEqual(a, calc.chain_hash(None, {"x": 2}))
		self.assertEqual(a, calc.chain_hash(None, {"x": 1}))


class TestXml(unittest.TestCase):
	def test_mixed_invoice_validates_and_parses(self):
		inv = canonical()
		self.assertEqual([i for i in local_validation.validate_canonical(inv, CFG) if i["severity"] == "Error"], [])
		xml = xml_generator.generate(inv, CFG)
		root = ET.fromstring(xml)
		ns = {"cbc": xml_generator.NS["cbc"], "cac": xml_generator.NS["cac"]}
		self.assertTrue(root.tag.endswith("Invoice"))
		self.assertEqual(root.find("cbc:InvoiceTypeCode", ns).text, "380")
		self.assertEqual(len(root.findall("cac:InvoiceLine", ns)), 3)
		self.assertEqual(root.find("cac:TaxTotal/cbc:TaxAmount", ns).text, "5.000")
		self.assertEqual(len(root.findall("cac:TaxTotal/cac:TaxSubtotal", ns)), 3)
		self.assertEqual(root.find("cac:LegalMonetaryTotal/cbc:PayableAmount", ns).text, "185.000")
		self.assertEqual(local_validation.validate_xml(xml), [])

	def test_credit_note_root_and_reference(self):
		inv = canonical("Credit Note")
		xml = xml_generator.generate(inv, {**CFG, "credit_note_root": True})
		root = ET.fromstring(xml)
		self.assertTrue(root.tag.endswith("CreditNote"))
		inv["billing_references"] = []
		codes = {i["code"] for i in local_validation.validate_canonical(inv, CFG)}
		self.assertIn("BILLING_REFERENCE", codes)

	def test_arithmetic_errors_detected(self):
		inv = canonical()
		inv["tax_subtotals"][0]["tax"] = 6
		inv["tax_total"] = 6
		codes = {i["code"] for i in local_validation.validate_canonical(inv, CFG)}
		self.assertIn("SUBTOTAL_TAX", codes)
		self.assertIn("INCLUSIVE_TOTAL", codes)

	def test_zero_category_cannot_carry_tax(self):
		inv = canonical()
		inv["tax_subtotals"][1]["tax"] = 1
		codes = {i["code"] for i in local_validation.validate_canonical(inv, CFG)}
		self.assertIn("ZERO_CATEGORY_TAX", codes)

	def test_foreign_currency_requires_omr_tax_total(self):
		inv = canonical(currency="USD")
		inv["tax_total_tax_currency"] = None
		codes = {i["code"] for i in local_validation.validate_canonical(inv, CFG)}
		self.assertIn("TAX_CURRENCY_TOTAL", codes)
		inv["tax_total_tax_currency"] = 1.925
		xml = xml_generator.generate(inv, CFG)
		self.assertIn(b'currencyID="OMR">1.925<', xml)

	def test_missing_seller_vrn(self):
		inv = canonical()
		inv["supplier"]["vrn"] = None
		self.assertIn("SUPPLIER_VRN", {i["code"] for i in local_validation.validate_canonical(inv, CFG)})


if __name__ == "__main__":
	unittest.main()
