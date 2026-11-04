"""Baseline master data.

Everything here is *configuration*, stored with effective dates and a
rule-set version, and is meant to be reviewed by an Oman VAT specialist
before production use (Oman VAT Settings → Legal Rule-set Review).

Verified statutory baseline used for seeding:
* Standard rate 5% (VAT Law, Royal Decree 121/2020; VAT effective 16 April 2021).
* Fawtara mandate dates per Decision No. 189/2026: 1 April 2027 (annual
  supplies > OMR 5 million) and 1 October 2027 (all others).

Return box layout and some check parameters (e.g. invoice issue days, bad-debt
age) are working defaults to be confirmed against the current OTA return form
and Executive Regulations.
"""

import frappe

RULESET = "OM-VAT-2026.11-BASELINE"
VAT_START = "2021-04-16"
LAW = "Royal Decree 121/2020 (VAT Law) and Executive Regulations, as amended"

ROLES = ["Oman VAT User", "Oman VAT Manager", "Oman VAT Approver", "Fawtara Operator", "Fawtara Manager"]

EVIDENCE_TYPES = [
	("Customs Export Declaration", "Export"),
	("Proof of Export (B/L, AWB, CMR)", "Export"),
	("Proof of Services Used Outside Oman", "Zero-rated Supply"),
	("Zero-rating Certificate / Contract", "Zero-rated Supply"),
	("Customs Import Declaration (Bayan)", "Import"),
	("Supplier Tax Invoice", "Input Claim"),
	("Self-billing Agreement", "Other"),
	("Bad Debt Write-off Evidence", "Bad Debt"),
]

# name, arabic, nature, direction, charges_vat, rc, import, recovery, category, exemption code/text, threshold, evidence
TREATMENTS = [
	("Standard Rated", "خاضع للنسبة الأساسية", "Standard Rated", "Both", 1, 0, 0, "Full", "S", None, None, 1, None),
	("Zero Rated", "خاضع لنسبة الصفر", "Zero Rated", "Both", 0, 0, 0, "Full", "Z", None, None, 1, "Zero-rating Certificate / Contract"),
	("Zero Rated Export", "تصدير خاضع لنسبة الصفر", "Zero Rated", "Sales", 0, 0, 0, "Full", "Z", None, None, 1, "Proof of Export (B/L, AWB, CMR)"),
	("Exempt", "معفى", "Exempt", "Both", 0, 0, 0, "Full", "E", "VATEX-OM-EXEMPT", "Exempt supply", 1, None),
	("Out of Scope", "خارج النطاق", "Out of Scope", "Both", 0, 0, 0, "Full", "O", "VATEX-OM-OOS", "Outside the scope of Oman VAT", 0, None),
	("Reverse Charge", "الاحتساب العكسي", "Standard Rated", "Purchase", 0, 1, 0, "Full", "AE", "VATEX-OM-AE", "Reverse charge", 1, "Supplier Tax Invoice"),
	("Import of Services", "استيراد خدمات", "Standard Rated", "Purchase", 0, 1, 1, "Full", "AE", "VATEX-OM-AE", "Reverse charge", 1, "Supplier Tax Invoice"),
	("Import of Goods", "استيراد سلع", "Standard Rated", "Purchase", 0, 0, 1, "Full", "S", None, None, 0, "Customs Import Declaration (Bayan)"),
	("Mixed Use Expense", "مصروف مختلط الاستخدام", "Standard Rated", "Purchase", 1, 0, 0, "Partial", "S", None, None, 0, None),
	("Blocked Input VAT", "ضريبة مدخلات غير قابلة للخصم", "Standard Rated", "Purchase", 1, 0, 0, "Blocked", "S", None, None, 0, None),
]

# rate history: treatment, rate
RATES = [
	("Standard Rated", 5), ("Zero Rated", 0), ("Zero Rated Export", 0), ("Exempt", 0), ("Out of Scope", 0),
	("Reverse Charge", 5), ("Import of Services", 5), ("Import of Goods", 5), ("Mixed Use Expense", 5),
	("Blocked Input VAT", 5),
]

