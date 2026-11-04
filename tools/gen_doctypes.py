#!/usr/bin/env python3
"""Generate DocType JSON + stubs for thinkNXG Oman Fawtara.

Usage: python3 tools/gen_doctypes.py <app_root>
Existing controller .py / .js files are never overwritten.
"""

import json
import os
import re
import sys

APP = "oman_fawtara"
MODULE = "Oman Fawtara"
TS = "2026-11-04 12:00:00.000000"


def snake(name):
	return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def F(fieldname, fieldtype, label=None, options=None, **kw):
	d = {"fieldname": fieldname, "fieldtype": fieldtype}
	if label is None and fieldtype not in ("Column Break",):
		label = fieldname.replace("_", " ").title().replace("Vat", "VAT").replace("Omr", "OMR").replace("Ota", "OTA") \
			.replace("Rcm", "RCM").replace("Uuid", "UUID").replace("Xml", "XML").replace("Vrn", "VRN").replace("Url", "URL") \
			.replace("Http", "HTTP").replace("Tls", "TLS").replace("Gl ", "GL ")
	if label:
		d["label"] = label
	if options is not None:
		d["options"] = options
	for k, v in kw.items():
		d[k] = v
	return d


def SB(name, label=None, **kw):
	return F(name, "Section Break", label, **kw)


def CB(name):
	return {"fieldname": name, "fieldtype": "Column Break"}


def TAB(name, label):
	return F(name, "Tab Break", label)


def MONEY(fn, label=None, **kw):
	return F(fn, "Float", label, precision="3", **kw)


def RO(f):
	f["read_only"] = 1
	return f


def perm(role, r=1, w=0, c=0, d=0, s=0, cancel=0, amend=0, export=1, report=1):
	p = {"role": role, "read": r, "write": w, "create": c, "delete": d, "report": report, "export": export,
		"print": 1, "email": 1, "share": 1 if w else 0}
	if s:
		p["submit"] = 1
	if cancel:
		p["cancel"] = 1
	if amend:
		p["amend"] = 1
	return p


P_CONFIG = [
	perm("System Manager", w=1, c=1, d=1),
	perm("Oman VAT Approver", w=1, c=1, d=1),
	perm("Oman VAT Manager", w=1, c=1),
	perm("Oman VAT User"),
	perm("Accounts Manager"),
	perm("Accounts User"),
]
P_READONLY = [
	perm("System Manager"),
	perm("Oman VAT Approver"),
	perm("Oman VAT Manager"),
	perm("Oman VAT User"),
	perm("Accounts Manager"),
	perm("Auditor"),
]
P_SUBMIT = [
	perm("System Manager", w=1, c=1, d=1, s=1, cancel=1, amend=1),
	perm("Oman VAT Approver", w=1, c=1, d=1, s=1, cancel=1, amend=1),
	perm("Oman VAT Manager", w=1, c=1, s=1, cancel=1, amend=1),
	perm("Oman VAT User", w=1, c=1),
	perm("Accounts Manager"),
	perm("Auditor"),
]
P_SYSTEM_SUBMIT = [  # created by the engine, cancelled with their source document
	perm("System Manager", s=0, cancel=1),
	perm("Oman VAT Approver", cancel=1),
	perm("Oman VAT Manager"),
	perm("Oman VAT User"),
	perm("Accounts Manager"),
	perm("Auditor"),
]
P_RETURN = [
	perm("System Manager", w=1, c=1, d=1, s=1, cancel=1, amend=1),
	perm("Oman VAT Approver", w=1, c=1, s=1, cancel=1, amend=1),
	perm("Oman VAT Manager", w=1, c=1, s=1),
	perm("Oman VAT User", w=1, c=1),
	perm("Accounts Manager"),
	perm("Auditor"),
]
P_SETTINGS = [perm("System Manager", w=1, c=1), perm("Oman VAT Approver", w=1, c=1), perm("Oman VAT Manager"),
	perm("Oman VAT User")]
P_F_SETTINGS = [perm("System Manager", w=1, c=1), perm("Fawtara Manager", w=1, c=1), perm("Fawtara Operator"),
	perm("Oman VAT Manager")]
P_F_CONFIG = [perm("System Manager", w=1, c=1, d=1), perm("Fawtara Manager", w=1, c=1, d=1), perm("Fawtara Operator"),
	perm("Oman VAT Manager")]
P_F_QUEUE = [perm("System Manager", w=1), perm("Fawtara Manager", w=1), perm("Fawtara Operator"),
	perm("Oman VAT Manager"), perm("Oman VAT User"), perm("Auditor")]
P_AUDIT = [perm("System Manager"), perm("Oman VAT Approver"), perm("Oman VAT Manager"), perm("Auditor")]

YN_STATUS = "Active\nSuspended\nDeregistered"
NATURE = "Standard Rated\nZero Rated\nExempt\nOut of Scope"
DIRECTION = "Sales\nPurchase\nBoth"
BOX_FIELDS = [
	SB("sb_boxes", "VAT Return Boxes"),
	F("output_value_box", "Link", "Output / Self-assessed Value Box", "Oman VAT Return Box"),
	F("output_vat_box", "Link", "Output / Self-assessed VAT Box", "Oman VAT Return Box"),
	F("output_adjustment_box", "Link", "Output Adjustment Box", "Oman VAT Return Box"),
	CB("cb_boxes"),
	F("input_value_box", "Link", "Input Value Box", "Oman VAT Return Box"),
	F("input_vat_box", "Link", "Input VAT Box (Recoverable)", "Oman VAT Return Box"),
	F("fixed_asset_input_vat_box", "Link", "Fixed Asset Input VAT Box", "Oman VAT Return Box"),
	F("input_adjustment_box", "Link", "Input Adjustment Box", "Oman VAT Return Box"),
]
CHECK_KEYS = "\n".join(
	[
		"",
		"party_vrn_format",
		"b2b_requires_buyer_vrn",
		"input_claim_requires_supplier_vrn",
		"zero_rated_requires_evidence",
		"export_requires_foreign_destination",
		"invoice_issue_within_days",
		"duplicate_supplier_invoice",
		"rcm_foreign_services",
		"import_goods_requires_declaration",
		"credit_note_requires_original",
		"adjustment_reason_required",
		"foreign_currency_rate",
		"b2c_simplified_threshold",
		"bad_debt_min_age_days",
	]
)
ADJ_REASONS = "\nReturn of Goods\nPrice Reduction / Discount\nCancellation of Supply\nChange in Consideration\nIncorrect VAT Treatment\nIncorrect Amount\nBad Debt\nOther"

DT = {}


def doctype(name, fields, perms=None, **meta):
	DT[name] = {"fields": fields, "permissions": perms if perms is not None else [], **meta}


# =========================== A. Configuration ===========================

doctype("Oman VAT Settings", [
	TAB("tab_general", "General"),
	F("enabled", "Check", "Enable Oman VAT Engine", default="1"),
	F("enforcement_mode", "Select", "Enforcement Mode", "Block\nAdvisory", default="Block",
		description="Block: validation errors prevent submission. Advisory: errors are recorded and must be cleared before the VAT return is finalized."),
	F("active_ruleset_version", "Data", "Active Rule-set Version", default="OM-VAT-2026.11-BASELINE"),
	CB("cb_g1"),
	F("vrn_pattern", "Data", "VAT Number Pattern (regex)", default="^OM\\d{10}$"),
	F("currency_precision", "Int", "OMR Precision", default="3"),
	F("line_tolerance", "Float", "Per-line Tolerance (OMR)", default="0.001", precision="3"),
	F("allow_future_tax_point", "Check", "Allow Future Tax Point"),
	SB("sb_legal", "Legal Rule-set Review"),
	F("legal_review_confirmed", "Check", "Legal Rule-set Reviewed for Production",
		description="Confirm that the rule set reflects Royal Decree 121/2020, the Executive Regulations and all amendments (including Decision 189/2026) as reviewed by an Oman VAT specialist. Production Fawtara providers cannot be enabled until confirmed."),
	F("legal_reviewed_by", "Link", "Reviewed By", "User", read_only=1),
	F("legal_reviewed_on", "Datetime", "Reviewed On", read_only=1),
	CB("cb_legal"),
	F("legal_review_notes", "Small Text", "Review Notes / Specialist Reference"),
	TAB("tab_treatments", "Treatments"),
	F("default_sales_treatment", "Link", "Default Sales Treatment", "Oman VAT Treatment"),
	F("default_purchase_treatment", "Link", "Default Purchase Treatment", "Oman VAT Treatment"),
	F("import_of_services_treatment", "Link", "Import of Services Treatment", "Oman VAT Treatment"),
	F("import_of_goods_treatment", "Link", "Import of Goods Treatment", "Oman VAT Treatment"),
	CB("cb_t1"),
	F("auto_detect_reverse_charge", "Check", "Auto-detect Reverse Charge / Imports", default="1"),
	F("auto_apply_item_tax_template", "Check", "Auto-apply Item Tax Template from VAT Code", default="1"),
	F("reverse_charge_posting", "Select", "Reverse Charge Posting", "Journal Entry\nTax Template", default="Journal Entry"),
	TAB("tab_recovery", "Recovery"),
	F("default_recovery_profile", "Link", "Default Recovery Profile", "Oman VAT Recovery Profile"),
	F("default_partial_recovery_profile", "Link", "Default Profile for Mixed-use Treatment", "Oman VAT Recovery Profile"),
	CB("cb_r1"),
	F("charge_nonrecoverable_to_item_expense", "Check", "Charge Non-recoverable VAT to the Line's Expense Account", default="1",
		description="Stock and fixed-asset lines always use the Non-Recoverable VAT Account from the account mapping."),
	F("exclude_pending_from_return", "Check", "Exclude Pending-evidence Input VAT from Return", default="1"),
	TAB("tab_return", "Return"),
	F("credit_note_reporting", "Select", "Credit/Debit Note Reporting", "Net in Original Box\nAdjustment Box", default="Net in Original Box"),
	F("total_vat_due_box", "Link", "Total VAT Due Box", "Oman VAT Return Box"),
	F("total_input_vat_box", "Link", "Total Input VAT Box", "Oman VAT Return Box"),
	F("net_vat_box", "Link", "Net VAT Box", "Oman VAT Return Box"),
	CB("cb_ret"),
	F("return_due_days", "Int", "Return Due (days after period end)", default="30"),
	F("reconciliation_tolerance", "Float", "GL Reconciliation Tolerance (OMR)", default="0.010", precision="3"),
	F("zero_rated_evidence_severity_at_return", "Select", "Missing Zero-rated Evidence at Return", "Error\nWarning", default="Error"),
	SB("sb_controls", "Controls"),
	F("enforce_segregation_of_duties", "Check", "Preparer Cannot Finalize Own Return", default="1"),
	F("restrict_manual_vat_journals", "Check", "Restrict Manual Journals on VAT Accounts", default="1"),
], P_SETTINGS, issingle=1)

