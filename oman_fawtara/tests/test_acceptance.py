"""Acceptance tests on a real ERPNext v16 site.

Run: bench --site <site> run-tests --app oman_fawtara

Each test maps to a row of the acceptance matrix in README.md. Fixtures are
created idempotently on a dedicated company (OMR, Oman) so the suite can run
repeatedly on a test site. The numeric expectations are engine baselines; the
release checklist additionally requires an Oman VAT specialist's approved
cases.
"""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, flt, getdate, today

from oman_fawtara import audit
from oman_fawtara.fawtara import queue
from oman_fawtara.setup.company_setup import setup_company
from oman_fawtara.vat import reconciliation

COMPANY = "Oman Fawtara Test LLC"
ABBR = "OFT"
VATIN = "OM1100099999"


def _ensure(doctype, name, values):
	if not frappe.db.exists(doctype, name):
		frappe.get_doc({"doctype": doctype, **values}).insert(ignore_permissions=True)
	return name


def _leaf(doctype):
	return frappe.db.get_value(doctype, {"is_group": 0}, "name", order_by="lft asc")


def fixtures():
	cg, tr, sg, ig = _leaf("Customer Group"), _leaf("Territory"), _leaf("Supplier Group"), _leaf("Item Group")
	if not frappe.db.exists("Company", COMPANY):
		frappe.get_doc({"doctype": "Company", "company_name": COMPANY, "abbr": ABBR, "default_currency": "OMR",
			"country": "Oman", "chart_of_accounts": "Standard", "create_chart_of_accounts_based_on": "Standard Template"}).insert()
	setup_company(COMPANY, VATIN, "Oman Fawtara Test LLC", "2026-01-01", "Quarterly", "2026-01-01")
	reg = frappe.db.get_value("Oman VAT Registration", {"company": COMPANY})
	frappe.db.set_value("Oman VAT Registration", reg, {"fawtara_enabled": 1, "fawtara_voluntary_start_date": "2026-01-01",
		"fawtara_provider": "Sandbox", "peppol_participant_id": VATIN, "commercial_registration_no": "1234567"})
	frappe.clear_document_cache("Oman VAT Registration", reg)
	if not frappe.db.exists("Currency Exchange", {"from_currency": "USD", "to_currency": "OMR"}):
		frappe.db.set_value("Currency", "USD", "enabled", 1)
		frappe.get_doc({"doctype": "Currency Exchange", "date": "2026-01-01", "from_currency": "USD", "to_currency": "OMR",
			"exchange_rate": 0.385, "for_buying": 1, "for_selling": 1}).insert(ignore_permissions=True)
	_ensure("Customer", "OFT Local Buyer", {"customer_name": "OFT Local Buyer", "customer_group": cg,
		"territory": tr, "tax_id": "OM1100000002", "oman_vat_status": "Registered",
		"oman_party_country": "Oman", "oman_buyer_type_default": "B2B", "oman_peppol_id": "OM1100000002"})
	_ensure("Customer", "OFT Export Buyer", {"customer_name": "OFT Export Buyer", "customer_group": cg,
		"territory": tr, "oman_vat_status": "Foreign", "oman_party_country": "United Kingdom",
		"oman_buyer_type_default": "B2B", "oman_peppol_id": "GB-BUYER"})
	_ensure("Supplier", "OFT Local Supplier", {"supplier_name": "OFT Local Supplier", "supplier_group": sg,
		"tax_id": "OM1100000003", "oman_vat_status": "Registered", "oman_party_country": "Oman"})
	_ensure("Supplier", "OFT UK Consultant", {"supplier_name": "OFT UK Consultant", "supplier_group": sg,
		"oman_vat_status": "Foreign", "oman_party_country": "United Kingdom", "country": "United Kingdom"})
	usd_payable = f"Creditors USD - {ABBR}"
	if not frappe.db.exists("Account", usd_payable):
		frappe.get_doc({"doctype": "Account", "account_name": "Creditors USD", "company": COMPANY, "account_currency": "USD",
			"account_type": "Payable", "parent_account": frappe.db.get_value("Account", f"Creditors - {ABBR}", "parent_account")}
		).insert(ignore_permissions=True)
	_ensure("Supplier", "OFT US Vendor", {"supplier_name": "OFT US Vendor", "supplier_group": sg,
		"tax_id": "OM1100000004", "oman_vat_status": "Registered", "oman_party_country": "Oman", "default_currency": "USD",
		"accounts": [{"company": COMPANY, "account": usd_payable}]})
	for code, cat in (("OFT-SVC", "Services"), ("OFT-GOODS", "Goods"), ("OFT-GOODS-B", "Goods"), ("OFT-GOODS-C", "Goods")):
		_ensure("Item", code, {"item_code": code, "item_name": code, "item_group": ig, "stock_uom": "Nos",
			"is_stock_item": 0, "oman_supply_category": cat})
	_ensure("Oman VAT Recovery Profile", "OFT Business Use 40%", {"profile_name": "OFT Business Use 40%",
		"method": "Business Use", "recovery_percentage": 40, "status": "Approved", "legal_basis": "Test"})
	fs = frappe.get_single("Oman Fawtara Settings")
	fs.update({"enabled": 1, "default_provider": "Sandbox", "endpoint_scheme": "9999", "submit_immediately": 0})
	fs.save(ignore_permissions=True)
	_sandbox("Accept")
	frappe.db.commit()