# Working VAT return layout (verify against the OTA return form in force)
BOXES = [
	("1a_value", "1(a) Supplies taxed at the basic rate – value", "1. Supplies", "Taxable Value", 10, None),
	("1a_vat", "1(a) Supplies taxed at the basic rate – VAT", "1. Supplies", "VAT", 11, None),
	("1b_value", "1(b) Supplies taxed at zero rate", "1. Supplies", "Taxable Value", 20, None),
	("1c_value", "1(c) Exempt supplies", "1. Supplies", "Taxable Value", 30, None),
	("1e_value", "1(e) Supplies outside the scope", "1. Supplies", "Taxable Value", 40, None),
	("2a_value", "2(a) Purchases subject to reverse charge – value", "2. Reverse Charge", "Taxable Value", 50, None),
	("2a_vat", "2(a) Purchases subject to reverse charge – VAT", "2. Reverse Charge", "VAT", 51, None),
	("3a_value", "3(a) Imports of goods (postponed payment) – value", "3. Imports", "Taxable Value", 60, None),
	("3a_vat", "3(a) Imports of goods (postponed payment) – VAT", "3. Imports", "VAT", 61, None),
	("4b_vat", "4(b) Adjustment of VAT due", "4. VAT Due", "VAT", 70, None),
	("4a_vat", "4(a) Total VAT due", "4. VAT Due", "Total", 75, "1a_vat+2a_vat+3a_vat+4b_vat"),
	("5a_value", "5(a) Purchases (excluding imports) – value", "5. Input VAT", "Taxable Value", 80, None),
	("5a_vat", "5(a) Purchases (excluding imports) – recoverable VAT", "5. Input VAT", "VAT", 81, None),
	("5b_value", "5(b) Imports of goods – value", "5. Input VAT", "Taxable Value", 82, None),
	("5b_vat", "5(b) Imports of goods – recoverable VAT", "5. Input VAT", "VAT", 83, None),
	("5c_vat", "5(c) VAT on acquisition of fixed assets", "5. Input VAT", "VAT", 84, None),
	("5d_vat", "5(d) Adjustment of input VAT", "5. Input VAT", "VAT", 85, None),
	("5e_vat", "5(e) Total recoverable input VAT", "5. Input VAT", "Total", 86, "5a_vat+5b_vat+5c_vat+5d_vat"),
	("6c_vat", "6. Net VAT payable / (refundable)", "6. Net VAT", "Total", 99, "4a_vat-5e_vat"),
]

# code, title, treatment, direction, default, export, out_value, out_vat, in_value, in_vat, fa_vat, out_adj, in_adj
CODES = [
	("OM-S5", "Standard rated 5%", "Standard Rated", "Both", 1, 0, "1a_value", "1a_vat", "5a_value", "5a_vat", "5c_vat", "4b_vat", "5d_vat"),
	("OM-Z0", "Zero rated (domestic)", "Zero Rated", "Both", 1, 0, "1b_value", None, "5a_value", None, None, "4b_vat", "5d_vat"),
	("OM-ZX", "Zero rated export / international", "Zero Rated Export", "Sales", 1, 1, "1b_value", None, None, None, None, "4b_vat", None),
	("OM-EX", "Exempt", "Exempt", "Both", 1, 0, "1c_value", None, None, None, None, None, None),
	("OM-OS", "Out of scope", "Out of Scope", "Both", 1, 0, "1e_value", None, None, None, None, None, None),
	("OM-RC", "Reverse charge (domestic/designated)", "Reverse Charge", "Purchase", 1, 0, "2a_value", "2a_vat", "5a_value", "5a_vat", "5c_vat", "4b_vat", "5d_vat"),
	("OM-IS", "Import of services (reverse charge)", "Import of Services", "Purchase", 1, 0, "2a_value", "2a_vat", "5a_value", "5a_vat", "5c_vat", "4b_vat", "5d_vat"),
	("OM-IG", "Import of goods (customs)", "Import of Goods", "Purchase", 1, 0, "3a_value", "3a_vat", "5b_value", "5b_vat", "5b_vat", "4b_vat", "5d_vat"),
	("OM-MX", "Standard rated, mixed use", "Mixed Use Expense", "Purchase", 1, 0, None, None, "5a_value", "5a_vat", "5c_vat", None, "5d_vat"),
	("OM-BL", "Standard rated, blocked input VAT", "Blocked Input VAT", "Purchase", 1, 0, None, None, "5a_value", "5a_vat", "5c_vat", None, "5d_vat"),
]