doctype("Oman VAT Registration", [
	F("company", "Link", "Company", "Company", reqd=1, in_list_view=1, in_standard_filter=1),
	F("vatin", "Data", "VAT Registration Number", reqd=1, in_list_view=1, bold=1),
	F("legal_name", "Data", "Legal Name (as registered)"),
	F("trade_name", "Data", "Trade Name"),
	CB("cb1"),
	F("status", "Select", "Status", YN_STATUS, default="Active", in_list_view=1),
	F("is_default", "Check", "Default for Company", default="1"),
	F("commercial_registration_no", "Data", "Commercial Registration (CR) No."),
	F("tax_card_number", "Data", "Tax Card / TIN"),
	SB("sb_dates", "Validity"),
	F("registration_date", "Date", "Registration Date"),
	F("effective_from", "Date", "Effective From", reqd=1),
	F("effective_to", "Date", "Effective To"),
	CB("cb2"),
	F("return_frequency", "Select", "Return Frequency", "Quarterly\nMonthly", default="Quarterly"),
	F("first_period_start", "Date", "First Return Period Start"),
	F("is_tax_group", "Check", "VAT Group Registration"),
	F("group_members", "Small Text", "Group Member Companies", depends_on="is_tax_group"),
	SB("sb_contact", "Address & Contact"),
	F("address", "Link", "Registered Address", "Address"),
	CB("cb3"),
	F("contact_email", "Data", "Contact Email", options="Email"),
	F("contact_phone", "Data", "Contact Phone"),
	TAB("tab_fawtara", "Fawtara"),
	F("fawtara_enabled", "Check", "Fawtara E-invoicing Enabled"),
	F("fawtara_provider", "Link", "Accredited Service Provider", "Oman Fawtara Provider"),
	F("peppol_participant_id", "Data", "Electronic Address / Participant ID"),
	CB("cb_f"),
	RO(F("fawtara_mandate_date", "Date", "Mandatory From (computed)")),
	F("fawtara_mandate_date_override", "Date", "Mandate Date Override"),
	F("fawtara_voluntary_start_date", "Date", "Voluntary / Pilot Start Date"),
	SB("sb_threshold", "OMR 5 million Threshold Assessment",
		description="Supplies counted per Oman Fawtara Settings (reference periods) and the treatments flagged 'Counts for Fawtara Threshold'. Verify the assessment independently."),
	MONEY("annual_supplies_reference", "Supplies in Reference Period (OMR)"),
	MONEY("annual_supplies_expected", "Expected Supplies, Next 12 Months (OMR)"),
	CB("cb_th"),
	RO(MONEY("annual_supplies_computed", "Computed from VAT Ledger (OMR)")),
], P_CONFIG, autoname="OVREG-.#####", title_field="vatin", search_fields="company,vatin", show_title_field_in_link=1)

doctype("Oman VAT Treatment", [
	F("treatment_name", "Data", "Treatment", reqd=1, unique=1, in_list_view=1),
	F("treatment_name_ar", "Data", "Treatment (Arabic)"),
	F("nature", "Select", "Nature", NATURE, reqd=1, in_list_view=1,
		description="Nature is independent of the rate: zero-rated and exempt are never interchangeable."),
	F("direction", "Select", "Applies To", DIRECTION, default="Both", in_list_view=1),
	CB("cb1"),
	F("charges_vat", "Check", "Supplier Charges VAT on Invoice"),
	F("is_reverse_charge", "Check", "Reverse Charge (self-assessed)"),
	F("is_import", "Check", "Import"),
	F("input_recovery_default", "Select", "Input Recovery Behaviour", "Full\nPartial\nBlocked", default="Full"),
	SB("sb_einv", "E-invoice"),
	F("tax_category_code", "Data", "Tax Category Code (UNCL5305)", default="S"),
	F("exemption_reason_code", "Data", "Exemption Reason Code"),
	CB("cb2"),
	F("exemption_reason", "Data", "Exemption Reason Text"),
	F("counts_for_fawtara_threshold", "Check", "Counts for Fawtara Threshold"),
	SB("sb_ev", "Evidence"),
	F("requires_evidence", "Check", "Requires Evidence"),
	F("evidence_type", "Link", "Evidence Type", "Oman VAT Evidence Type", depends_on="requires_evidence"),
	F("description", "Small Text", "Description"),
	F("disabled", "Check", "Disabled"),
], P_CONFIG, autoname="field:treatment_name")

doctype("Oman VAT Code Template", [
	F("company", "Link", "Company", "Company", reqd=1, in_list_view=1),
	F("item_tax_template", "Link", "Item Tax Template", "Item Tax Template", reqd=1, in_list_view=1),
], [], istable=1, editable_grid=1)

doctype("Oman VAT Code", [
	F("code", "Data", "Code", reqd=1, unique=1, in_list_view=1),
	F("title", "Data", "Title", reqd=1, in_list_view=1),
	F("treatment", "Link", "Treatment", "Oman VAT Treatment", reqd=1, in_list_view=1, in_standard_filter=1),
	CB("cb1"),
	F("direction", "Select", "Direction", DIRECTION, default="Both"),
	F("is_default", "Check", "Default Code for Treatment"),
	F("is_export", "Check", "Export / International Supply"),
	F("disabled", "Check", "Disabled"),
	*BOX_FIELDS,
	SB("sb_tmpl", "ERPNext Item Tax Templates"),
	F("templates", "Table", "Item Tax Templates per Company", "Oman VAT Code Template"),
	F("description", "Small Text", "Description"),
], P_CONFIG, autoname="field:code", title_field="title", show_title_field_in_link=1)

doctype("Oman VAT Rule", [
	F("rule_code", "Data", "Rule Code", reqd=1, unique=1, in_list_view=1),
	F("title", "Data", "Title", reqd=1, in_list_view=1),
	F("rule_type", "Select", "Rule Type", "Validation\nReverse Charge\nPlace of Supply\nEvidence\nTiming\nThreshold", default="Validation", in_standard_filter=1),
	F("check_key", "Select", "Check", CHECK_KEYS),
	CB("cb1"),
	F("status", "Select", "Status", "Draft\nApproved\nRetired", default="Draft", in_list_view=1, in_standard_filter=1),
	F("enabled", "Check", "Enabled", default="1"),
	F("severity", "Select", "Severity", "Error\nWarning\nInfo", default="Error", in_list_view=1),
	F("applies_to", "Select", "Applies To", DIRECTION, default="Both"),
	F("priority", "Int", "Priority", default="0"),
	SB("sb_legal", "Legal Basis & Validity"),
	F("effective_from", "Date", "Effective From", reqd=1),
	F("effective_to", "Date", "Effective To"),
	CB("cb2"),
	F("ruleset_version", "Data", "Rule-set Version"),
	F("legal_reference", "Data", "Legal Reference"),
	SB("sb_cond", "Conditions"),
	F("company", "Link", "Company", "Company"),
	F("treatment", "Link", "Treatment", "Oman VAT Treatment"),
	F("vat_code", "Link", "VAT Code", "Oman VAT Code"),
	F("supply_category", "Select", "Supply Category", "Any\nGoods\nServices", default="Any"),
	CB("cb3"),
	F("party_country_condition", "Select", "Party Country", "Any\nOman\nNot Oman\nGCC\nNon-GCC", default="Any"),
	F("party_registration_condition", "Select", "Party Registration", "Any\nRegistered\nUnregistered", default="Any"),
	F("item_group", "Link", "Item Group", "Item Group"),
	F("account", "Link", "Account", "Account"),
	SB("sb_action", "Parameters & Action"),
	F("numeric_value", "Float", "Numeric Parameter"),
	F("text_value", "Data", "Text Parameter"),
	CB("cb4"),
	F("action_treatment", "Link", "Set Treatment", "Oman VAT Treatment"),
	F("action_recovery_profile", "Link", "Set Recovery Profile", "Oman VAT Recovery Profile"),
	F("message", "Small Text", "Message"),
	SB("sb_appr", "Approval"),
	RO(F("approved_by", "Link", "Approved By", "User")),
	RO(F("approved_on", "Datetime", "Approved On")),
	F("notes", "Small Text", "Notes"),
], P_CONFIG, autoname="field:rule_code", title_field="title", track_changes=1)

