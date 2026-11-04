"""Invoice analysis engine.

For every Sales Invoice / Purchase Invoice line the engine:

1. resolves the VAT *treatment* (independent of the rate),
2. resolves the VAT code and the rate in force at the tax point,
3. reads the VAT actually computed by ERPNext for that line from the v16
   relational ``Item Wise Tax Detail`` structure,
4. computes output / input / recoverable / non-recoverable / reverse-charge
   figures in OMR,
5. reconciles the per-line figures with ERPNext's tax rows (it never
   overrides the ERPNext tax total), and
6. runs the configurable validation rule set.

The result is written to the ``oman_*`` custom fields on each line and on the
document header, and returned for the caller (hooks, API, tests).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate

from oman_fawtara.vat import calc, recovery, rules, validation
from oman_fawtara.vat.calc import D
from oman_fawtara.vat.utils import (
	OMAN,
	get_account_mapping,
	get_period_for,
	get_registration,
	party_country,
	party_vat_status,
	settings,
	to_omr_factor,
)

DIRECTION = {"Sales Invoice": "Sales", "Purchase Invoice": "Purchase"}
PARTY = {"Sales Invoice": ("Customer", "customer"), "Purchase Invoice": ("Supplier", "supplier")}


@dataclass
class Analysis:
	doctype: str
	name: str | None
	direction: str
	company: str
	registration: str | None
	tax_point: object
	ruleset: str | None
	lines: list = field(default_factory=list)
	issues: list = field(default_factory=list)
	totals: dict = field(default_factory=dict)

	@property
	def errors(self):
		return [i for i in self.issues if i["severity"] == "Error"]

	@property
	def warnings(self):
		return [i for i in self.issues if i["severity"] == "Warning"]

	@property
	def status(self) -> str:
		if self.errors:
			return "Failed"
		if self.warnings:
			return "Warnings"
		return "Passed"

	def add(self, code, severity, message, line=None, rule=None):
		self.issues.append(
			{"code": code, "severity": severity, "message": message, "line": line, "rule": rule}
		)


# --------------------------------------------------------------------------
# ERPNext v16 item-wise tax access
# --------------------------------------------------------------------------


def item_tax_breakup(doc, account_filter: set[str]) -> dict[str, dict]:
	"""Return {item_row_name: {"amount": x, "rate": r, "taxable": t, "rows": n}}.

	Reads the in-memory ``_item_wise_tax_details`` produced by ERPNext's
	``calculate_taxes_and_totals`` during validate (row objects), falling back
	to the persisted ``item_wise_tax_details`` child table (row names). The
	legacy JSON ``item_wise_tax_detail`` field is intentionally not used.
	Amounts are in company currency. Deducted purchase tax rows are negated.
	"""
	taxes_by_name = {t.name: t for t in doc.get("taxes") or []}
	out: dict[str, dict] = {}

	def add(item_key, tax, amount, rate, taxable):
		if tax is None or tax.account_head not in account_filter:
			return
		sign = -1 if tax.get("add_deduct_tax") == "Deduct" else 1
		bucket = out.setdefault(item_key, {"amount": 0.0, "rate": 0.0, "taxable": 0.0, "rows": 0})
		bucket["amount"] += sign * flt(amount)
		bucket["rate"] += sign * flt(rate)
		bucket["taxable"] = max(bucket["taxable"], flt(taxable))
		bucket["rows"] += 1

	live = doc.get("_item_wise_tax_details")
	if live:
		for row in live:
			item, tax = row.get("item"), row.get("tax")
			if item is None:
				continue
			add(_item_key(item), tax, row.get("amount"), row.get("rate"), row.get("taxable_amount"))
		return out

	for row in doc.get("item_wise_tax_details") or []:
		add(row.item_row, taxes_by_name.get(row.tax_row), row.amount, row.rate, row.taxable_amount)
	return out


def _item_key(item) -> str:
	# Unsaved rows may not have a name yet; fall back to a stable idx key.
	return item.name or f"idx:{item.idx}"


# --------------------------------------------------------------------------
# Treatment resolution
# --------------------------------------------------------------------------


def _treatment(name):
	return frappe.get_cached_doc("Oman VAT Treatment", name) if name else None


def default_code_for(treatment: str, direction: str) -> str | None:
	codes = frappe.get_all(
		"Oman VAT Code",
		filters={"treatment": treatment, "disabled": 0, "direction": ["in", [direction, "Both"]]},
		fields=["name", "is_default"],
		order_by="is_default desc, name asc",
		limit=1,
	)
	return codes[0].name if codes else None


def code_from_template(item_tax_template: str | None, company: str) -> str | None:
	"""Reverse-map an Item Tax Template to a VAT code, only when unambiguous.

	Several codes legitimately share a template (e.g. zero-rated, exempt and
	out-of-scope all carry 0%), so an ambiguous template never decides the
	treatment on its own.
	"""
	if not item_tax_template:
		return None
	codes = frappe.get_all(
		"Oman VAT Code Template",
		filters={"item_tax_template": item_tax_template, "parenttype": "Oman VAT Code", "company": company},
		pluck="parent",
		distinct=True,
	)
	return codes[0] if len(codes) == 1 else None


def supply_category(item) -> str:
	if item.get("oman_supply_category"):
		return item.oman_supply_category
	if item.get("item_code"):
		cat = frappe.get_cached_value("Item", item.item_code, "oman_supply_category")
		if cat:
			return cat
		if not cint(frappe.get_cached_value("Item", item.item_code, "is_stock_item")):
			return "Services"
	return "Goods"


EXPLICIT_SOURCES = ("", "line", "line-code")


def resolve_treatment(ctx: dict, item) -> tuple[str, str | None, str]:
	"""Return (treatment, vat_code, source) for a line.

	Precedence: explicit line treatment → explicit line VAT code → Item default
	VAT code → reverse-charge / import identification for foreign suppliers →
	unambiguous Item Tax Template mapping → settings default.

	A treatment/code stored on the line counts as explicit only when the user
	set it (``oman_vat_source`` empty or "line"/"line-code"). Values the engine
	derived earlier are recomputed, so changing the supplier or item on a draft
	re-classifies the line.
	"""
	direction = ctx["direction"]
	explicit = (item.get("oman_vat_source") or "") in EXPLICIT_SOURCES
	code = item.get("oman_vat_code") if explicit else None
	if explicit and item.get("oman_vat_treatment"):
		return item.oman_vat_treatment, code or default_code_for(item.oman_vat_treatment, direction), "line"
	if code:
		return frappe.get_cached_value("Oman VAT Code", code, "treatment"), code, "line-code"

	if item.get("item_code"):
		item_code_default = frappe.get_cached_value(
			"Item",
			item.item_code,
			"oman_sales_vat_code" if direction == "Sales" else "oman_purchase_vat_code",
		)
		if item_code_default:
			return frappe.get_cached_value("Oman VAT Code", item_code_default, "treatment"), item_code_default, "item"

	if direction == "Purchase":
		auto = auto_purchase_treatment(ctx, item)
		if auto:
			return auto, default_code_for(auto, direction), "auto"

	tmpl_code = code_from_template(item.get("item_tax_template"), ctx["company"])
	if tmpl_code:
		return frappe.get_cached_value("Oman VAT Code", tmpl_code, "treatment"), tmpl_code, "item-tax-template"

	s = settings()
	default = s.default_sales_treatment if direction == "Sales" else s.default_purchase_treatment
	return default, default_code_for(default, direction), "default"


def auto_purchase_treatment(ctx: dict, item) -> str | None:
	"""Reverse-charge / import identification for foreign suppliers.

	Configurable ``Reverse Charge`` rules are evaluated first; when none
	match, the built-in baseline applies: services from a supplier outside
	Oman that is not Oman-VAT-registered are imported services subject to
	reverse charge, goods from such a supplier are imports of goods (VAT is
	assessed by customs, not on the supplier invoice).
	"""
	line = {"supply_category": supply_category(item), "item_group": item.get("item_group"),
		"account": item.get("expense_account")}
	for rule in rules.active_rules(ctx["tax_point"], "Purchase", "Reverse Charge", ctx["company"]):
		if rule.action_treatment and rules.rule_matches_line(rule, ctx, line):
			return rule.action_treatment

	s = settings()
	if not cint(s.auto_detect_reverse_charge):
		return None
	if ctx.get("party_country") and ctx["party_country"] != OMAN and ctx.get("party_vat_status") != "Registered":
		return s.import_of_services_treatment if line["supply_category"] == "Services" else s.import_of_goods_treatment
	return None


# --------------------------------------------------------------------------
# Context
# --------------------------------------------------------------------------


def determine_tax_point(doc):
	"""Tax point: explicit value, else the earlier of supply date and issue date."""
	if doc.get("oman_tax_point_date"):
		return getdate(doc.oman_tax_point_date)
	posting = getdate(doc.posting_date)
	supply = doc.get("oman_supply_date")
	if DIRECTION[doc.doctype] == "Sales" and supply and getdate(supply) < posting:
		return getdate(supply)
	return posting


def build_context(doc) -> dict:
	direction = DIRECTION[doc.doctype]
	party_type, party_field = PARTY[doc.doctype]
	party = doc.get(party_field)
	tax_point = determine_tax_point(doc)
	reg_name = doc.get("oman_vat_registration")
	if reg_name and not frappe.db.exists("Oman VAT Registration", reg_name):
		reg_name = None  # stale reference (e.g. registration deleted/re-created)
	registration = (
		frappe.get_cached_doc("Oman VAT Registration", reg_name)
		if reg_name
		else get_registration(doc.company, tax_point)
	)
	mapping = get_account_mapping(doc.company, registration.name if registration else None, raise_if_missing=False)
	return {
		"doc": doc,
		"direction": direction,
		"company": doc.company,
		"tax_point": tax_point,
		"registration": registration,
		"mapping": mapping,
		"party_type": party_type,
		"party": party,
		"party_country": party_country(party_type, party) or OMAN,
		"party_vat_status": party_vat_status(party_type, party),
		"party_vrn": doc.get("tax_id") or frappe.db.get_value(party_type, party, "tax_id"),
		"factor": to_omr_factor(doc.company, tax_point),
		"is_return": cint(doc.get("is_return")),
		"is_debit_note": cint(doc.get("is_debit_note")),
	}


def vat_charge_accounts(mapping, direction) -> set[str]:
	"""Accounts whose tax rows represent VAT *charged on the document*."""
	if not mapping:
		return set()
	if direction == "Sales":
		return {a for a in (mapping.output_vat_account,) if a}
	return {a for a in (mapping.input_vat_account,) if a}


# --------------------------------------------------------------------------
# Main entry point
# --------------------------------------------------------------------------


def analyse(doc, persist: bool = True) -> Analysis:
	ctx = build_context(doc)
	s = settings()
	reg = ctx["registration"]
	a = Analysis(
		doctype=doc.doctype,
		name=doc.name,
		direction=ctx["direction"],
		company=doc.company,
		registration=reg.name if reg else None,
		tax_point=ctx["tax_point"],
		ruleset=s.active_ruleset_version,
	)
	if not reg:
		a.add("NO_REGISTRATION", "Error", _("Company {0} has no active Oman VAT Registration at {1}.").format(
			doc.company, ctx["tax_point"]))
		_persist_header(doc, a, ctx, persist)
		return a
	if not ctx["mapping"]:
		a.add("NO_ACCOUNT_MAPPING", "Error", _("No Oman VAT Account Mapping for company {0}.").format(doc.company))
		_persist_header(doc, a, ctx, persist)
		return a

	charge_accounts = vat_charge_accounts(ctx["mapping"], ctx["direction"])
	breakup = item_tax_breakup(doc, charge_accounts)
	factor = D(ctx["factor"])
	places = cint(s.currency_precision) or calc.OMR_PLACES

	for item in doc.get("items") or []:
		treatment_name, code, source = resolve_treatment(ctx, item)
		treatment = _treatment(treatment_name)
		if not treatment:
			a.add("NO_TREATMENT", "Error", _("Row {0}: no VAT treatment could be determined.").format(item.idx), item.idx)
			continue
		if treatment.direction not in (ctx["direction"], "Both"):
			a.add("TREATMENT_DIRECTION", "Error", _("Row {0}: treatment {1} is not valid for {2}.").format(
				item.idx, treatment_name, ctx["direction"]), item.idx)

		rate, rate_ref = rules.get_rate(treatment_name, code, ctx["tax_point"])
		cat = supply_category(item)
		taxable = calc.round_money(D(item.base_net_amount) * factor, places)
		bk = breakup.get(_item_key(item), {})
		charged = calc.round_money(D(bk.get("amount", 0)) * factor, places)
		reverse = bool(cint(treatment.is_reverse_charge))
		charges_vat = bool(cint(treatment.charges_vat))

		pct, profile, rec_status = 100, None, "Not Applicable"
		if ctx["direction"] == "Purchase":
			pct, profile, rec_status = recovery.resolve(ctx, item, treatment, a)

		res = calc.compute_line(
			direction=ctx["direction"],
			taxable=taxable,
			rate=rate,
			charges_vat=charges_vat,
			reverse_charge=reverse,
			recovery_pct=pct,
			charged_vat=None if reverse else charged,
			places=places,
		)

		line = {
			"idx": item.idx,
			"row": item.name,
			"item_code": item.get("item_code"),
			"item_group": item.get("item_group"),
			"account": item.get("expense_account") or item.get("income_account"),
			"treatment": treatment_name,
			"vat_code": code,
			"source": source,
			"rate": flt(rate),
			"rate_ref": rate_ref,
			"supply_category": cat,
			"reverse_charge": reverse,
			"is_import": bool(cint(treatment.is_import)),
			"nature": treatment.nature,
			"recovery_profile": profile,
			"recovery_status": rec_status,
			"charged_vat": res.charged_vat,
			**{k: v for k, v in res.as_dict().items() if k not in ("notes", "charged_vat")},
		}
		a.lines.append(line)

		# Per-line arithmetic checks (always on: these are tax-correctness invariants)
		tol = D(s.line_tolerance or "0.001")
		if not charges_vat and not reverse and abs(D(charged)) > tol:
			a.add("VAT_ON_NON_TAXABLE", "Error", _(
				"Row {0}: treatment {1} must not carry VAT but ERPNext computed {2} OMR. "
				"Fix the Item Tax Template for this line."
			).format(item.idx, treatment_name, charged), item.idx)
		elif charges_vat and not reverse and abs(res.expected_vat - charged) > tol:
			a.add("RATE_MISMATCH", "Error", _(
				"Row {0}: VAT computed by ERPNext ({1} OMR) differs from {2}% on {3} OMR ({4} OMR) "
				"required for treatment {5} at {6}."
			).format(item.idx, charged, flt(rate), taxable, res.expected_vat, treatment_name, ctx["tax_point"]), item.idx)
		if reverse and abs(D(charged)) > tol:
			a.add("RCM_SUPPLIER_CHARGED_VAT", "Warning", _(
				"Row {0}: reverse-charge line also carries supplier-charged VAT of {1} OMR."
			).format(item.idx, charged), item.idx)

		if persist:
			_persist_line(item, line)

	_reconcile_with_tax_rows(doc, a, ctx, charge_accounts, factor, places)
	validation.run_checks(doc, ctx, a)
	_persist_header(doc, a, ctx, persist)
	return a


def _reconcile_with_tax_rows(doc, a: Analysis, ctx, charge_accounts, factor, places):
	"""The sum of per-line VAT must equal ERPNext's VAT tax rows."""
	tax_rows_total = D(0)
	for t in doc.get("taxes") or []:
		if t.account_head in charge_accounts:
			sign = -1 if t.get("add_deduct_tax") == "Deduct" else 1
			tax_rows_total += sign * D(t.base_tax_amount_after_discount_amount)
	tax_rows_total = calc.round_money(tax_rows_total * factor, places)
	lines_total = sum((D(l["charged_vat"]) for l in a.lines if not l["reverse_charge"]), D(0))
	ok, diff = calc.reconcile(lines_total, tax_rows_total, calc.line_tolerance(len(a.lines)))
	a.totals["erpnext_vat_total"] = float(tax_rows_total)
	a.totals["line_vat_total"] = float(lines_total)
	a.totals["reconciliation_difference"] = float(diff)
	if not ok:
		a.add("TAX_ROW_RECONCILIATION", "Error", _(
			"Per-line VAT ({0} OMR) does not reconcile with ERPNext VAT tax rows ({1} OMR); difference {2}. "
			"Use item-wise ('On Net Total') VAT rows rather than 'Actual' amounts on VAT accounts."
		).format(lines_total, tax_rows_total, diff))