# rule_code, title, check_key, applies_to, severity, numeric, message
RULES = [
	("OM-VAL-001", "Party VAT number format", "party_vrn_format", "Both", "Warning", None, None),
	("OM-VAL-002", "VAT-registered buyer must have VAT number", "b2b_requires_buyer_vrn", "Sales", "Error", None, None),
	("OM-VAL-003", "Input VAT claim requires supplier VAT number", "input_claim_requires_supplier_vrn", "Purchase", "Error", None, None),
	("OM-VAL-004", "Zero-rated supplies require evidence", "zero_rated_requires_evidence", "Sales", "Warning", None, None),
	("OM-VAL-005", "Export code requires foreign destination", "export_requires_foreign_destination", "Sales", "Error", None, None),
	("OM-VAL-006", "Tax invoice issued within N days of supply", "invoice_issue_within_days", "Sales", "Warning", 15, None),
	("OM-VAL-007", "Duplicate supplier invoice / VAT claim", "duplicate_supplier_invoice", "Purchase", "Error", None, None),
	("OM-VAL-008", "Foreign services should be reverse charged", "rcm_foreign_services", "Purchase", "Warning", None, None),
	("OM-VAL-009", "Imported goods need a customs declaration", "import_goods_requires_declaration", "Purchase", "Warning", None, None),
	("OM-VAL-010", "Credit/debit note references original", "credit_note_requires_original", "Both", "Error", None, None),
	("OM-VAL-011", "Credit/debit note adjustment reason", "adjustment_reason_required", "Both", "Error", None, None),
	("OM-VAL-012", "Exchange rate to OMR present", "foreign_currency_rate", "Both", "Error", None, None),
	("OM-VAL-013", "Bad debt relief minimum age (days)", "bad_debt_min_age_days", "Sales", "Error", 180, None),
]

PROFILES = [
	("Full Recovery", "Full Recovery", 100, 0, "Approved"),
	("Blocked", "Blocked", 0, 0, "Approved"),
	("Business Use 50%", "Business Use", 50, 0, "Draft"),
	("Standard Apportionment", "Standard Apportionment", 0, 100, "Draft"),
]

UOM_CODES = {"Nos": "H87", "Unit": "C62", "Kg": "KGM", "Gram": "GRM", "Litre": "LTR", "Meter": "MTR",
	"Hour": "HUR", "Day": "DAY", "Box": "BX", "Pair": "PR", "Set": "SET", "Month": "MON", "Year": "ANN"}


def _insert(doc):
	d = frappe.get_doc(doc)
	d.flags.ignore_permissions = True
	d.flags.ignore_links = True
	d.insert(ignore_if_duplicate=True)
	return d


def seed_all():
	frappe.flags.in_install = True
	try:
		for role in ROLES:
			if not frappe.db.exists("Role", role):
				_insert({"doctype": "Role", "role_name": role, "desk_access": 1})
		for name, applies in EVIDENCE_TYPES:
			if not frappe.db.exists("Oman VAT Evidence Type", name):
				_insert({"doctype": "Oman VAT Evidence Type", "evidence_type": name, "applies_to": applies})
		for b in BOXES:
			if not frappe.db.exists("Oman VAT Return Box", b[0]):
				_insert({"doctype": "Oman VAT Return Box", "box_code": b[0], "label": b[1], "section": b[2], "value_type": b[3],
					"sequence": b[4], "formula": b[5], "enabled": 1, "effective_from": VAT_START,
					"notes": "Working layout – confirm against the current OTA VAT return form."})
		for t in TREATMENTS:
			if not frappe.db.exists("Oman VAT Treatment", t[0]):
				_insert({"doctype": "Oman VAT Treatment", "treatment_name": t[0], "treatment_name_ar": t[1], "nature": t[2],
					"direction": t[3], "charges_vat": t[4], "is_reverse_charge": t[5], "is_import": t[6],
					"input_recovery_default": t[7], "tax_category_code": t[8], "exemption_reason_code": t[9],
					"exemption_reason": t[10], "counts_for_fawtara_threshold": t[11],
					"requires_evidence": 1 if t[12] else 0, "evidence_type": t[12]})
		for c in CODES:
			if not frappe.db.exists("Oman VAT Code", c[0]):
				_insert({"doctype": "Oman VAT Code", "code": c[0], "title": c[1], "treatment": c[2], "direction": c[3],
					"is_default": c[4], "is_export": c[5], "output_value_box": c[6], "output_vat_box": c[7],
					"input_value_box": c[8], "input_vat_box": c[9], "fixed_asset_input_vat_box": c[10],
					"output_adjustment_box": c[11], "input_adjustment_box": c[12]})
		for treatment, rate in RATES:
			if not frappe.db.exists("Oman VAT Rate History", {"treatment": treatment, "vat_code": ["is", "not set"]}):
				_insert({"doctype": "Oman VAT Rate History", "treatment": treatment, "rate": rate,
					"effective_from": VAT_START, "ruleset_version": RULESET, "legal_reference": LAW})
		for r in RULES:
			if not frappe.db.exists("Oman VAT Rule", r[0]):
				_insert({"doctype": "Oman VAT Rule", "rule_code": r[0], "title": r[1], "rule_type": "Validation",
					"check_key": r[2], "applies_to": r[3], "severity": r[4], "numeric_value": r[5], "message": r[6],
					"status": "Approved", "enabled": 1, "effective_from": VAT_START, "ruleset_version": RULESET,
					"legal_reference": LAW})
		for p in PROFILES:
			if not frappe.db.exists("Oman VAT Recovery Profile", p[0]):
				_insert({"doctype": "Oman VAT Recovery Profile", "profile_name": p[0], "method": p[1],
					"recovery_percentage": p[2], "provisional_percentage": p[3], "status": p[4],
					"legal_basis": "Seeded default – approve a business-specific method before use." if p[4] == "Draft" else None})
		for uom, code in UOM_CODES.items():
			if frappe.db.exists("UOM", uom) and not frappe.db.get_value("UOM", uom, "oman_unece_code"):
				frappe.db.set_value("UOM", uom, "oman_unece_code", code, update_modified=False)
		if not frappe.db.exists("Oman Fawtara Provider", "Sandbox"):
			_insert({"doctype": "Oman Fawtara Provider", "provider_name": "Sandbox", "adapter": "Sandbox (Simulated)",
				"enabled": 1, "environment": "Sandbox", "sandbox_behaviour": "Accept", "auth_type": "None",
				"notes": "Simulated provider for UAT and automated tests. Not an accredited service provider."})
		_settings_defaults()
	finally:
		frappe.flags.in_install = False