doctype("Oman VAT Rate History", [
	F("treatment", "Link", "Treatment", "Oman VAT Treatment", reqd=1, in_list_view=1, in_standard_filter=1),
	F("vat_code", "Link", "VAT Code (optional override)", "Oman VAT Code"),
	F("rate", "Percent", "Rate", reqd=1, in_list_view=1),
	CB("cb1"),
	F("effective_from", "Date", "Effective From", reqd=1, in_list_view=1),
	F("effective_to", "Date", "Effective To", in_list_view=1),
	F("ruleset_version", "Data", "Rule-set Version"),
	F("legal_reference", "Data", "Legal Reference"),
	F("notes", "Small Text", "Notes"),
], P_CONFIG, autoname="ORH-.#####", track_changes=1)

doctype("Oman VAT Account Mapping", [
	F("company", "Link", "Company", "Company", reqd=1, in_list_view=1),
	F("vat_registration", "Link", "VAT Registration", "Oman VAT Registration"),
	F("disabled", "Check", "Disabled"),
	SB("sb_out", "Output / Input VAT"),
	F("output_vat_account", "Link", "Output VAT Account", "Account", reqd=1),
	F("input_vat_account", "Link", "Input VAT Account", "Account", reqd=1),
	CB("cb1"),
	F("rcm_output_vat_account", "Link", "Reverse Charge Output VAT Account", "Account"),
	F("rcm_input_vat_account", "Link", "Reverse Charge Input VAT Account", "Account"),
	SB("sb_imp", "Imports"),
	F("import_vat_account", "Link", "Import VAT (Input) Account", "Account"),
	F("import_vat_payable_account", "Link", "Postponed Import VAT Payable Account", "Account"),
	CB("cb2"),
	F("customs_vat_clearing_account", "Link", "Customs VAT Clearing Account", "Account"),
	SB("sb_other", "Recovery & Adjustments"),
	F("nonrecoverable_vat_account", "Link", "Non-Recoverable VAT Account", "Account"),
	CB("cb3"),
	F("vat_adjustment_account", "Link", "VAT Adjustment Account", "Account"),
], P_CONFIG, autoname="OVAM-.####", title_field="company")

doctype("Oman VAT Recovery Profile", [
	F("profile_name", "Data", "Profile Name", reqd=1, unique=1, in_list_view=1),
	F("method", "Select", "Method", "Full Recovery\nBlocked\nFixed Percentage\nBusiness Use\nStandard Apportionment\nSpecial Method", reqd=1, in_list_view=1),
	F("recovery_percentage", "Percent", "Recovery %", depends_on="eval:['Fixed Percentage','Business Use','Special Method'].includes(doc.method)"),
	F("provisional_percentage", "Percent", "Provisional Recovery %", depends_on="eval:doc.method=='Standard Apportionment'"),
	CB("cb1"),
	F("status", "Select", "Status", "Draft\nApproved\nRetired", default="Draft", in_list_view=1),
	F("disabled", "Check", "Disabled"),
	F("company", "Link", "Company", "Company"),
	F("effective_from", "Date", "Effective From"),
	F("effective_to", "Date", "Effective To"),
	SB("sb_basis", "Basis"),
	F("legal_basis", "Small Text", "Legal Basis / Method Approval"),
	RO(F("approved_by", "Link", "Approved By", "User")),
	RO(F("approved_on", "Datetime", "Approved On")),
	F("notes", "Small Text", "Notes"),
], P_CONFIG, autoname="field:profile_name", track_changes=1)

doctype("Oman VAT Recovery Rule", [
	F("recovery_profile", "Link", "Recovery Profile", "Oman VAT Recovery Profile", reqd=1, in_list_view=1),
	F("enabled", "Check", "Enabled", default="1"),
	F("priority", "Int", "Priority", default="0", in_list_view=1),
	F("description", "Data", "Description", in_list_view=1),
	CB("cb1"),
	F("effective_from", "Date", "Effective From", reqd=1),
	F("effective_to", "Date", "Effective To"),
	SB("sb_match", "Match Conditions (blank = any)"),
	F("company", "Link", "Company", "Company"),
	F("expense_account", "Link", "Expense Account", "Account"),
	F("cost_center", "Link", "Cost Center", "Cost Center"),
	CB("cb2"),
	F("item_code", "Link", "Item", "Item"),
	F("item_group", "Link", "Item Group", "Item Group"),
	F("supplier", "Link", "Supplier", "Supplier"),
	F("treatment", "Link", "Treatment", "Oman VAT Treatment"),
], P_CONFIG, autoname="ORR-.#####", track_changes=1)

doctype("Oman VAT Evidence Type", [
	F("evidence_type", "Data", "Evidence Type", reqd=1, unique=1, in_list_view=1),
	F("applies_to", "Select", "Applies To", "Zero-rated Supply\nExport\nImport\nInput Claim\nBad Debt\nOther", in_list_view=1),
	F("retention_years", "Int", "Retention (years)", default="10"),
	F("description", "Small Text", "Description"),
], P_CONFIG, autoname="field:evidence_type")

doctype("Oman VAT Return Box", [
	F("box_code", "Data", "Box Code", reqd=1, unique=1, in_list_view=1),
	F("label", "Data", "Label", reqd=1, in_list_view=1),
	F("label_ar", "Data", "Label (Arabic)"),
	F("section", "Data", "Section", in_list_view=1),
	CB("cb1"),
	F("value_type", "Select", "Value Type", "Taxable Value\nVAT\nTotal", default="VAT"),
	F("sequence", "Int", "Sequence", default="0"),
	F("formula", "Data", "Formula (box codes joined by + / -)"),
	F("enabled", "Check", "Enabled", default="1"),
	F("effective_from", "Date", "Effective From"),
	F("effective_to", "Date", "Effective To"),
	F("notes", "Small Text", "Notes"),
], P_CONFIG, autoname="field:box_code", title_field="label", sort_field="sequence", sort_order="ASC")

# =========================== B. Transactions ===========================

doctype("Oman VAT Transaction Detail", [
	F("source_row", "Data", "Source Row"),
	F("item_code", "Link", "Item", "Item", in_list_view=1),
	F("treatment", "Link", "Treatment", "Oman VAT Treatment", in_list_view=1),
	F("vat_code", "Link", "VAT Code", "Oman VAT Code"),
	F("rate", "Percent", "Rate", in_list_view=1),
	F("rate_reference", "Link", "Rate Reference", "Oman VAT Rate History"),
	F("supply_category", "Data", "Supply Category"),
	CB("cb1"),
	MONEY("taxable_amount", "Taxable (OMR)", in_list_view=1),
	MONEY("output_vat", "Output VAT", in_list_view=1),
	MONEY("input_vat", "Input VAT", in_list_view=1),
	F("recovery_percentage", "Percent", "Recovery %"),
	MONEY("recoverable_vat", "Recoverable VAT"),
	MONEY("nonrecoverable_vat", "Non-recoverable VAT"),
	MONEY("rcm_output_vat", "RCM Output VAT"),
	F("reverse_charge", "Check", "Reverse Charge"),
	F("is_import", "Check", "Import"),
	F("recovery_status", "Data", "Recovery Status"),
	F("recovery_profile", "Link", "Recovery Profile", "Oman VAT Recovery Profile"),
	F("return_boxes", "Small Text", "Return Boxes"),
], [], istable=1)

doctype("Oman VAT Transaction", [
	F("source_doctype", "Link", "Source DocType", "DocType", read_only=1, in_standard_filter=1),
	F("source_name", "Dynamic Link", "Source Document", "source_doctype", read_only=1, in_list_view=1, search_index=1),
	F("company", "Link", "Company", "Company", read_only=1, in_standard_filter=1),
	F("vat_registration", "Link", "VAT Registration", "Oman VAT Registration", read_only=1),
	F("direction", "Select", "Direction", "Sales\nPurchase", read_only=1, in_list_view=1),
	CB("cb1"),
	F("tax_point_date", "Date", "Tax Point", read_only=1, in_list_view=1, search_index=1),
	F("posting_date", "Date", "Posting Date", read_only=1),
	F("vat_period", "Link", "VAT Period", "Oman VAT Period", read_only=1, in_standard_filter=1, search_index=1),
	F("status", "Select", "Status", "Active\nCancelled", read_only=1, in_list_view=1),
	F("validation_status", "Data", "Validation Status", read_only=1),
	F("vat_return", "Link", "Included in VAT Return", "Oman VAT Return", read_only=1),
	SB("sb_party", "Party"),
	F("party_type", "Link", "Party Type", "DocType", read_only=1),
	F("party", "Dynamic Link", "Party", "party_type", read_only=1),
	CB("cb2"),
	F("party_vrn", "Data", "Party VAT No.", read_only=1),
	F("party_country", "Link", "Party Country", "Country", read_only=1),
	SB("sb_adj", "Adjustment / Currency"),
	F("is_adjustment", "Check", "Adjustment", read_only=1),
	F("original_doctype", "Link", "Original DocType", "DocType", read_only=1),
	F("original_name", "Dynamic Link", "Original Document", "original_doctype", read_only=1),
	F("adjustment_reason", "Data", "Adjustment Reason", read_only=1),
	CB("cb3"),
	F("currency", "Link", "Document Currency", "Currency", read_only=1),
	F("conversion_rate", "Float", "Conversion Rate", read_only=1, precision="9"),
	F("ruleset_version", "Data", "Rule-set Version", read_only=1),
	SB("sb_tot", "Totals (OMR)"),
	RO(MONEY("total_taxable", "Taxable")),
	RO(MONEY("total_output_vat", "Output VAT")),
	RO(MONEY("total_input_vat", "Input VAT")),
	CB("cb4"),
	RO(MONEY("total_recoverable", "Recoverable")),
	RO(MONEY("total_nonrecoverable", "Non-recoverable")),
	RO(MONEY("total_rcm_output", "RCM Output VAT")),
	SB("sb_lines", "Lines"),
	F("details", "Table", "Details", "Oman VAT Transaction Detail", read_only=1),
	F("content_hash", "Data", "Content Hash (SHA-256)", read_only=1),
], P_READONLY, autoname="OVT-.YYYY.-.#######", in_create=1, title_field="source_name")

