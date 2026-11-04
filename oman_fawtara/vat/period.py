"""VAT period management: generation, open/closed checks, locking."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import add_days, add_months, getdate

from oman_fawtara.vat.utils import get_period_for, get_registration, has_role

CLOSED = ("Finalized", "Filed", "Locked")


def assert_open(company: str, registration: str | None, on_date, action: str = "post"):
	"""Throw if ``on_date`` is inside a finalized/filed/locked period."""
	reg = registration or (get_registration(company, on_date) or frappe._dict()).get("name")
	if not reg:
		return
	period = get_period_for(reg, on_date)
	if period and period.status in CLOSED:
		frappe.throw(
			_("Cannot {0}: VAT period {1} ({2}) is closed for registration {3}. "
			"Record the correction in an open period using an Oman VAT Adjustment.").format(
				action, period.name, period.status, reg),
			title=_("VAT Period Closed"),
		)


def generate_periods(registration: str, from_date=None, count: int = 4):
	"""Create the next ``count`` periods following the registration's return frequency."""
	reg = frappe.get_doc("Oman VAT Registration", registration)
	months = 1 if reg.return_frequency == "Monthly" else 3
	last = frappe.db.get_value(
		"Oman VAT Period", {"vat_registration": registration}, "to_date", order_by="to_date desc"
	)
	start = getdate(add_days(last, 1)) if last else getdate(from_date or reg.first_period_start or reg.effective_from)
	created = []
	for _i in range(count):
		end = getdate(add_days(add_months(start, months), -1))
		p = frappe.new_doc("Oman VAT Period")
		p.vat_registration = registration
		p.company = reg.company
		p.from_date = start
		p.to_date = end
		p.due_date = add_days(end, frappe.get_cached_value("Oman VAT Settings", None, "return_due_days") or 30)
		p.status = "Open"
		p.flags.ignore_permissions = True
		p.insert()
		created.append(p.name)
		start = add_days(end, 1)
	return created


def ensure_future_periods():
	"""Scheduler: keep at least the current and next period available."""
	today = getdate()
	for reg in frappe.get_all("Oman VAT Registration", filters={"status": "Active"}, pluck="name"):
		last = frappe.db.get_value("Oman VAT Period", {"vat_registration": reg}, "to_date", order_by="to_date desc")
		if not last or getdate(last) < add_months(today, 3):
			try:
				generate_periods(reg, count=2)
			except Exception:
				frappe.log_error(title=f"Oman VAT period generation failed for {reg}")


def set_status(period_name: str, status: str, return_name: str | None = None):
	frappe.db.set_value("Oman VAT Period", period_name, {"status": status, **({"vat_return": return_name} if return_name else {})})


def require_role(*roles):
	if not has_role(*roles):
		frappe.throw(_("Requires one of the roles: {0}").format(", ".join(roles)), frappe.PermissionError)