def _settings_defaults():
	s = frappe.get_single("Oman VAT Settings")
	defaults = {
		"enforcement_mode": "Block",
		"active_ruleset_version": RULESET,
		"vrn_pattern": r"^OM\d{10}$",
		"currency_precision": 3,
		"line_tolerance": 0.001,
		"default_sales_treatment": "Standard Rated",
		"default_purchase_treatment": "Standard Rated",
		"import_of_services_treatment": "Import of Services",
		"import_of_goods_treatment": "Import of Goods",
		"auto_detect_reverse_charge": 1,
		"auto_apply_item_tax_template": 1,
		"reverse_charge_posting": "Journal Entry",
		"default_recovery_profile": "Full Recovery",
		"credit_note_reporting": "Net in Original Box",
		"total_vat_due_box": "4a_vat",
		"total_input_vat_box": "5e_vat",
		"net_vat_box": "6c_vat",
		"return_due_days": 30,
		"reconciliation_tolerance": 0.01,
		"zero_rated_evidence_severity_at_return": "Error",
		"enforce_segregation_of_duties": 1,
		"restrict_manual_vat_journals": 1,
		"charge_nonrecoverable_to_item_expense": 1,
		"exclude_pending_from_return": 1,
	}
	changed = False
	if not s.active_ruleset_version:
		s.enabled = 1
		changed = True
	for k, v in defaults.items():
		if s.get(k) in (None, ""):
			s.set(k, v)
			changed = True
	if changed:
		s.flags.ignore_permissions = True
		s.flags.ignore_mandatory = True
		s.save()

	f = frappe.get_single("Oman Fawtara Settings")
	fdefaults = {
		"customization_id": "urn:peppol:pint:billing-1@om-1",
		"profile_id": "urn:peppol:bis:billing",
		"phase_1_date": "2027-04-01",
		"phase_2_date": "2027-10-01",
		"mandate_threshold_omr": 5000000,
		"threshold_period_start": "2026-04-01",
		"threshold_period_end": "2027-03-31",
		"default_provider": "Sandbox",
		"submit_immediately": 1,
		"block_on_local_validation_error": 1,
		"include_b2c": 1,
		"include_b2g": 1,
		"skip_out_of_scope_only": 1,
		"require_endpoint": 1,
		"use_credit_note_root": 1,
		"default_payment_means_code": "30",
		"local_tolerance": 0.01,
		"max_attempts": 8,
		"retry_base_seconds": 60,
		"batch_size": 200,
		"new_uuid_on_resubmit": 1,
		"retention_years": 10,
		"transaction_flag_order": "b2b,b2c,b2g,self_billing,reverse_charge,export,import",
		"legal_source_notes": (
			"Decision No. 189/2026 (Official Gazette, 9 Aug 2026) amending the VAT Executive Regulations: "
			"e-invoicing mandatory from 1 Apr 2027 for annual supplies > OMR 5m and from 1 Oct 2027 for others. "
			"Threshold reference periods per OTA Fawtara FAQ – verify the current FAQ."
		),
	}
	for k, v in fdefaults.items():
		if f.get(k) in (None, ""):
			f.set(k, v)
	f.flags.ignore_permissions = True
	f.flags.ignore_mandatory = True
	f.save()