doctype("Oman VAT Validation Log", [
	F("reference_doctype", "Link", "Reference DocType", "DocType", read_only=1),
	F("reference_name", "Dynamic Link", "Reference", "reference_doctype", read_only=1, in_list_view=1, search_index=1),
	F("company", "Link", "Company", "Company", read_only=1),
	F("vat_registration", "Link", "VAT Registration", "Oman VAT Registration", read_only=1),
	CB("cb1"),
	F("status", "Select", "Status", "Passed\nWarnings\nFailed", read_only=1, in_list_view=1, in_standard_filter=1),
	F("error_count", "Int", "Errors", read_only=1, in_list_view=1),
	F("warning_count", "Int", "Warnings", read_only=1),
	F("tax_point_date", "Date", "Tax Point", read_only=1),
	F("ruleset_version", "Data", "Rule-set Version", read_only=1),
	SB("sb_issues", "Issues"),
	F("issues", "Code", "Issues (JSON)", options="JSON", read_only=1),
], P_READONLY, autoname="OVL-.YYYY.-.#######", in_create=1)

doctype("Oman VAT Recovery Allocation Item", [
	F("invoice_item", "Data", "Invoice Row"),
	F("item_code", "Link", "Item", "Item", in_list_view=1),
	MONEY("input_vat", "Input VAT", in_list_view=1),
	F("recovery_percentage", "Percent", "Recovery %", in_list_view=1),
	MONEY("recoverable_vat", "Recoverable"),
	MONEY("nonrecoverable_vat", "Non-recoverable", in_list_view=1),
	F("debit_account", "Link", "Debit Account", "Account", in_list_view=1),
	F("cost_center", "Link", "Cost Center", "Cost Center"),
	F("recovery_profile", "Link", "Recovery Profile", "Oman VAT Recovery Profile"),
], [], istable=1)

doctype("Oman VAT Recovery Allocation", [
	F("company", "Link", "Company", "Company", reqd=1, read_only=1),
	F("vat_registration", "Link", "VAT Registration", "Oman VAT Registration", read_only=1),
	F("purchase_invoice", "Link", "Purchase Invoice", "Purchase Invoice", reqd=1, read_only=1, in_list_view=1, search_index=1),
	CB("cb1"),
	F("posting_date", "Date", "Posting Date", read_only=1),
	F("tax_point_date", "Date", "Tax Point", read_only=1),
	F("credit_account", "Link", "Input VAT Account (credited)", "Account", read_only=1),
	F("journal_entry", "Link", "Journal Entry", "Journal Entry", read_only=1, allow_on_submit=1, no_copy=1),
	RO(MONEY("total_nonrecoverable", "Total Non-recoverable VAT")),
	SB("sb_items", "Allocation"),
	F("items", "Table", "Items", "Oman VAT Recovery Allocation Item", read_only=1),
	F("amended_from", "Link", "Amended From", "Oman VAT Recovery Allocation", read_only=1, no_copy=1, print_hide=1),
], P_SYSTEM_SUBMIT, autoname="ORA-.YYYY.-.#####", is_submittable=1, in_create=1)

doctype("Oman VAT Recovery Adjustment", [
	F("company", "Link", "Company", "Company", reqd=1),
	F("vat_registration", "Link", "VAT Registration", "Oman VAT Registration", reqd=1),
	F("recovery_profile", "Link", "Apportionment Profile", "Oman VAT Recovery Profile", reqd=1),
	F("posting_date", "Date", "Posting Date", reqd=1, default="Today"),
	CB("cb1"),
	F("period_from", "Date", "Period From", reqd=1),
	F("period_to", "Date", "Period To", reqd=1),
	F("update_profile_provisional", "Check", "Update Profile's Provisional % on Submit", default="1"),
	SB("sb_calc", "Annual Apportionment"),
	RO(MONEY("taxable_supplies", "Taxable Supplies (standard + zero rated)")),
	RO(MONEY("exempt_supplies", "Exempt Supplies")),
	RO(F("actual_ratio", "Percent", "Actual Recovery Ratio")),
	RO(F("provisional_ratio", "Percent", "Provisional Ratio Used")),
	CB("cb2"),
	RO(MONEY("residual_input_vat", "Residual Input VAT")),
	RO(MONEY("provisionally_recovered", "Recovered Provisionally")),
	RO(MONEY("actually_recoverable", "Recoverable at Actual Ratio")),
	RO(MONEY("adjustment_amount", "Adjustment (+ further recovery / − repayment)")),
	SB("sb_post", "Posting"),
	F("post_journal_entry", "Check", "Post Journal Entry", default="1"),
	F("contra_account", "Link", "Contra Account (default: Non-Recoverable VAT)", "Account"),
	F("journal_entry", "Link", "Journal Entry", "Journal Entry", read_only=1, no_copy=1),
	F("notes", "Small Text", "Notes"),
	F("amended_from", "Link", "Amended From", "Oman VAT Recovery Adjustment", read_only=1, no_copy=1, print_hide=1),
], P_SUBMIT, autoname="ORADJ-.YYYY.-.####", is_submittable=1)

doctype("Oman Reverse Charge Entry Item", [
	F("invoice_item", "Data", "Invoice Row"),
	F("item_code", "Link", "Item", "Item", in_list_view=1),
	F("treatment", "Link", "Treatment", "Oman VAT Treatment"),
	MONEY("taxable_amount", "Taxable (OMR)", in_list_view=1),
	F("vat_rate", "Percent", "Rate"),
	MONEY("output_vat", "Self-assessed Output VAT", in_list_view=1),
	F("recovery_percentage", "Percent", "Recovery %"),
	MONEY("recoverable_vat", "Recoverable Input VAT", in_list_view=1),
	MONEY("nonrecoverable_vat", "Non-recoverable"),
	F("nonrecoverable_account", "Link", "Non-recoverable Account", "Account"),
	F("cost_center", "Link", "Cost Center", "Cost Center"),
], [], istable=1)

doctype("Oman Reverse Charge Entry", [
	F("company", "Link", "Company", "Company", reqd=1, read_only=1),
	F("vat_registration", "Link", "VAT Registration", "Oman VAT Registration", read_only=1),
	F("purchase_invoice", "Link", "Purchase Invoice", "Purchase Invoice", reqd=1, read_only=1, in_list_view=1, search_index=1),
	F("supplier", "Link", "Supplier", "Supplier", read_only=1, in_list_view=1),
	F("supplier_country", "Link", "Supplier Country", "Country", read_only=1),
	CB("cb1"),
	F("posting_date", "Date", "Posting Date", read_only=1),
	F("tax_point_date", "Date", "Tax Point", read_only=1),
	F("journal_entry", "Link", "Journal Entry", "Journal Entry", read_only=1, allow_on_submit=1, no_copy=1),
	RO(MONEY("total_output_vat", "Total Self-assessed VAT")),
	RO(MONEY("total_recoverable", "Total Recoverable")),
	SB("sb_items", "Lines"),
	F("items", "Table", "Items", "Oman Reverse Charge Entry Item", read_only=1),
	F("amended_from", "Link", "Amended From", "Oman Reverse Charge Entry", read_only=1, no_copy=1, print_hide=1),
], P_SYSTEM_SUBMIT, autoname="ORCE-.YYYY.-.#####", is_submittable=1, in_create=1)

doctype("Oman Import Declaration Invoice", [
	F("purchase_invoice", "Link", "Purchase Invoice", "Purchase Invoice", reqd=1, in_list_view=1),
	F("supplier", "Link", "Supplier", "Supplier", fetch_from="purchase_invoice.supplier", read_only=1, in_list_view=1),
	F("amount", "Currency", "Invoice Amount", fetch_from="purchase_invoice.base_net_total", read_only=1, in_list_view=1),
], [], istable=1, editable_grid=1)