def _sandbox(behaviour, failures=1):
	frappe.db.set_value("Oman Fawtara Provider", "Sandbox", {"sandbox_behaviour": behaviour, "sandbox_failures": failures})
	frappe.clear_document_cache("Oman Fawtara Provider", "Sandbox")


def acc(name):
	return f"{name} - {ABBR}"


def sales(items, customer="OFT Local Buyer", posting_date=None, submit=True, **kw):
	si = frappe.new_doc("Sales Invoice")
	si.update({"company": COMPANY, "customer": customer, "currency": "OMR", "posting_date": posting_date or today(),
		"set_posting_time": 1, "due_date": add_days(posting_date or today(), 30), **kw})
	for it in items:
		si.append("items", {"qty": 1, "uom": "Nos", **it})
	si.append("taxes", {"charge_type": "On Net Total", "account_head": acc("Oman Output VAT"), "rate": 5, "description": "VAT"})
	si.insert()
	if submit:
		si.submit()
	return si


def purchase(items, supplier="OFT Local Supplier", bill_no=None, taxes=True, submit=True, **kw):
	pi = frappe.new_doc("Purchase Invoice")
	pi.update({"company": COMPANY, "supplier": supplier, "posting_date": kw.pop("posting_date", today()), "set_posting_time": 1,
		"bill_no": bill_no or frappe.generate_hash(length=8), "bill_date": today(), **kw})
	for it in items:
		pi.append("items", {"qty": 1, "uom": "Nos", "expense_account": acc("Cost of Goods Sold"), **it})
	if taxes:
		pi.append("taxes", {"charge_type": "On Net Total", "account_head": acc("Oman Input VAT"), "rate": 5,
			"description": "VAT", "category": "Total", "add_deduct_tax": "Add"})
	pi.insert()
	if submit:
		pi.submit()
	return pi


