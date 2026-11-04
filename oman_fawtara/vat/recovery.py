"""Input VAT recovery engine.

Distinguishes fully recoverable, fully blocked, partially recoverable,
residual (apportioned) and pending-evidence input VAT. The original input VAT
is always retained; recovery only splits its accounting treatment.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate

from oman_fawtara.vat import calc
from oman_fawtara.vat.utils import has_role, settings

APPROVER_ROLES = ("Oman VAT Approver", "System Manager")


def profile_percentage(profile) -> float:
	method = profile.method
	if method == "Full Recovery":
		return 100.0
	if method == "Blocked":
		return 0.0
	if method == "Standard Apportionment":
		return flt(profile.provisional_percentage)
	return flt(profile.recovery_percentage)


def _approved_profile(name):
	if not name:
		return None
	p = frappe.get_cached_doc("Oman VAT Recovery Profile", name)
	if p.status != "Approved" or cint(p.disabled):
		return None
	return p


def match_rule(ctx: dict, item, treatment_name: str):
	"""Highest-priority Oman VAT Recovery Rule matching the line at the tax point."""
	on = getdate(ctx["tax_point"])
	candidates = frappe.get_all(
		"Oman VAT Recovery Rule",
		filters={"enabled": 1, "effective_from": ["<=", on]},
		fields=[
			"name", "recovery_profile", "company", "expense_account", "item_code", "item_group",
			"cost_center", "supplier", "treatment", "effective_to", "priority",
		],
		order_by="priority desc, effective_from desc",
	)
	for r in candidates:
		if r.effective_to and getdate(r.effective_to) < on:
			continue
		if r.company and r.company != ctx["company"]:
			continue
		if r.expense_account and r.expense_account != item.get("expense_account"):
			continue
		if r.item_code and r.item_code != item.get("item_code"):
			continue
		if r.item_group and r.item_group != item.get("item_group"):
			continue
		if r.cost_center and r.cost_center != item.get("cost_center"):
			continue
		if r.supplier and r.supplier != ctx.get("party"):
			continue
		if r.treatment and r.treatment != treatment_name:
			continue
		profile = _approved_profile(r.recovery_profile)
		if profile:
			return profile, r.name
	return None, None


def resolve(ctx: dict, item, treatment, analysis) -> tuple[float, str | None, str]:
	"""Return (recovery_percentage, profile_name, recovery_status)."""
	if treatment.nature in ("Exempt", "Out of Scope") and not cint(treatment.is_reverse_charge):
		return 0.0, None, "Not Applicable"

	default_behaviour = treatment.input_recovery_default or "Full"
	profile, rule_ref = None, None

	# 1. Explicit line profile chosen by the user
	explicit = item.get("oman_recovery_profile")
	if explicit:
		profile = _approved_profile(explicit)
		if not profile:
			analysis.add("RECOVERY_PROFILE_NOT_APPROVED", "Error", _(
				"Row {0}: recovery profile {1} is not approved or is disabled."
			).format(item.idx, explicit), item.idx)

	# 2. Treatment-level hard block (e.g. blocked expenditure)
	if not profile and default_behaviour == "Blocked":
		pct = 0.0
		status = "Blocked"
		return _apply_override(item, pct, None, status, analysis)

	# 3. Recovery rules
	if not profile:
		profile, rule_ref = match_rule(ctx, item, treatment.name)

	# 4. Company / settings default
	if not profile:
		s = settings()
		default_name = (
			s.default_partial_recovery_profile if default_behaviour == "Partial" else s.default_recovery_profile
		)
		profile = _approved_profile(default_name)

	pct = profile_percentage(profile) if profile else 100.0
	if pct >= 100:
		status = "Recoverable"
	elif pct <= 0:
		status = "Blocked"
	else:
		status = "Partially Recoverable"

	if profile and profile.method == "Standard Apportionment":
		status = "Residual (Apportioned)"

	return _apply_override(item, pct, profile.name if profile else None, status, analysis)


def _apply_override(item, computed_pct, profile_name, status, analysis):
	"""Manual percentage overrides require an approver and a reason.

	Users cannot silently change a recovery percentage: an override needs the
	``oman_recovery_override`` flag, a reason and the Oman VAT Approver role.
	Overrides are recorded in the compliance audit trail at submission.
	"""
	if not cint(item.get("oman_recovery_override")):
		return computed_pct, profile_name, status

	requested = flt(item.get("oman_recovery_percentage"))
	if not (0 <= requested <= 100):
		analysis.add("RECOVERY_PCT_RANGE", "Error", _("Row {0}: recovery percentage must be 0–100.").format(item.idx), item.idx)
		return computed_pct, profile_name, status
	if not item.get("oman_recovery_override_reason"):
		analysis.add("RECOVERY_OVERRIDE_REASON", "Error", _(
			"Row {0}: a reason is required to override the recovery percentage.").format(item.idx), item.idx)
		return computed_pct, profile_name, status
	if not has_role(*APPROVER_ROLES):
		analysis.add("RECOVERY_OVERRIDE_ROLE", "Error", _(
			"Row {0}: only an Oman VAT Approver may override the recovery percentage.").format(item.idx), item.idx)
		return computed_pct, profile_name, status

	if requested >= 100:
		new_status = "Recoverable"
	elif requested <= 0:
		new_status = "Blocked"
	else:
		new_status = "Partially Recoverable"
	return requested, profile_name, new_status + " (Override)"


# --------------------------------------------------------------------------
# Accounting: non-recoverable VAT allocation
# --------------------------------------------------------------------------


def nonrecoverable_debit_account(doc, item, mapping) -> str:
	"""Where the non-recoverable part of input VAT is charged.

	Stock and fixed-asset lines go to the configured non-recoverable VAT
	account (their expense_account is a clearing account); service/expense
	lines go to their own expense account when the setting allows it.
	"""
	s = settings()
	is_stock = item.get("item_code") and cint(frappe.get_cached_value("Item", item.item_code, "is_stock_item"))
	is_asset = cint(item.get("is_fixed_asset"))
	if cint(s.charge_nonrecoverable_to_item_expense) and not is_stock and not is_asset and item.get("expense_account"):
		return item.expense_account
	if not mapping.nonrecoverable_vat_account:
		frappe.throw(_("Set 'Non-Recoverable VAT Account' in Oman VAT Account Mapping for {0}.").format(doc.company))
	return mapping.nonrecoverable_vat_account


def create_allocation(doc, mapping):
	"""Create and submit an Oman VAT Recovery Allocation for a Purchase Invoice.

	Only domestic, supplier-charged input VAT is handled here; reverse-charge
	lines split recovery inside the Oman Reverse Charge Entry.
	"""
	rows = [
		i
		for i in doc.items
		if flt(i.get("oman_nonrecoverable_vat")) and not cint(i.get("oman_reverse_charge"))
	]
	if not rows:
		return None
	alloc = frappe.new_doc("Oman VAT Recovery Allocation")
	alloc.company = doc.company
	alloc.vat_registration = doc.oman_vat_registration
	alloc.purchase_invoice = doc.name
	alloc.posting_date = doc.posting_date
	alloc.tax_point_date = doc.oman_tax_point_date
	alloc.credit_account = mapping.input_vat_account
	for i in rows:
		alloc.append(
			"items",
			{
				"invoice_item": i.name,
				"item_code": i.item_code,
				"input_vat": i.oman_input_vat,
				"recovery_percentage": i.oman_recovery_percentage,
				"recoverable_vat": i.oman_recoverable_vat,
				"nonrecoverable_vat": i.oman_nonrecoverable_vat,
				"debit_account": nonrecoverable_debit_account(doc, i, mapping),
				"cost_center": i.cost_center,
				"recovery_profile": i.get("oman_recovery_profile"),
			},
		)
	alloc.flags.ignore_permissions = True
	alloc.insert()
	alloc.submit()
	return alloc


def make_journal_entry(*, company, posting_date, lines, remark, source_doctype, source_name, cost_center=None):
	"""Create and submit a balanced Journal Entry from [(account, debit, credit, cost_center)]."""
	from oman_fawtara.vat.calc import D, round_money

	debit = sum(D(l[1]) for l in lines)
	credit = sum(D(l[2]) for l in lines)
	if round_money(debit - credit) != 0:
		frappe.throw(_("Internal error: unbalanced VAT journal ({0} vs {1}).").format(debit, credit))
	je = frappe.new_doc("Journal Entry")
	je.voucher_type = "Journal Entry"
	je.company = company
	je.posting_date = posting_date
	je.user_remark = remark
	je.oman_vat_source_doctype = source_doctype
	je.oman_vat_source_name = source_name
	default_cc = cost_center or frappe.get_cached_value("Company", company, "cost_center")
	for account, dr, cr, cc in lines:
		if not flt(dr) and not flt(cr):
			continue
		je.append(
			"accounts",
			{
				"account": account,
				"debit_in_account_currency": flt(dr),
				"credit_in_account_currency": flt(cr),
				"cost_center": cc or default_cc,
			},
		)
	je.flags.ignore_permissions = True
	je.flags.oman_vat_system_entry = True
	je.insert()
	je.submit()
	return je


def cancel_linked(doctype: str, link_field: str, value: str):
	for name in frappe.get_all(doctype, filters={link_field: value, "docstatus": 1}, pluck="name"):
		d = frappe.get_doc(doctype, name)
		d.flags.ignore_permissions = True
		d.cancel()


def cancel_journal(je_name: str | None):
	if je_name and frappe.db.get_value("Journal Entry", je_name, "docstatus") == 1:
		je = frappe.get_doc("Journal Entry", je_name)
		je.flags.ignore_permissions = True
		je.flags.oman_vat_system_entry = True
		je.cancel()


__all__ = ["resolve", "create_allocation", "make_journal_entry", "cancel_linked", "cancel_journal", "calc"]