doctype("Oman Import Declaration", [
	F("company", "Link", "Company", "Company", reqd=1),
	F("vat_registration", "Link", "VAT Registration (Importer)", "Oman VAT Registration", reqd=1),
	F("declaration_number", "Data", "Customs Declaration (Bayan) No.", reqd=1, in_list_view=1, search_index=1, bold=1),
	F("declaration_date", "Date", "Declaration Date", reqd=1, in_list_view=1),
	CB("cb1"),
	F("clearance_date", "Date", "Customs Clearance Date"),
	F("customs_office", "Data", "Customs Office / Port"),
	F("importer_vrn", "Data", "Importer VAT No.", fetch_from="vat_registration.vatin", read_only=1),
	F("supplier", "Link", "Foreign Supplier", "Supplier"),
	F("country_of_origin", "Link", "Country of Origin", "Country"),
	SB("sb_vat", "Customs Valuation & Import VAT (OMR)"),
	MONEY("customs_value", "Customs Value", reqd=1),
	MONEY("customs_duty", "Customs Duty"),
	MONEY("other_charges", "Other Charges in VAT Base"),
	RO(MONEY("vat_base", "Import VAT Base")),
	CB("cb2"),
	RO(F("vat_rate", "Percent", "Rate")),
	F("rate_reference", "Link", "Rate Reference", "Oman VAT Rate History", read_only=1),
	RO(MONEY("computed_vat", "Computed VAT")),
	MONEY("import_vat", "Customs-assessed Import VAT", description="As shown on the customs declaration. Defaults to the computed amount."),
	RO(MONEY("vat_difference", "Difference")),
	SB("sb_rec", "Payment & Recovery"),
	F("payment_method", "Select", "Import VAT Payment", "Paid at Customs\nDeferred via VAT Return", default="Paid at Customs", reqd=1),
	F("recovery_percentage", "Percent", "Recovery %", default="100"),
	CB("cb3"),
	RO(MONEY("recoverable_vat", "Recoverable")),
	RO(MONEY("nonrecoverable_vat", "Non-recoverable")),
	F("post_journal_entry", "Check", "Post Journal Entry", default="1"),
	F("journal_entry", "Link", "Journal Entry", "Journal Entry", read_only=1, no_copy=1, allow_on_submit=1),
	SB("sb_inv", "Linked Purchase Invoices"),
	F("invoices", "Table", "Purchase Invoices", "Oman Import Declaration Invoice"),
	F("attachment", "Attach", "Customs Document"),
	F("notes", "Small Text", "Notes"),
	F("amended_from", "Link", "Amended From", "Oman Import Declaration", read_only=1, no_copy=1, print_hide=1),
], P_SUBMIT, autoname="OID-.YYYY.-.#####", is_submittable=1, title_field="declaration_number")

doctype("Oman VAT Adjustment", [
	F("company", "Link", "Company", "Company", reqd=1),
	F("vat_registration", "Link", "VAT Registration", "Oman VAT Registration", reqd=1),
	F("posting_date", "Date", "Posting Date (reporting period)", reqd=1, default="Today"),
	F("vat_period", "Link", "VAT Period", "Oman VAT Period", read_only=1),
	CB("cb1"),
	F("adjustment_type", "Select", "Adjustment Type",
		"Sales Credit Note\nSales Debit Note\nPurchase Credit Note\nPurchase Debit Note\nBad Debt Relief\nChange in Consideration\nIncorrect VAT Treatment\nPrevious Period Correction\nInput Recovery Change\nManual Statutory Adjustment",
		reqd=1, in_list_view=1),
	F("direction", "Select", "Direction", "Output\nInput", in_list_view=1),
	SB("sb_orig", "Original Transaction"),
	F("original_doctype", "Link", "Original DocType", "DocType"),
	F("original_name", "Dynamic Link", "Original Document", "original_doctype"),
	F("original_tax_point", "Date", "Original Tax Point", read_only=1),
	CB("cb2"),
	F("original_treatment", "Link", "Original Treatment", "Oman VAT Treatment"),
	F("original_period", "Link", "Original Period", "Oman VAT Period", read_only=1),
	F("treatment", "Link", "Corrected Treatment", "Oman VAT Treatment"),
	F("vat_code", "Link", "VAT Code (return boxes)", "Oman VAT Code"),
	SB("sb_amt", "Amounts (OMR; positive increases the liability/credit)"),
	MONEY("taxable_adjustment", "Taxable Adjustment"),
	MONEY("vat_adjustment", "VAT Adjustment", reqd=1, in_list_view=1),
	CB("cb3"),
	F("reason", "Small Text", "Reason", reqd=1),
	F("evidence", "Link", "Evidence", "Oman VAT Evidence"),
	SB("sb_post", "Posting"),
	F("post_journal_entry", "Check", "Post Journal Entry"),
	F("contra_account", "Link", "Contra Account", "Account"),
	F("journal_entry", "Link", "Journal Entry", "Journal Entry", read_only=1, no_copy=1, allow_on_submit=1),
	RO(F("approved_by", "Link", "Approved By", "User")),
	F("amended_from", "Link", "Amended From", "Oman VAT Adjustment", read_only=1, no_copy=1, print_hide=1),
], P_SUBMIT, autoname="OVA-.YYYY.-.#####", is_submittable=1)

doctype("Oman VAT Evidence", [
	F("evidence_type", "Link", "Evidence Type", "Oman VAT Evidence Type", reqd=1, in_list_view=1),
	F("reference_doctype", "Link", "Reference DocType", "DocType", reqd=1),
	F("reference_name", "Dynamic Link", "Reference", "reference_doctype", reqd=1, in_list_view=1, search_index=1),
	F("company", "Link", "Company", "Company"),
	CB("cb1"),
	F("status", "Select", "Status", "Pending\nReceived\nVerified\nRejected", default="Received", in_list_view=1),
	F("document_number", "Data", "Document Number"),
	F("document_date", "Date", "Document Date"),
	F("issuing_authority", "Data", "Issuing Authority / Carrier"),
	SB("sb_file", "Document"),
	F("attachment", "Attach", "Attachment"),
	F("expiry_date", "Date", "Expiry / Retention Until"),
	CB("cb2"),
	RO(F("verified_by", "Link", "Verified By", "User")),
	RO(F("verified_on", "Datetime", "Verified On")),
	F("notes", "Small Text", "Notes"),
], P_SUBMIT[:4] + [perm("Accounts User", w=1, c=1), perm("Auditor")], autoname="OVE-.YYYY.-.#####", track_changes=1)

# =========================== C. Reporting ===========================

doctype("Oman VAT Return Box Total", [
	F("box_code", "Link", "Box", "Oman VAT Return Box", in_list_view=1),
	F("label", "Data", "Label", in_list_view=1),
	F("section", "Data", "Section"),
	F("value_type", "Data", "Type"),
	MONEY("amount", "Amount (OMR)", in_list_view=1),
], [], istable=1)

doctype("Oman VAT Return Detail", [
	F("vat_transaction", "Link", "VAT Transaction", "Oman VAT Transaction", in_list_view=1),
	F("transaction_detail", "Data", "Detail Row"),
	F("source_doctype", "Link", "Source DocType", "DocType"),
	F("source_name", "Dynamic Link", "Source", "source_doctype", in_list_view=1),
	F("tax_point_date", "Date", "Tax Point"),
	F("party", "Data", "Party"),
	F("treatment", "Link", "Treatment", "Oman VAT Treatment"),
	F("vat_code", "Link", "VAT Code", "Oman VAT Code"),
	F("box_code", "Link", "Box", "Oman VAT Return Box", in_list_view=1),
	MONEY("amount", "Amount (OMR)", in_list_view=1),
	F("is_adjustment", "Check", "Adjustment"),
], [], istable=1)

doctype("Oman VAT Return", [
	F("company", "Link", "Company", "Company", reqd=1, in_standard_filter=1),
	F("vat_registration", "Link", "VAT Registration", "Oman VAT Registration", reqd=1),
	F("vat_period", "Link", "VAT Period", "Oman VAT Period", reqd=1, in_list_view=1),
	F("from_date", "Date", "From", fetch_from="vat_period.from_date", read_only=1),
	F("to_date", "Date", "To", fetch_from="vat_period.to_date", read_only=1),
	CB("cb1"),
	F("status", "Select", "Status", "Open\nValidation\nReviewed\nFinalized\nFiled\nLocked", default="Open",
		read_only=1, in_list_view=1, allow_on_submit=1, in_standard_filter=1),
	RO(F("prepared_by", "Link", "Prepared By", "User")),
	RO(F("reviewed_by", "Link", "Reviewed By", "User")),
	RO(F("reviewed_on", "Datetime", "Reviewed On")),
	RO(F("finalized_by", "Link", "Finalized By", "User", allow_on_submit=1)),
	RO(F("finalized_at", "Datetime", "Finalized At", allow_on_submit=1)),
	SB("sb_summary", "Summary (OMR)"),
	RO(MONEY("total_output_vat", "Total VAT Due", in_list_view=1)),
	RO(MONEY("total_input_vat", "Total Recoverable Input VAT")),
	RO(MONEY("net_vat", "Net VAT Payable / (Refundable)", bold=1, in_list_view=1)),
	CB("cb2"),
	RO(F("transaction_count", "Int", "Transactions")),
	RO(F("validation_errors", "Int", "Validation Errors")),
	RO(F("validation_warnings", "Int", "Validation Warnings")),
	F("last_validation_log", "Link", "Last Validation Log", "Oman VAT Validation Log", read_only=1),
	F("waive_warnings", "Check", "Warnings Reviewed and Accepted"),
	F("review_notes", "Small Text", "Review Notes"),
	TAB("tab_boxes", "Return Boxes"),
	F("box_totals", "Table", "Box Totals", "Oman VAT Return Box Total", read_only=1),
	TAB("tab_details", "Working Paper"),
	F("details", "Table", "Transaction Lines", "Oman VAT Return Detail", read_only=1),
	F("reconciliation_json", "Code", "GL Reconciliation", options="JSON", read_only=1),
	TAB("tab_filing", "Filing"),
	F("snapshot", "Link", "Frozen Snapshot", "Oman VAT Return Snapshot", read_only=1, allow_on_submit=1, no_copy=1),
	F("snapshot_hash", "Data", "Snapshot Hash", read_only=1, allow_on_submit=1, no_copy=1),
	F("filing_record", "Link", "Filing Record", "Oman VAT Filing Record", read_only=1, allow_on_submit=1, no_copy=1),
	CB("cb_f"),
	F("filing_reference", "Data", "OTA Filing Reference", allow_on_submit=1, read_only=1, no_copy=1),
	F("filing_date", "Date", "Filing Date", allow_on_submit=1, read_only=1, no_copy=1),
	F("acknowledgement_reference", "Data", "Acknowledgement", allow_on_submit=1, read_only=1, no_copy=1),
	F("payment_reference", "Data", "Payment Reference", allow_on_submit=1, read_only=1, no_copy=1),
	F("payment_date", "Date", "Payment Date", allow_on_submit=1, read_only=1, no_copy=1),
	F("amended_from", "Link", "Amended From", "Oman VAT Return", read_only=1, no_copy=1, print_hide=1),
], P_RETURN, autoname="OVRTN-.YYYY.-.####", is_submittable=1, track_changes=1, title_field="vat_period")