class TestOmanFawtaraAcceptance(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		fixtures()

	def setUp(self):
		frappe.set_user("Administrator")
		_sandbox("Accept")

	# ------------------------------------------------------------ VAT engine
	def test_01_domestic_standard_sale(self):
		si = sales([{"item_code": "OFT-GOODS", "rate": 100}])
		self.assertEqual(si.oman_vat_validation_status, "Passed")
		self.assertEqual(flt(si.items[0].oman_output_vat, 3), 5.0)
		self.assertEqual(si.items[0].oman_vat_treatment, "Standard Rated")
		self.assertEqual(flt(si.total_taxes_and_charges, 3), 5.0)
		t = frappe.get_doc("Oman VAT Transaction", {"source_name": si.name})
		self.assertEqual(flt(t.total_output_vat, 3), 5.0)

	def test_02_zero_rated_sale(self):
		si = sales([{"item_code": "OFT-GOODS", "rate": 100, "oman_vat_code": "OM-Z0"}], submit=False)
		frappe.get_doc({"doctype": "Oman VAT Evidence", "evidence_type": "Zero-rating Certificate / Contract",
			"reference_doctype": "Sales Invoice", "reference_name": si.name, "status": "Received"}).insert()
		si.reload()
		si.submit()
		self.assertEqual(si.items[0].oman_vat_treatment, "Zero Rated")
		self.assertEqual(flt(si.items[0].oman_output_vat), 0)
		self.assertEqual(flt(si.total_taxes_and_charges), 0)
		nature = frappe.db.get_value("Oman VAT Treatment", si.items[0].oman_vat_treatment, "nature")
		self.assertEqual(nature, "Zero Rated")

	def test_03_exempt_sale(self):
		si = sales([{"item_code": "OFT-SVC", "rate": 100, "oman_vat_code": "OM-EX"}])
		self.assertEqual(si.items[0].oman_vat_treatment, "Exempt")
		self.assertEqual(flt(si.items[0].oman_output_vat), 0)
		box = frappe.parse_json(frappe.db.get_value("Oman VAT Transaction Detail",
			{"parent": frappe.db.get_value("Oman VAT Transaction", {"source_name": si.name})}, "return_boxes"))
		self.assertEqual(box, [["1c_value", 100.0]])

	def test_04_mixed_treatment_invoice(self):
		si = sales([
			{"item_code": "OFT-GOODS", "rate": 100},
			{"item_code": "OFT-GOODS-B", "rate": 50, "oman_vat_code": "OM-Z0"},
			{"item_code": "OFT-GOODS-C", "rate": 30, "oman_vat_code": "OM-EX"},
		], submit=False)
		frappe.get_doc({"doctype": "Oman VAT Evidence", "evidence_type": "Zero-rating Certificate / Contract",
			"reference_doctype": "Sales Invoice", "reference_name": si.name, "status": "Received"}).insert()
		si.reload()
		si.submit()
		got = [(i.oman_vat_treatment, flt(i.oman_output_vat, 3)) for i in si.items]
		self.assertEqual(got, [("Standard Rated", 5.0), ("Zero Rated", 0.0), ("Exempt", 0.0)])
		self.assertEqual(flt(si.total_taxes_and_charges, 3), 5.0)

	def test_05_partially_recoverable_purchase(self):
		pi = purchase([{"item_code": "OFT-SVC", "rate": 100, "oman_recovery_profile": "OFT Business Use 40%"}])
		i = pi.items[0]
		self.assertEqual((flt(i.oman_input_vat, 3), flt(i.oman_recoverable_vat, 3), flt(i.oman_nonrecoverable_vat, 3)),
			(5.0, 2.0, 3.0))
		alloc = frappe.get_doc("Oman VAT Recovery Allocation", pi.oman_recovery_allocation)
		je = frappe.get_doc("Journal Entry", alloc.journal_entry)
		self.assertEqual(je.docstatus, 1)
		self.assertEqual(flt(sum(a.credit for a in je.accounts if a.account == acc("Oman Input VAT")), 3), 3.0)

	def test_06_blocked_input_vat(self):
		pi = purchase([{"item_code": "OFT-SVC", "rate": 200, "oman_vat_code": "OM-BL"}])
		i = pi.items[0]
		self.assertEqual((flt(i.oman_input_vat, 3), flt(i.oman_recoverable_vat, 3), flt(i.oman_nonrecoverable_vat, 3)),
			(10.0, 0.0, 10.0))
		self.assertEqual(i.oman_recovery_status, "Blocked")

	def test_07_recovery_override_requires_approver(self):
		user = "oft.vatuser@example.com"
		if not frappe.db.exists("User", user):
			u = frappe.get_doc({"doctype": "User", "email": user, "first_name": "VAT", "send_welcome_email": 0})
			u.insert(ignore_permissions=True)
			u.add_roles("Oman VAT User", "Accounts User", "Accounts Manager", "Purchase User")
		frappe.set_user(user)
		with self.assertRaises(frappe.ValidationError):
			purchase([{"item_code": "OFT-SVC", "rate": 100, "oman_recovery_override": 1,
				"oman_recovery_percentage": 80, "oman_recovery_override_reason": "test"}])
		frappe.set_user("Administrator")

	def test_08_reverse_charge_foreign_services(self):
		pi = purchase([{"item_code": "OFT-SVC", "rate": 100}], supplier="OFT UK Consultant", taxes=False)
		i = pi.items[0]
		self.assertEqual(i.oman_vat_treatment, "Import of Services")
		self.assertTrue(i.oman_reverse_charge)
		self.assertEqual(flt(i.oman_input_vat, 3), 5.0)
		self.assertEqual(flt(pi.oman_total_rcm_vat, 3), 5.0)
		self.assertEqual(flt(pi.grand_total, 3), 100.0, "supplier payable must not include self-assessed VAT")
		rce = frappe.get_doc("Oman Reverse Charge Entry", pi.oman_reverse_charge_entry)
		je = frappe.get_doc("Journal Entry", rce.journal_entry)
		self.assertEqual(flt(sum(a.credit for a in je.accounts), 3), 5.0)
		self.assertFalse(any(a.party for a in je.accounts))

	def test_09_import_of_goods_bayan(self):
		pi = purchase([{"item_code": "OFT-GOODS", "rate": 1000}], supplier="OFT UK Consultant", taxes=False)
		self.assertEqual(pi.items[0].oman_vat_treatment, "Import of Goods")
		decl = frappe.get_doc({"doctype": "Oman Import Declaration", "company": COMPANY,
			"vat_registration": pi.oman_vat_registration, "declaration_number": f"BAYAN-{frappe.generate_hash(length=6)}",
			"declaration_date": today(), "clearance_date": today(), "customs_value": 1000, "customs_duty": 50,
			"payment_method": "Deferred via VAT Return", "recovery_percentage": 100,
			"invoices": [{"purchase_invoice": pi.name}]})
		decl.insert()
		decl.submit()
		self.assertEqual(flt(decl.import_vat, 3), 52.5)
		self.assertEqual(frappe.db.get_value("Purchase Invoice", pi.name, "oman_import_declaration"), decl.name)
		dup = frappe.copy_doc(decl)
		dup.invoices = []
		with self.assertRaises(frappe.ValidationError):
			dup.insert()

	def test_10_sales_credit_note(self):
		from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_sales_return

		si = sales([{"item_code": "OFT-GOODS", "rate": 100}])
		# Credit note without an adjustment reason is rejected
		cn = make_sales_return(si.name)
		cn.insert()
		with self.assertRaises(frappe.ValidationError):
			cn.submit()
		cn.reload()
		cn.oman_adjustment_reason = "Return of Goods"
		cn.save()
		cn.submit()
		self.assertEqual(flt(cn.items[0].oman_output_vat, 3), -5.0)
		t = frappe.get_doc("Oman VAT Transaction", {"source_name": cn.name})
		self.assertTrue(t.is_adjustment)
		self.assertEqual(t.original_name, si.name)

	def test_11_foreign_currency_purchase(self):
		pi = purchase([{"item_code": "OFT-SVC", "rate": 100}], supplier="OFT US Vendor", currency="USD",
			conversion_rate=0.385)
		i = pi.items[0]
		self.assertEqual(flt(i.oman_taxable_amount, 3), 38.5)
		self.assertEqual(flt(i.oman_input_vat, 3), 1.925)

	def test_12_duplicate_supplier_invoice(self):
		purchase([{"item_code": "OFT-SVC", "rate": 10}], bill_no="DUP-0012")
		with self.assertRaises(frappe.ValidationError):
			purchase([{"item_code": "OFT-SVC", "rate": 10}], bill_no="dup 12")

	def test_13_closed_period_blocks_posting(self):
		reg = frappe.db.get_value("Oman VAT Registration", {"company": COMPANY})
		p = frappe.db.get_value("Oman VAT Period", {"vat_registration": reg, "from_date": "2026-01-01"})
		frappe.db.set_value("Oman VAT Period", p, "status", "Finalized")
		try:
			with self.assertRaises(frappe.ValidationError):
				sales([{"item_code": "OFT-GOODS", "rate": 10}], posting_date="2026-02-15")
		finally:
			frappe.db.set_value("Oman VAT Period", p, "status", "Open")

	def test_14_finalized_return_snapshot_and_sod(self):
		reg = frappe.db.get_value("Oman VAT Registration", {"company": COMPANY})
		period = frappe.db.get_value("Oman VAT Period", {"vat_registration": reg, "from_date": "2026-04-01"})
		sales([{"item_code": "OFT-GOODS", "rate": 300}], posting_date="2026-05-10")
		purchase([{"item_code": "OFT-SVC", "rate": 100}], posting_date="2026-05-11")
		ret = frappe.get_doc({"doctype": "Oman VAT Return", "company": COMPANY, "vat_registration": reg,
			"vat_period": period})
		ret.insert()
		ret.run_validation()
		ret.reload()
		self.assertEqual(ret.validation_errors, 0, ret.last_validation_log)
		ret.waive_warnings = 1
		ret.save()
		ret.mark_reviewed()
		ret.reload()
		boxes = {b.box_code: flt(b.amount, 3) for b in ret.box_totals}
		self.assertEqual(boxes["1a_vat"], 15.0)
		self.assertEqual(boxes["5a_vat"], 5.0)
		self.assertEqual(boxes["6c_vat"], 10.0)
		ret.submit()
		ret.reload()
		self.assertEqual(ret.status, "Finalized")
		check = ret.verify_snapshot()
		self.assertTrue(check["reproducible"], check)
		snap = frappe.get_doc("Oman VAT Return Snapshot", ret.snapshot)
		with self.assertRaises(frappe.ValidationError):
			snap.content_hash = "x"
			snap.save()
		with self.assertRaises(frappe.ValidationError):
			sales([{"item_code": "OFT-GOODS", "rate": 10}], posting_date="2026-05-20")
		frappe.get_doc({"doctype": "Oman VAT Filing Record", "vat_return": ret.name, "filing_reference": "OTA-TEST-1",
			"filing_date": today()}).insert()
		self.assertEqual(frappe.db.get_value("Oman VAT Return", ret.name, "status"), "Filed")
		lock = ret.lock_period("Filed and paid")
		self.assertEqual(frappe.db.get_value("Oman VAT Period", period, "status"), "Locked")
		self.assertTrue(lock)

	def test_15_segregation_of_duties(self):
		reg = frappe.db.get_value("Oman VAT Registration", {"company": COMPANY})
		period = frappe.db.get_value("Oman VAT Period", {"vat_registration": reg, "from_date": "2026-07-01"})
		user = "oft.preparer@example.com"
		if not frappe.db.exists("User", user):
			u = frappe.get_doc({"doctype": "User", "email": user, "first_name": "Prep", "send_welcome_email": 0})
			u.insert(ignore_permissions=True)
			u.add_roles("Oman VAT User", "Oman VAT Manager")
		frappe.set_user(user)
		ret = frappe.get_doc({"doctype": "Oman VAT Return", "company": COMPANY, "vat_registration": reg, "vat_period": period})
		ret.insert()
		ret.run_validation()
		ret.reload()
		ret.waive_warnings = 1
		ret.save()
		ret.mark_reviewed()
		ret.reload()
		with self.assertRaises(frappe.ValidationError):
			ret.submit()
		frappe.set_user("Administrator")
		ret.reload()
		ret.delete()

	# ------------------------------------------------------------- Fawtara
	def _submit_and_process(self, rate=100, behaviour="Accept", failures=1):
		_sandbox(behaviour, failures)
		si = sales([{"item_code": "OFT-GOODS", "rate": rate}])
		sub = frappe.db.get_value("Oman Fawtara Submission", {"reference_name": si.name})
		self.assertTrue(sub, "submission must be queued on submit")
		queue.process_submission(sub)
		return si, frappe.get_doc("Oman Fawtara Submission", sub)

	def test_20_accepted_submission_receipt(self):
		si, sub = self._submit_and_process()
		self.assertEqual(sub.status, "Accepted")
		self.assertTrue(sub.provider_reference and sub.provider_accepted_at and sub.submitted_at)
		self.assertEqual(sub.ota_status, "Reported")
		self.assertTrue(sub.ota_reported_at)
		self.assertTrue(sub.receipt and frappe.db.get_value("Oman Fawtara Receipt", sub.receipt, "receipt_file"))
		self.assertEqual(frappe.db.count("Oman Fawtara Document", {"reference_name": si.name}), 1)
		self.assertTrue(frappe.db.get_value("Sales Invoice", si.name, "oman_fawtara_uuid"))
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc("Sales Invoice", si.name).cancel()

	def test_21_provider_accepted_vs_ota_reported(self):
		si, sub = self._submit_and_process(behaviour="Accept, OTA Pending")
		self.assertEqual(sub.status, "Accepted")
		self.assertEqual(sub.ota_status, "Not Reported")
		self.assertFalse(sub.ota_reported_at)
		queue.poll_status()
		sub.reload()
		self.assertEqual(sub.ota_status, "Acknowledged")
		self.assertTrue(sub.ota_acknowledged_at)

	def test_22_duplicate_request_idempotent(self):
		si, sub = self._submit_and_process()
		self.assertEqual(queue.on_invoice_submit(frappe.get_doc("Sales Invoice", si.name)), sub.name)
		frappe.db.set_value("Oman Fawtara Submission", sub.name, "status", "Pending")
		queue.process_submission(sub.name)  # replay with the same idempotency key
		sub.reload()
		self.assertEqual(sub.status, "Accepted")
		self.assertEqual(frappe.db.count("Oman Fawtara Submission", {"reference_name": si.name}), 1)
		self.assertIn("idempotent", frappe.db.get_value("Oman Fawtara Submission Log",
			{"submission": sub.name, "attempt": 2}, "message"))

	def test_23_rejection_and_correction(self):
		si, sub = self._submit_and_process(behaviour="Reject")
		self.assertEqual(sub.status, "Rejected")
		self.assertTrue(frappe.db.exists("Oman Fawtara Error Log", {"submission": sub.name, "category": "Provider Rejection"}))
		queue.process_due()
		sub.reload()
		self.assertEqual(sub.attempt_count, 1, "rejections must never be retried automatically")
		with self.assertRaises(frappe.ValidationError):
			queue.retry_now(sub.name)
		_sandbox("Accept")
		new = queue.resubmit(sub.name, "Buyer VAT number corrected")
		queue.process_submission(new)
		self.assertEqual(frappe.db.get_value("Oman Fawtara Submission", new, "status"), "Accepted")
		self.assertEqual(frappe.db.get_value("Oman Fawtara Submission", sub.name, "superseded_by"), new)

	def test_24_network_failure_safe_retry(self):
		si, sub = self._submit_and_process(behaviour="Transient Failure then Accept", failures=2)
		self.assertEqual(sub.status, "Retry")
		self.assertTrue(sub.next_attempt_at)
		for _i in range(2):
			frappe.db.set_value("Oman Fawtara Submission", sub.name, "next_attempt_at", frappe.utils.now_datetime())
			queue.process_due()
		sub.reload()
		self.assertEqual(sub.status, "Accepted")
		self.assertEqual(sub.attempt_count, 3)
		self.assertEqual(frappe.db.count("Oman Fawtara Document", {"reference_name": si.name}), 1)

	def test_25_xml_content(self):
		si, sub = self._submit_and_process(rate=200)
		xml = frappe.get_doc("File", {"file_url": sub.xml_file}).get_content()
		xml = xml.decode() if isinstance(xml, bytes) else xml
		self.assertIn(VATIN, xml)
		self.assertIn("<cbc:TaxAmount currencyID=\"OMR\">10.000</cbc:TaxAmount>", xml)
		self.assertIn(sub.document_uuid, xml)

	# ------------------------------------------------------------- Ledger
	def test_30_gl_reconciliation(self):
		reg = frappe.db.get_value("Oman VAT Registration", {"company": COMPANY})
		rows = reconciliation.compute(COMPANY, reg, "2026-01-01", "2026-12-31")
		bad = [r for r in rows if abs(r["difference"]) > 0.001]
		self.assertEqual(bad, [], rows)

	def test_31_audit_chain_intact(self):
		res = audit.verify_chain()
		self.assertTrue(res["valid"], res)
		self.assertGreater(res["checked"], 0)

	def test_32_transaction_immutable(self):
		name = frappe.db.get_value("Oman VAT Transaction", {"company": COMPANY})
		t = frappe.get_doc("Oman VAT Transaction", name)
		t.total_output_vat = 999
		with self.assertRaises(frappe.ValidationError):
			t.save(ignore_permissions=True)

	def test_33_rate_history_effective_dating(self):
		from oman_fawtara.vat.rules import get_rate

		rate, ref = get_rate("Standard Rated", None, getdate("2026-06-01"))
		self.assertEqual(rate, 5)
		with self.assertRaises(frappe.ValidationError):
			get_rate("Standard Rated", None, getdate("2020-01-01"))
