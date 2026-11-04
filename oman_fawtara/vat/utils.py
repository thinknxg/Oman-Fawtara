"""Frappe-bound helpers shared by the VAT engines."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate

from oman_fawtara.vat.calc import D, round_money

OMAN = "Oman"
GCC_COUNTRIES = {"Oman", "United Arab Emirates", "Saudi Arabia", "Qatar", "Bahrain", "Kuwait"}
REPORTING_CURRENCY = "OMR"


def settings():
	return frappe.get_cached_doc("Oman VAT Settings")


def is_enabled() -> bool:
	try:
		return bool(cint(settings().enabled))
	except frappe.DoesNotExistError:
		return False


def enforcement_blocks() -> bool:
	"""True when Errors must block document submission (vs. advisory mode)."""
	return settings().enforcement_mode == "Block"


def get_registration(company: str, on_date=None, raise_if_missing: bool = False):
	"""Return the active Oman VAT Registration for ``company`` at ``on_date``.

	A company may hold several registrations over time (or a tax-group
	registration); the one effective at the tax point wins. If the document
	names a registration explicitly the caller should use that instead.
	"""
	on_date = getdate(on_date) if on_date else getdate()
	rows = frappe.get_all(
		"Oman VAT Registration",
		filters={"company": company, "status": ["in", ["Active", "Suspended"]]},
		fields=["name", "effective_from", "effective_to", "status", "is_default"],
		order_by="is_default desc, effective_from desc",
	)
	for row in rows:
		if (not row.effective_from or getdate(row.effective_from) <= on_date) and (
			not row.effective_to or getdate(row.effective_to) >= on_date
		):
			return frappe.get_cached_doc("Oman VAT Registration", row.name)
	if raise_if_missing:
		frappe.throw(_("No active Oman VAT Registration for company {0} on {1}").format(company, on_date))
	return None


def get_account_mapping(company: str, registration: str | None = None, raise_if_missing: bool = True):
	filters = {"company": company, "disabled": 0}
	name = None
	if registration:
		name = frappe.db.get_value("Oman VAT Account Mapping", {**filters, "vat_registration": registration})
	if not name:
		name = frappe.db.get_value("Oman VAT Account Mapping", filters)
	if not name:
		if raise_if_missing:
			frappe.throw(_("Configure an Oman VAT Account Mapping for company {0}").format(company))
		return None
	return frappe.get_cached_doc("Oman VAT Account Mapping", name)


def vat_accounts(company: str, registration: str | None = None) -> set[str]:
	m = get_account_mapping(company, registration, raise_if_missing=False)
	if not m:
		return set()
	return {
		a
		for a in (
			m.output_vat_account,
			m.input_vat_account,
			m.rcm_output_vat_account,
			m.rcm_input_vat_account,
			m.import_vat_account,
		)
		if a
	}


def company_currency(company: str) -> str:
	return frappe.get_cached_value("Company", company, "default_currency")


def to_omr_factor(company: str, on_date) -> float:
	"""Factor converting company-currency amounts into OMR.

	For an Oman entity the company currency is OMR and the factor is 1. If a
	group company keeps books in another currency we convert at the rate
	effective on the tax point, as the return must be expressed in OMR.
	"""
	cur = company_currency(company)
	if cur == REPORTING_CURRENCY:
		return 1.0
	from erpnext.setup.utils import get_exchange_rate

	rate = flt(get_exchange_rate(cur, REPORTING_CURRENCY, on_date))
	if not rate:
		frappe.throw(_("Missing exchange rate {0} → OMR on {1}").format(cur, on_date))
	return rate


def omr(value, factor=1.0):
	return round_money(D(value) * D(factor))


def party_country(party_type: str, party: str) -> str | None:
	if not party:
		return None
	if party_type == "Supplier":
		return frappe.db.get_value("Supplier", party, "oman_party_country") or frappe.db.get_value(
			"Supplier", party, "country"
		)
	return frappe.db.get_value("Customer", party, "oman_party_country")


def party_vat_status(party_type: str, party: str) -> str | None:
	if not party:
		return None
	return frappe.db.get_value(party_type, party, "oman_vat_status")


def has_role(*roles) -> bool:
	user_roles = set(frappe.get_roles())
	return bool(user_roles.intersection(roles)) or frappe.session.user == "Administrator"


def get_period_for(registration: str, on_date):
	on_date = getdate(on_date)
	return frappe.db.get_value(
		"Oman VAT Period",
		{"vat_registration": registration, "from_date": ["<=", on_date], "to_date": [">=", on_date]},
		["name", "status"],
		as_dict=True,
	)
