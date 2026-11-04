# Copyright (c) 2026, thinkNXG and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from oman_fawtara import audit


class OmanVATPeriodLock(Document):
	def before_submit(self):
		p = frappe.get_doc("Oman VAT Period", self.vat_period)
		if p.status not in ("Filed", "Finalized"):
			frappe.throw(_("Only finalized or filed periods can be locked (period {0} is {1}).").format(p.name, p.status))
		self.locked_by = frappe.session.user
		self.lock_date = now_datetime()

	def on_submit(self):
		frappe.db.set_value("Oman VAT Period", self.vat_period,
			{"status": "Locked", "locked_by": self.locked_by, "locked_on": self.lock_date})
		ret = frappe.db.get_value("Oman VAT Period", self.vat_period, "vat_return")
		if ret:
			frappe.db.set_value("Oman VAT Return", ret, "status", "Locked")
		audit.log_event("VAT Period Locked", self.doctype, self.name, {"period": self.vat_period, "note": self.lock_reason},
			self.company, self.vat_registration)

	def before_cancel(self):
		if not (self.unlock_reason or "").strip():
			frappe.throw(_("Enter a Reopen Reason before cancelling a period lock."))
		frappe.only_for(("Oman VAT Approver", "System Manager"))

	def on_cancel(self):
		ret = frappe.db.get_value("Oman VAT Period", self.vat_period, "vat_return")
		filed = ret and frappe.db.get_value("Oman VAT Return", ret, "filing_record")
		frappe.db.set_value("Oman VAT Period", self.vat_period, {"status": "Filed" if filed else "Finalized"})
		if ret:
			frappe.db.set_value("Oman VAT Return", ret, "status", "Filed" if filed else "Finalized")
		audit.log_event("VAT Period Reopened", self.doctype, self.name, {"period": self.vat_period, "reason": self.unlock_reason},
			self.company, self.vat_registration)
