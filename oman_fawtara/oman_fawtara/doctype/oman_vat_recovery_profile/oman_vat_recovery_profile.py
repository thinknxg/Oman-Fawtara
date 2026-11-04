# Copyright (c) 2026, thinkNXG and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, now_datetime


class OmanVATRecoveryProfile(Document):
	def validate(self):
		for f in ("recovery_percentage", "provisional_percentage"):
			if not 0 <= flt(self.get(f)) <= 100:
				frappe.throw(_("{0} must be between 0 and 100.").format(self.meta.get_label(f)))
		before = self.get_doc_before_save()
		if self.status == "Approved" and (not before or before.status != "Approved"):
			if not frappe.flags.in_install:
				frappe.only_for(("Oman VAT Approver", "System Manager"))
			self.approved_by = frappe.session.user
			self.approved_on = now_datetime()
		if before and before.status == "Approved" and self.status == "Approved" and not self.flags.get("oman_system"):
			for f in ("method", "recovery_percentage", "provisional_percentage"):
				if flt(self.get(f)) != flt(before.get(f)) if f != "method" else self.method != before.method:
					frappe.throw(_("Approved recovery profiles cannot be changed; retire it and approve a new profile, "
						"or use an Oman VAT Recovery Adjustment for annual apportionment."))
