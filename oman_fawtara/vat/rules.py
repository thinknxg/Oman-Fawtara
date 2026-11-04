"""Versioned legal rule resolution.

Every rate and every configurable compliance check is stored with an
effective-from / effective-to window and a rule-set version. A document is
always evaluated against the rules in force at its *tax point*, so historic
invoices and filed returns keep the rules that applied when they arose.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, getdate

from oman_fawtara.vat.utils import GCC_COUNTRIES, OMAN


def get_rate(treatment: str, vat_code: str | None, on_date) -> tuple[float, str | None]:
	"""Return (rate, rate_history_name) effective at ``on_date``.

	A VAT-code specific entry overrides the treatment-level entry.
	"""
	on_date = getdate(on_date)
	for filters in (
		{"vat_code": vat_code, "treatment": treatment} if vat_code else None,
		{"treatment": treatment, "vat_code": ["is", "not set"]},
	):
		if not filters:
			continue
		rows = frappe.get_all(
			"Oman VAT Rate History",
			filters={**filters, "effective_from": ["<=", on_date], "docstatus": ["!=", 2]},
			fields=["name", "rate", "effective_to"],
			order_by="effective_from desc",
		)
		for row in rows:
			if not row.effective_to or getdate(row.effective_to) >= on_date:
				return flt(row.rate), row.name
	frappe.throw(
		_("No Oman VAT rate is effective for treatment {0} on {1}. Check Oman VAT Rate History.").format(
			treatment, on_date
		)
	)


def active_rules(on_date, applies_to: str, rule_type: str | None = None, company: str | None = None):
	"""Approved, enabled rules effective at ``on_date``."""
	on_date = getdate(on_date)
	filters = {
		"status": "Approved",
		"enabled": 1,
		"effective_from": ["<=", on_date],
		"applies_to": ["in", [applies_to, "Both"]],
	}
	if rule_type:
		filters["rule_type"] = rule_type
	rules = frappe.get_all(
		"Oman VAT Rule",
		filters=filters,
		fields=[
			"name",
			"rule_code",
			"title",
			"rule_type",
			"check_key",
			"severity",
			"effective_from",
			"effective_to",
			"legal_reference",
			"ruleset_version",
			"company",
			"treatment",
			"vat_code",
			"party_country_condition",
			"party_registration_condition",
			"supply_category",
			"item_group",
			"account",
			"numeric_value",
			"text_value",
			"action_treatment",
			"action_recovery_profile",
			"message",
			"priority",
		],
		order_by="priority desc, effective_from desc",
	)
	out = []
	for r in rules:
		if r.effective_to and getdate(r.effective_to) < on_date:
			continue
		if r.company and company and r.company != company:
			continue
		out.append(r)
	return out


def rules_by_check(on_date, applies_to: str, company: str | None = None) -> dict:
	out = {}
	for r in active_rules(on_date, applies_to, company=company):
		if r.check_key and r.check_key not in out:
			out[r.check_key] = r
	return out


def country_matches(condition: str | None, country: str | None) -> bool:
	if not condition or condition == "Any":
		return True
	if condition == "Oman":
		return country == OMAN
	if condition == "Not Oman":
		return bool(country) and country != OMAN
	if condition == "GCC":
		return country in GCC_COUNTRIES
	if condition == "Non-GCC":
		return bool(country) and country not in GCC_COUNTRIES
	return True


def registration_matches(condition: str | None, vat_status: str | None) -> bool:
	if not condition or condition == "Any":
		return True
	registered = vat_status in ("Registered", "Government")
	return registered if condition == "Registered" else not registered


def rule_matches_line(rule, ctx: dict, line: dict) -> bool:
	"""Evaluate a rule's conditions against a document line context."""
	if rule.treatment and rule.treatment != line.get("treatment"):
		return False
	if rule.vat_code and rule.vat_code != line.get("vat_code"):
		return False
	if rule.supply_category and rule.supply_category not in ("Any", line.get("supply_category")):
		return False
	if rule.item_group and rule.item_group != line.get("item_group"):
		return False
	if rule.account and rule.account != line.get("account"):
		return False
	if not country_matches(rule.party_country_condition, ctx.get("party_country")):
		return False
	if not registration_matches(rule.party_registration_condition, ctx.get("party_vat_status")):
		return False
	return True