def _persist_line(item, line):
	item.oman_vat_source = line["source"]
	item.oman_vat_treatment = line["treatment"]
	item.oman_vat_code = line["vat_code"]
	item.oman_vat_rate = line["rate"]
	item.oman_taxable_amount = line["taxable"]
	item.oman_output_vat = line["output_vat"]
	item.oman_input_vat = line["input_vat"]
	item.oman_recovery_percentage = line["recovery_pct"]
	item.oman_recoverable_vat = line["recoverable"]
	item.oman_nonrecoverable_vat = line["nonrecoverable"]
	item.oman_reverse_charge = 1 if line["reverse_charge"] else 0
	item.oman_supply_category = line["supply_category"]
	item.oman_rate_reference = line["rate_ref"]
	if item.meta.has_field("oman_recovery_profile"):
		item.oman_recovery_profile = line["recovery_profile"]
		item.oman_recovery_status = line["recovery_status"]


def _persist_header(doc, a: Analysis, ctx, persist):
	totals = {
		"output_vat": sum(l["output_vat"] for l in a.lines),
		"input_vat": sum(l["input_vat"] for l in a.lines),
		"recoverable": sum(l["recoverable"] for l in a.lines),
		"nonrecoverable": sum(l["nonrecoverable"] for l in a.lines),
		"rcm_output": sum(l["rcm_output"] for l in a.lines),
		"taxable": sum(l["taxable"] for l in a.lines),
	}
	a.totals.update(totals)
	if not persist:
		return
	doc.oman_tax_point_date = ctx["tax_point"]
	if a.registration:
		doc.oman_vat_registration = a.registration
		period = get_period_for(a.registration, ctx["tax_point"])
		doc.oman_vat_period = period.name if period else None
	doc.oman_vat_ruleset = a.ruleset
	doc.oman_vat_validation_status = a.status
	doc.oman_total_taxable_amount = totals["taxable"]
	doc.oman_total_output_vat = totals["output_vat"]
	doc.oman_total_input_vat = totals["input_vat"]
	doc.oman_total_recoverable_vat = totals["recoverable"]
	doc.oman_total_nonrecoverable_vat = totals["nonrecoverable"]
	doc.oman_total_rcm_vat = totals["rcm_output"]
	doc.oman_reverse_charge = 1 if any(l["reverse_charge"] for l in a.lines) else 0
	doc.oman_vat_issues = frappe.as_json(a.issues) if a.issues else None
