"""VAT Validation Engine.

Two layers:

* **Core invariants** always run (registration, period status, treatment
  direction, arithmetic — see ``engine.analyse``).
* **Configurable legal checks** run only when an *Approved*, enabled
  ``Oman VAT Rule`` with the matching ``check_key`` is effective at the
  document's tax point. The rule supplies severity, parameters, legal
  reference and rule-set version, so legal changes are made by adding a new
  dated rule rather than editing code.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, date_diff, flt, getdate

from oman_fawtara.vat import calc, rules
from oman_fawtara.vat.utils import OMAN, get_period_for, settings

CHECKS: dict[str, callable] = {}


def check(key):
	def deco(fn):
		CHECKS[key] = fn
		return fn

	return deco


def run_checks(doc, ctx: dict, analysis):
	_core_checks(doc, ctx, analysis)
	applies = analysis.direction
	for key, rule in rules.rules_by_check(ctx["tax_point"], applies, ctx["company"]).items():
		fn = CHECKS.get(key)
		if fn:
			fn(doc, ctx, analysis, rule)


def _emit(analysis, rule, message, line=None):
	text = rule.message or message
	if rule.message and "{" in rule.message:
		try:
			text = rule.message.format(line=line, value=rule.numeric_value)
		except (KeyError, IndexError, ValueError):
			text = rule.message
	ref = f" [{rule.rule_code}{' · ' + rule.legal_reference if rule.legal_reference else ''}]"
	analysis.add(rule.check_key, rule.severity, text + ref, line, rule.name)


# --------------------------------------------------------------------------
# Core invariants
# --------------------------------------------------------------------------


def _core_checks(doc, ctx, a):
	reg = ctx["registration"]
	if reg.status != "Active":
		a.add("REGISTRATION_STATUS", "Error", _("VAT registration {0} is {1}.").format(reg.name, reg.status))
	if not calc.vrn_is_valid(reg.vatin, settings().vrn_pattern):
		a.add("COMPANY_VRN_FORMAT", "Error", _("Company VAT number {0} is not in the expected format.").format(reg.vatin))

	period = get_period_for(reg.name, ctx["tax_point"])
	if period and period.status in ("Finalized", "Filed", "Locked"):
		a.add("PERIOD_CLOSED", "Error", _(
			"Tax point {0} falls in VAT period {1} which is {2}. Record the correction in an open period "
			"through an Oman VAT Adjustment."
		).format(ctx["tax_point"], period.name, period.status))

	if ctx["tax_point"] > getdate() and not cint(settings().allow_future_tax_point):
		a.add("FUTURE_TAX_POINT", "Error", _("Tax point {0} is in the future.").format(ctx["tax_point"]))


# --------------------------------------------------------------------------
# Configurable checks
# --------------------------------------------------------------------------


@check("party_vrn_format")
def _party_vrn_format(doc, ctx, a, rule):
	vrn = ctx.get("party_vrn")
	if vrn and ctx.get("party_country") == OMAN and not calc.vrn_is_valid(vrn, settings().vrn_pattern):
		_emit(a, rule, _("{0} VAT number {1} is not a valid Oman VAT number.").format(ctx["party_type"], vrn))


@check("b2b_requires_buyer_vrn")
def _b2b_vrn(doc, ctx, a, rule):
	if a.direction != "Sales":
		return
	if ctx.get("party_vat_status") == "Registered" and not ctx.get("party_vrn"):
		_emit(a, rule, _("Customer is VAT-registered but no VAT number is recorded."))


@check("input_claim_requires_supplier_vrn")
def _supplier_vrn(doc, ctx, a, rule):
	if a.direction != "Purchase":
		return
	claims = [l for l in a.lines if not l["reverse_charge"] and not l["is_import"] and l["recoverable"] > 0]
	if claims and ctx.get("party_country") == OMAN and not calc.vrn_is_valid(ctx.get("party_vrn"), settings().vrn_pattern):
		_emit(a, rule, _("Input VAT is claimed but the supplier has no valid Oman VAT number on the tax invoice."))
		for line in claims:
			line["recovery_status"] = "Pending Evidence"


@check("zero_rated_requires_evidence")
def _zero_evidence(doc, ctx, a, rule):
	zero = [l for l in a.lines if l["nature"] == "Zero Rated"]
	if not zero or not doc.name or doc.is_new():
		if zero:
			_emit(a, rule, _("Zero-rated supplies require supporting evidence (attach after saving)."))
		return
	have = frappe.db.count(
		"Oman VAT Evidence",
		{"reference_doctype": doc.doctype, "reference_name": doc.name, "status": ["in", ["Received", "Verified"]]},
	)
	if not have:
		_emit(a, rule, _("No Oman VAT Evidence recorded for zero-rated lines {0}.").format(
			", ".join(str(l["idx"]) for l in zero)))


@check("export_requires_foreign_destination")
def _export_dest(doc, ctx, a, rule):
	if a.direction != "Sales":
		return
	for l in a.lines:
		if l["vat_code"] and cint(frappe.get_cached_value("Oman VAT Code", l["vat_code"], "is_export")):
			if ctx.get("party_country") == OMAN and not doc.get("oman_export_destination"):
				_emit(a, rule, _("Row {0}: export VAT code used but customer and destination are in Oman.").format(
					l["idx"]), l["idx"])


@check("invoice_issue_within_days")
def _issue_days(doc, ctx, a, rule):
	if a.direction != "Sales" or not doc.get("oman_supply_date"):
		return
	limit = cint(rule.numeric_value or 0)
	gap = date_diff(doc.posting_date, doc.oman_supply_date)
	if limit and gap > limit:
		_emit(a, rule, _("Tax invoice issued {0} days after supply (limit {1}).").format(gap, limit))


@check("duplicate_supplier_invoice")
def _duplicate(doc, ctx, a, rule):
	if a.direction != "Purchase" or not doc.get("bill_no") or cint(doc.get("is_return")):
		return
	key = calc.normalize_invoice_number(doc.bill_no)
	doc.oman_duplicate_check_key = key
	filters = {
		"company": doc.company,
		"docstatus": 1,
		"is_return": 0,
		"oman_duplicate_check_key": key,
		"name": ["!=", doc.name or ""],
	}
	same_supplier = frappe.get_all("Purchase Invoice", filters={**filters, "supplier": doc.supplier}, pluck="name")
	same_vrn = []
	if ctx.get("party_vrn"):
		same_vrn = frappe.get_all(
			"Purchase Invoice",
			filters={**filters, "tax_id": ctx["party_vrn"], "supplier": ["!=", doc.supplier]},
			pluck="name",
		)
	dupes = same_supplier + same_vrn
	if dupes:
		_emit(a, rule, _("Supplier invoice {0} already booked in {1} (possible duplicate VAT claim).").format(
			doc.bill_no, ", ".join(dupes)))


@check("rcm_foreign_services")
def _rcm_missing(doc, ctx, a, rule):
	if a.direction != "Purchase":
		return
	if ctx.get("party_country") in (None, OMAN) or ctx.get("party_vat_status") == "Registered":
		return
	for l in a.lines:
		if l["supply_category"] == "Services" and not l["reverse_charge"] and l["nature"] != "Out of Scope":
			_emit(a, rule, _("Row {0}: service from a foreign supplier is not under reverse charge.").format(
				l["idx"]), l["idx"])


@check("import_goods_requires_declaration")
def _import_decl(doc, ctx, a, rule):
	if a.direction != "Purchase":
		return
	imports = [l for l in a.lines if l["is_import"] and l["supply_category"] == "Goods"]
	if not imports:
		return
	linked = doc.get("oman_import_declaration") or (
		doc.name
		and frappe.db.exists("Oman Import Declaration Invoice", {"purchase_invoice": doc.name, "docstatus": ["<", 2]})
	)
	if not linked:
		_emit(a, rule, _("Imported goods need a customs (Bayan) Oman Import Declaration."))


@check("credit_note_requires_original")
def _cn_original(doc, ctx, a, rule):
	if not cint(doc.get("is_return")):
		return
	if not doc.get("return_against"):
		_emit(a, rule, _("Credit/debit note must reference the original invoice."))
		return
	original = frappe.get_doc(doc.doctype, doc.return_against)
	orig_by_item = {i.item_code: i.get("oman_vat_treatment") for i in original.items}
	for l in a.lines:
		ot = orig_by_item.get(l["item_code"])
		if ot and ot != l["treatment"]:
			_emit(a, rule, _("Row {0}: treatment {1} differs from original invoice treatment {2}.").format(
				l["idx"], l["treatment"], ot), l["idx"])


@check("adjustment_reason_required")
def _adj_reason(doc, ctx, a, rule):
	if (cint(doc.get("is_return")) or cint(doc.get("is_debit_note"))) and not doc.get("oman_adjustment_reason"):
		_emit(a, rule, _("Select an Oman VAT adjustment reason for this credit/debit note."))


@check("foreign_currency_rate")
def _fx(doc, ctx, a, rule):
	if doc.get("currency") != "OMR" and not flt(doc.get("conversion_rate")):
		_emit(a, rule, _("Exchange rate to OMR is missing."))


@check("b2c_simplified_threshold")
def _b2c(doc, ctx, a, rule):
	# Example parametric check: warn when a B2C invoice exceeds a configured amount
	if a.direction != "Sales" or doc.get("oman_buyer_type") != "B2C":
		return
	limit = flt(rule.numeric_value)
	if limit and flt(doc.base_grand_total) > limit:
		_emit(a, rule, _("B2C invoice exceeds {0} OMR; confirm buyer details.").format(limit))
