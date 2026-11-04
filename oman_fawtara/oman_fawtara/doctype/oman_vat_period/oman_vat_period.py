# Copyright (c) 2026, thinkNXG and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate


class OmanVATPeriod(Document):
	def validate(self):
		if getdate(self.to_date) < getdate(self.from_date):
			frappe.throw(_("Period end is before period start."))
		overlap = frappe.db.sql(
			"""select name from `tabOman VAT Period` where vat_registration=%s and name!=%s
			and from_date <= %s and to_date >= %s""",
			(self.vat_registration, self.name or "", self.to_date, self.from_date),
		)
		if overlap:
			frappe.throw(_("Overlaps with VAT period {0}.").format(overlap[0][0]))

	def on_trash(self):
		if self.status != "Open" or frappe.db.exists("Oman VAT Transaction", {"vat_period": self.name}):
			frappe.throw(_("Periods with transactions or returns cannot be deleted."))