doctype("Oman VAT Return Snapshot", [
	F("vat_return", "Link", "VAT Return", "Oman VAT Return", read_only=1, in_list_view=1),
	F("company", "Link", "Company", "Company", read_only=1),
	F("vat_registration", "Link", "VAT Registration", "Oman VAT Registration", read_only=1),
	F("vat_period", "Link", "VAT Period", "Oman VAT Period", read_only=1, in_list_view=1),
	CB("cb1"),
	F("generated_by", "Link", "Generated By", "User", read_only=1),
	F("generated_at", "Datetime", "Generated At", read_only=1),
	F("ruleset_version", "Data", "Rule-set Version", read_only=1),
	RO(MONEY("net_vat", "Net VAT")),
	F("content_hash", "Data", "Content Hash (SHA-256)", read_only=1, in_list_view=1),
	SB("sb_json", "Frozen Content"),
	F("snapshot_json", "Code", "Snapshot", options="JSON", read_only=1),
], P_READONLY, autoname="OVRS-.YYYY.-.#####", in_create=1)

doctype("Oman VAT Period", [
	F("vat_registration", "Link", "VAT Registration", "Oman VAT Registration", reqd=1, in_list_view=1, in_standard_filter=1),
	F("company", "Link", "Company", "Company", fetch_from="vat_registration.company", read_only=1),
	F("from_date", "Date", "From", reqd=1, in_list_view=1),
	F("to_date", "Date", "To", reqd=1, in_list_view=1),
	CB("cb1"),
	F("status", "Select", "Status", "Open\nUnder Review\nFinalized\nFiled\nLocked", default="Open", in_list_view=1, read_only=1),
	F("due_date", "Date", "Return Due Date"),
	F("vat_return", "Link", "VAT Return", "Oman VAT Return", read_only=1),
	RO(F("locked_by", "Link", "Locked By", "User")),
	RO(F("locked_on", "Datetime", "Locked On")),
], P_CONFIG, autoname="format:{vat_registration}-{from_date}", sort_field="from_date")

doctype("Oman VAT Period Lock", [
	F("vat_period", "Link", "VAT Period", "Oman VAT Period", reqd=1, in_list_view=1),
	F("vat_registration", "Link", "VAT Registration", "Oman VAT Registration", fetch_from="vat_period.vat_registration", read_only=1),
	F("company", "Link", "Company", "Company", fetch_from="vat_period.company", read_only=1),
	CB("cb1"),
	F("lock_date", "Datetime", "Lock Date", read_only=1),
	RO(F("locked_by", "Link", "Locked By", "User")),
	F("lock_reason", "Small Text", "Lock Note", reqd=1),
	F("unlock_reason", "Small Text", "Reopen Reason (required to cancel)", allow_on_submit=1),
	F("amended_from", "Link", "Amended From", "Oman VAT Period Lock", read_only=1, no_copy=1, print_hide=1),
], [perm("System Manager", w=1, c=1, s=1, cancel=1), perm("Oman VAT Approver", w=1, c=1, s=1, cancel=1),
	perm("Oman VAT Manager"), perm("Auditor")], autoname="OVPL-.YYYY.-.####", is_submittable=1)

doctype("Oman VAT Reconciliation Item", [
	F("account", "Link", "Account", "Account", in_list_view=1),
	F("natural_side", "Data", "Side"),
	MONEY("register_amount", "VAT Register", in_list_view=1),
	MONEY("gl_amount", "General Ledger", in_list_view=1),
	MONEY("difference", "Difference", in_list_view=1),
	F("explanation", "Small Text", "Explanation", in_list_view=1),
], [], istable=1, editable_grid=1)

doctype("Oman VAT Reconciliation", [
	F("company", "Link", "Company", "Company", reqd=1),
	F("vat_registration", "Link", "VAT Registration", "Oman VAT Registration", reqd=1),
	F("vat_period", "Link", "VAT Period", "Oman VAT Period"),
	CB("cb1"),
	F("from_date", "Date", "From", reqd=1),
	F("to_date", "Date", "To", reqd=1),
	F("status", "Select", "Status", "Draft\nReconciled\nDifferences", default="Draft", read_only=1, in_list_view=1),
	RO(MONEY("total_difference", "Total Absolute Difference")),
	SB("sb_items", "Accounts"),
	F("items", "Table", "Accounts", "Oman VAT Reconciliation Item"),
	F("notes", "Small Text", "Notes"),
], P_CONFIG, autoname="OVREC-.YYYY.-.####")

doctype("Oman VAT Filing Record", [
	F("vat_return", "Link", "VAT Return", "Oman VAT Return", reqd=1, in_list_view=1),
	F("company", "Link", "Company", "Company", fetch_from="vat_return.company", read_only=1),
	F("vat_registration", "Link", "VAT Registration", "Oman VAT Registration", fetch_from="vat_return.vat_registration", read_only=1),
	F("vat_period", "Link", "VAT Period", "Oman VAT Period", fetch_from="vat_return.vat_period", read_only=1),
	RO(MONEY("net_vat", "Net VAT (from snapshot)")),
	CB("cb1"),
	F("filing_reference", "Data", "OTA Filing Reference", reqd=1),
	F("filing_date", "Date", "Filing Date", reqd=1, default="Today"),
	RO(F("filed_by", "Link", "Filed By", "User")),
	F("acknowledgement_reference", "Data", "Acknowledgement Reference"),
	F("acknowledgement_file", "Attach", "Acknowledgement"),
	SB("sb_pay", "Payment"),
	F("payment_reference", "Data", "Payment Reference"),
	F("payment_date", "Date", "Payment Date"),
	MONEY("payment_amount", "Payment Amount"),
	F("notes", "Small Text", "Notes"),
], P_RETURN[:4] + [perm("Auditor")], autoname="OVFR-.YYYY.-.####", track_changes=1)

# =========================== D. Fawtara ===========================

doctype("Oman Fawtara Settings", [
	TAB("tab_general", "General"),
	F("enabled", "Check", "Enable Fawtara Integration"),
	F("default_provider", "Link", "Default Service Provider", "Oman Fawtara Provider"),
	F("submit_immediately", "Check", "Queue Submission Immediately on Invoice Submit", default="1"),
	F("block_on_local_validation_error", "Check", "Block Invoice Submit on Local E-invoice Errors", default="1"),
	CB("cb_g"),
	F("include_b2c", "Check", "E-invoice B2C", default="1"),
	F("include_b2g", "Check", "E-invoice B2G", default="1"),
	F("skip_out_of_scope_only", "Check", "Skip Documents with only Out-of-scope Lines", default="1"),
	SB("sb_mandate", "Mandate (Decision No. 189/2026)",
		description="Verified baseline: 1 April 2027 where annual supplies exceed OMR 5 million; 1 October 2027 otherwise. Confirm the threshold reference periods against the OTA FAQ in force."),
	F("phase_1_date", "Date", "Phase 1 Date (above threshold)", default="2027-04-01"),
	F("phase_2_date", "Date", "Phase 2 Date (at/below threshold)", default="2027-10-01"),
	F("mandate_threshold_omr", "Float", "Threshold (OMR)", default="5000000", precision="3"),
	CB("cb_m"),
	F("threshold_period_start", "Date", "Threshold Reference Period Start", default="2026-04-01"),
	F("threshold_period_end", "Date", "Threshold Reference Period End", default="2027-03-31"),
	F("legal_source_notes", "Small Text", "Legal Source Notes"),
	TAB("tab_format", "XML Format"),
	F("customization_id", "Data", "CustomizationID", default="urn:peppol:pint:billing-1@om-1",
		description="Confirm against the published PINT-OM specification before go-live."),
	F("profile_id", "Data", "ProfileID", default="urn:peppol:bis:billing"),
	F("profile_execution_id", "Data", "ProfileExecutionID"),
	F("endpoint_scheme", "Data", "Endpoint (EAS) Scheme ID", description="Electronic address scheme assigned for Oman participants."),
	F("cr_scheme_id", "Data", "Commercial Registration Scheme ID"),
	CB("cb_x"),
	F("require_endpoint", "Check", "Require Electronic Addresses", default="1"),
	F("include_line_tax_amount", "Check", "Include Line VAT Amount"),
	F("include_line_description", "Check", "Include Line Description"),
	F("include_ubl_version", "Check", "Include UBLVersionID"),
	F("use_credit_note_root", "Check", "Use UBL CreditNote Root for Credit Notes", default="1"),
	F("use_transaction_flags", "Check", "Encode Transaction Flags in Type Code 'name'"),
	F("transaction_flag_order", "Data", "Transaction Flag Order", default="b2b,b2c,b2g,self_billing,reverse_charge,export,import",
		depends_on="use_transaction_flags"),
	F("default_payment_means_code", "Data", "Default Payment Means Code (UNCL4461)", default="30"),
	F("default_adjustment_reason_code", "Data", "Default Credit Note Reason Code"),
	F("local_tolerance", "Float", "Local Arithmetic Tolerance", default="0.01", precision="3"),
	F("xsd_file", "Attach", "XSD Schema (optional, for local validation)"),
	TAB("tab_queue", "Queue"),
	F("max_attempts", "Int", "Max Transient Retries", default="8"),
	F("retry_base_seconds", "Int", "Retry Base Delay (seconds)", default="60"),
	F("batch_size", "Int", "Scheduler Batch Size", default="200"),
	CB("cb_q"),
	F("new_uuid_on_resubmit", "Check", "New UUID on Authorised Resubmission", default="1"),
	F("retention_years", "Int", "Archive Retention (years)", default="10"),
], P_F_SETTINGS, issingle=1)

doctype("Oman Fawtara Provider Header", [
	F("header", "Data", "Header", reqd=1, in_list_view=1),
	F("value", "Data", "Value", in_list_view=1),
], [], istable=1, editable_grid=1)

doctype("Oman Fawtara Provider", [
	F("provider_name", "Data", "Provider Name", reqd=1, unique=1, in_list_view=1),
	F("adapter", "Data", "Adapter", reqd=1, in_list_view=1, description="Sandbox (Simulated), Generic REST, or an adapter registered via hooks."),
	F("enabled", "Check", "Enabled", default="1"),
	F("environment", "Select", "Environment", "Sandbox\nProduction", default="Sandbox", in_list_view=1),
	CB("cb1"),
	F("accreditation_number", "Data", "OTA Accreditation No."),
	RO(F("last_check_at", "Datetime", "Last Connectivity Check")),
	RO(F("last_check_ok", "Check", "Last Check OK")),
	RO(F("last_check_message", "Data", "Last Check Message")),
	SB("sb_sandbox", "Sandbox Behaviour", depends_on="eval:doc.adapter=='Sandbox (Simulated)'"),
	F("sandbox_behaviour", "Select", "Simulated Outcome", "Accept\nAccept, OTA Pending\nReject\nTransient Failure then Accept", default="Accept"),
	F("sandbox_failures", "Int", "Simulated Failures before Accept", default="1"),
	TAB("tab_conn", "Connection"),
	F("base_url", "Data", "Base URL"),
	F("submit_path", "Data", "Submit Path", default="/invoices"),
	F("status_path", "Data", "Status Path", default="/invoices/{reference}"),
	F("ping_path", "Data", "Health-check Path", default="/health"),
	F("list_path", "Data", "List Path (reconciliation)"),
	CB("cb_c"),
	F("timeout_seconds", "Int", "Timeout (s)", default="30"),
	F("verify_tls", "Check", "Verify TLS", default="1"),
	F("client_certificate", "Link", "Client Certificate (mTLS)", "Oman Fawtara Certificate"),
	F("idempotency_header", "Data", "Idempotency Header", default="Idempotency-Key"),
	SB("sb_auth", "Authentication"),
	F("auth_type", "Select", "Auth Type", "None\nAPI Key Header\nBearer Token\nBasic\nOAuth2 Client Credentials", default="API Key Header"),
	F("api_key_header", "Data", "API Key Header", default="X-API-Key"),
	F("api_key", "Password", "API Key / Token"),
	F("username", "Data", "Username"),
	F("password", "Password", "Password"),
	CB("cb_a"),
	F("token_url", "Data", "Token URL"),
	F("client_id", "Data", "Client ID"),
	F("client_secret", "Password", "Client Secret"),
	F("scope", "Data", "Scope"),
	F("extra_headers", "Table", "Extra Headers", "Oman Fawtara Provider Header"),
	TAB("tab_payload", "Payload & Response Mapping"),
	F("payload_format", "Select", "Payload Format", "JSON (base64 XML)\nRaw XML", default="JSON (base64 XML)"),
	F("payload_uuid_key", "Data", "JSON key: UUID", default="uuid"),
	F("payload_number_key", "Data", "JSON key: Invoice Number", default="invoiceNumber"),
	F("payload_type_key", "Data", "JSON key: Document Type", default="documentType"),
	F("payload_xml_key", "Data", "JSON key: XML (base64)", default="invoice"),
	CB("cb_p"),
	F("resp_status_path", "Data", "Response: Status Path", default="status"),
	F("accepted_values", "Data", "Accepted Values", default="ACCEPTED,CLEARED,REPORTED"),
	F("pending_values", "Data", "Pending Values", default="PENDING,PROCESSING,QUEUED"),
	F("rejected_values", "Data", "Rejected Values", default="REJECTED,INVALID"),
	F("resp_reference_path", "Data", "Response: Provider Reference Path", default="id"),
	F("resp_message_path", "Data", "Response: Message Path", default="message"),
	SB("sb_ota", "OTA / Delivery Mapping"),
	F("resp_ota_status_path", "Data", "Response: OTA Status Path", default="taxAuthority.status"),
	F("resp_ota_reference_path", "Data", "Response: OTA Reference Path", default="taxAuthority.reference"),
	F("ota_reported_values", "Data", "OTA Reported Values", default="REPORTED,SUBMITTED"),
	F("ota_acknowledged_values", "Data", "OTA Acknowledged Values", default="ACKNOWLEDGED,CLEARED"),
	F("ota_failed_values", "Data", "OTA Failed Values", default="FAILED,ERROR"),
	CB("cb_o"),
	F("resp_delivery_status_path", "Data", "Response: Buyer Delivery Path", default="delivery.status"),
	F("resp_errors_path", "Data", "Response: Errors Path", default="errors"),
	F("error_code_key", "Data", "Error Code Key", default="code"),
	F("error_message_key", "Data", "Error Message Key", default="message"),
	F("error_path_key", "Data", "Error Field Key", default="path"),
	F("resp_receipt_path", "Data", "Response: Receipt Path"),
	F("receipt_is_base64", "Check", "Receipt is Base64 (PDF)"),
	F("resp_stamped_xml_path", "Data", "Response: Stamped XML Path"),
	SB("sb_list", "Reconciliation Listing"),
	F("list_items_path", "Data", "List Items Path", default="items"),
	F("list_uuid_key", "Data", "List UUID Key", default="uuid"),
	F("list_number_key", "Data", "List Number Key", default="invoiceNumber"),
	F("list_status_key", "Data", "List Status Key", default="status"),
	F("notes", "Small Text", "Notes"),
], P_F_CONFIG, autoname="field:provider_name")

doctype("Oman Fawtara Submission", [
	F("reference_doctype", "Link", "Reference DocType", "DocType", read_only=1, in_standard_filter=1),
	F("reference_name", "Dynamic Link", "Reference Name", "reference_doctype", read_only=1, in_list_view=1, search_index=1),
	F("invoice_number", "Data", "Invoice Number", read_only=1),
	F("document_type", "Data", "Document Type", read_only=1, in_list_view=1),
	F("transaction_type", "Data", "Transaction Flags", read_only=1),
	CB("cb1"),
	F("status", "Select", "Status", "Draft\nPending\nProcessing\nAccepted\nRejected\nRetry\nCancelled", read_only=1,
		in_list_view=1, in_standard_filter=1, search_index=1),
	F("ota_status", "Select", "OTA Status", "Not Reported\nReported\nAcknowledged\nFailed", read_only=1, in_list_view=1),
	F("needs_attention", "Check", "Needs Attention", read_only=1, in_standard_filter=1),
	F("provider", "Link", "Provider", "Oman Fawtara Provider", read_only=1),
	F("company", "Link", "Company", "Company", read_only=1, in_standard_filter=1),
	F("vat_registration", "Link", "VAT Registration", "Oman VAT Registration", read_only=1),
	SB("sb_ids", "Identification"),
	F("document_uuid", "Data", "Document UUID", read_only=1, search_index=1),
	F("idempotency_key", "Data", "Idempotency Key", read_only=1, unique=1),
	F("issue_date", "Date", "Issue Date", read_only=1),
	CB("cb2"),
	F("xml_file", "Attach", "XML Payload", read_only=1),
	F("xml_hash", "Data", "XML SHA-256", read_only=1),
	F("receipt", "Link", "Receipt", "Oman Fawtara Receipt", read_only=1),
	SB("sb_timeline", "Provider (C2) and Authority (C5)"),
	F("attempt_count", "Int", "Attempt Count", read_only=1),
	F("submitted_at", "Datetime", "Submitted At", read_only=1),
	F("last_attempt_at", "Datetime", "Last Attempt", read_only=1),
	F("next_attempt_at", "Datetime", "Next Attempt", read_only=1),
	F("provider_reference", "Data", "Provider Reference", read_only=1),
	F("provider_accepted_at", "Datetime", "Accepted by Provider At", read_only=1),
	F("rejected_at", "Datetime", "Rejected At", read_only=1),
	CB("cb3"),
	F("ota_reference", "Data", "OTA Reference", read_only=1),
	F("ota_reported_at", "Datetime", "Reported to OTA At", read_only=1),
	F("ota_acknowledged_at", "Datetime", "Acknowledged by OTA At", read_only=1),
	F("buyer_delivery_status", "Data", "Buyer Delivery", read_only=1),
	F("buyer_delivered_at", "Datetime", "Delivered to Buyer At", read_only=1),
	SB("sb_err", "Errors & Corrections"),
	F("last_error", "Small Text", "Error Details", read_only=1),
	F("local_validation", "Code", "Local Validation", options="JSON", read_only=1),
	CB("cb4"),
	F("resubmission_reason", "Small Text", "Resubmission Reason", read_only=1),
	F("supersedes", "Link", "Supersedes", "Oman Fawtara Submission", read_only=1),
	F("superseded_by", "Link", "Superseded By", "Oman Fawtara Submission", read_only=1),
	SB("sb_payload", "Canonical Payload", collapsible=1),
	F("canonical_json", "Code", "Canonical Invoice", options="JSON", read_only=1),
], P_F_QUEUE, autoname="OFS-.YYYY.-.#######", in_create=1, title_field="reference_name")

doctype("Oman Fawtara Submission Log", [
	F("submission", "Link", "Submission", "Oman Fawtara Submission", read_only=1, in_list_view=1, search_index=1),
	F("attempt", "Int", "Attempt", read_only=1, in_list_view=1),
	F("outcome", "Data", "Outcome", read_only=1, in_list_view=1),
	F("http_status", "Int", "HTTP Status", read_only=1),
	F("duration_ms", "Int", "Duration (ms)", read_only=1),
	CB("cb1"),
	F("request_hash", "Data", "Request Hash", read_only=1),
	F("idempotency_key", "Data", "Idempotency Key", read_only=1),
	F("message", "Small Text", "Message", read_only=1),
	SB("sb_resp", "Response"),
	F("response", "Code", "Response Body", read_only=1),
], P_F_QUEUE, autoname="OFSL-.YYYY.-.########", in_create=1)

doctype("Oman Fawtara Receipt", [
	F("submission", "Link", "Submission", "Oman Fawtara Submission", read_only=1, in_list_view=1),
	F("reference_doctype", "Link", "Reference DocType", "DocType", read_only=1),
	F("reference_name", "Dynamic Link", "Reference", "reference_doctype", read_only=1, in_list_view=1, search_index=1),
	F("receipt_type", "Select", "Receipt Type", "Provider Acceptance\nOTA Acknowledgement\nBuyer Delivery", read_only=1),
	CB("cb1"),
	F("provider_reference", "Data", "Provider Reference", read_only=1),
	F("ota_reference", "Data", "OTA Reference", read_only=1),
	F("received_at", "Datetime", "Received At", read_only=1),
	F("content_hash", "Data", "Content Hash", read_only=1),
	F("receipt_file", "Attach", "Receipt", read_only=1),
], P_F_QUEUE, autoname="OFR-.YYYY.-.#######", in_create=1)

doctype("Oman Fawtara Document", [
	F("submission", "Link", "Submission", "Oman Fawtara Submission", read_only=1),
	F("reference_doctype", "Link", "Reference DocType", "DocType", read_only=1),
	F("reference_name", "Dynamic Link", "Reference", "reference_doctype", read_only=1, in_list_view=1, search_index=1),
	F("company", "Link", "Company", "Company", read_only=1),
	F("invoice_number", "Data", "Invoice Number", read_only=1),
	F("document_type", "Data", "Document Type", read_only=1, in_list_view=1),
	CB("cb1"),
	F("document_uuid", "Data", "UUID", read_only=1, search_index=1),
	F("issue_date", "Date", "Issue Date", read_only=1, in_list_view=1),
	F("xml_hash", "Data", "XML SHA-256", read_only=1),
	F("xml_file", "Attach", "Archived XML", read_only=1),
	F("is_provider_stamped", "Check", "Provider-stamped XML", read_only=1),
	F("provider_reference", "Data", "Provider Reference", read_only=1),
	F("retention_until", "Date", "Retain Until", read_only=1),
], P_F_QUEUE, autoname="OFD-.YYYY.-.#######", in_create=1)

doctype("Oman Fawtara Error Log", [
	F("submission", "Link", "Submission", "Oman Fawtara Submission", read_only=1, in_list_view=1, search_index=1),
	F("reference_doctype", "Link", "Reference DocType", "DocType", read_only=1),
	F("reference_name", "Dynamic Link", "Reference", "reference_doctype", read_only=1, in_list_view=1),
	F("category", "Select", "Category", "Local Validation\nProvider Rejection\nTransport\nAuthentication / Configuration\nOTA", read_only=1, in_list_view=1, in_standard_filter=1),
	F("severity", "Select", "Severity", "Error\nWarning", read_only=1),
	CB("cb1"),
	F("error_code", "Data", "Error Code", read_only=1, in_list_view=1),
	F("field_path", "Data", "Field", read_only=1),
	F("attempt", "Int", "Attempt", read_only=1),
	F("resolved", "Check", "Resolved"),
	SB("sb_msg", "Message"),
	F("message", "Small Text", "Message", read_only=1),
	F("resolution_notes", "Small Text", "Resolution Notes"),
], P_F_QUEUE, autoname="OFE-.YYYY.-.#######", in_create=1)

doctype("Oman Fawtara Certificate", [
	F("certificate_name", "Data", "Certificate Name", reqd=1, unique=1, in_list_view=1),
	F("provider", "Link", "Provider", "Oman Fawtara Provider"),
	F("purpose", "Select", "Purpose", "Client TLS\nSigning", default="Client TLS"),
	F("status", "Select", "Status", "Active\nExpired\nRevoked", default="Active", in_list_view=1),
	CB("cb1"),
	F("valid_from", "Date", "Valid From"),
	F("valid_to", "Date", "Valid To", in_list_view=1),
	RO(F("fingerprint", "Data", "SHA-256 Fingerprint")),
	RO(F("subject", "Data", "Subject")),
	RO(F("issuer", "Data", "Issuer")),
	SB("sb_files", "Files (stored privately)"),
	F("certificate_file", "Attach", "Certificate (PEM)"),
	F("private_key_file", "Attach", "Private Key (PEM)"),
	F("key_password", "Password", "Key Password"),
	F("notes", "Small Text", "Notes"),
], [perm("System Manager", w=1, c=1, d=1), perm("Fawtara Manager", w=1, c=1, d=1)], autoname="field:certificate_name")

# =========================== E. Audit ===========================

doctype("Oman Compliance Audit Log", [
	F("sequence", "Int", "Sequence", read_only=1, in_list_view=1, unique=1),
	F("event_type", "Data", "Event", read_only=1, in_list_view=1, in_standard_filter=1),
	F("reference_doctype", "Link", "Reference DocType", "DocType", read_only=1),
	F("reference_name", "Dynamic Link", "Reference", "reference_doctype", read_only=1, in_list_view=1, search_index=1),
	CB("cb1"),
	F("company", "Link", "Company", "Company", read_only=1),
	F("vat_registration", "Link", "VAT Registration", "Oman VAT Registration", read_only=1),
	F("event_user", "Link", "User", "User", read_only=1),
	F("event_timestamp", "Datetime", "Timestamp", read_only=1, in_list_view=1),
	SB("sb_chain", "Hash Chain"),
	F("previous_hash", "Data", "Previous Hash", read_only=1),
	F("entry_hash", "Data", "Entry Hash", read_only=1),
	SB("sb_payload", "Payload"),
	F("payload", "Code", "Payload", options="JSON", read_only=1),
], P_AUDIT, autoname="OCA-.##########", in_create=1, sort_field="sequence")


# ================================ writer ================================


def build(name, spec):
	meta = {k: v for k, v in spec.items() if k not in ("fields", "permissions")}
	fields = spec["fields"]
	d = {
		"actions": [],
		"allow_rename": 0,
		"creation": TS,
		"doctype": "DocType",
		"engine": "InnoDB",
		"field_order": [f["fieldname"] for f in fields],
		"fields": fields,
		"index_web_pages_for_search": 0,
		"links": [],
		"modified": TS,
		"modified_by": "Administrator",
		"module": MODULE,
		"name": name,
		"naming_rule": "",
		"owner": "Administrator",
		"permissions": spec["permissions"],
		"row_format": "Dynamic",
		"sort_field": meta.pop("sort_field", "modified"),
		"sort_order": meta.pop("sort_order", "DESC"),
		"states": [],
	}
	autoname = meta.pop("autoname", None)
	if autoname:
		d["autoname"] = autoname
		d["naming_rule"] = (
			"By fieldname" if autoname.startswith("field:")
			else "Expression" if autoname.startswith("format:")
			else "By \"Naming Series\" field" if autoname == "naming_series:"
			else "Expression (old style)"
		)
	else:
		d.pop("naming_rule")
	for k, v in meta.items():
		d[k] = v
	if d.get("istable"):
		d.pop("permissions")
		d["permissions"] = []
	if d.get("is_submittable") and not any(f["fieldname"] == "amended_from" for f in fields):
		raise SystemExit(f"{name}: submittable without amended_from")
	return d


def main(root):
	base = os.path.join(root, APP, "oman_fawtara", "doctype")
	os.makedirs(base, exist_ok=True)
	open(os.path.join(base, "__init__.py"), "a").close()
	for name, spec in DT.items():
		s = snake(name)
		folder = os.path.join(base, s)
		os.makedirs(folder, exist_ok=True)
		open(os.path.join(folder, "__init__.py"), "a").close()
		with open(os.path.join(folder, f"{s}.json"), "w") as fh:
			json.dump(build(name, spec), fh, indent=1, ensure_ascii=False)
			fh.write("\n")
		py = os.path.join(folder, f"{s}.py")
		if not os.path.exists(py):
			cls = name.replace(" ", "")
			with open(py, "w") as fh:
				fh.write(
					"# Copyright (c) 2026, thinkNXG and contributors\n# For license information, please see license.txt\n\n"
					"from frappe.model.document import Document\n\n\n"
					f"class {cls}(Document):\n\tpass\n"
				)
	print(f"generated {len(DT)} doctypes")


if __name__ == "__main__":
	main(sys.argv[1])
