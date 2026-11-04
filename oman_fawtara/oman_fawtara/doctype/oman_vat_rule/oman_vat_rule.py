# Copyright (c) 2026, thinkNXG and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, now_datetime

# Once approved, only these fields may change (closing a rule's validity or retiring it).
MUTABLE_AFTER_APPROVAL = {"effective_to", "status", "enabled", "notes", "modified", "modified_by"}


class OmanVATRule(Document):
	def validate(self):
		if self.effective_to and getdate(self.effective_to) < getdate(self.effective_from):
			frappe.throw(_("Effective To cannot be before Effective From."))
		before = self.get_doc_before_save()
		if self.status == "Approved" and (not before or before.status != "Approved"):
			if not frappe.flags.in_install and not frappe.flags.in_migrate:
				frappe.only_for(("Oman VAT Approver", "System Manager"))
			self.approved_by = frappe.session.user
			self.approved_on = now_datetime()
		if before and before.status == "Approved" and not frappe.flags.in_migrate:
			changed = [
				df.fieldname for df in self.meta.fields
				if df.fieldname not in MUTABLE_AFTER_APPROVAL and str(self.get(df.fieldname) or "") != str(before.get(df.fieldname) or "")
			]
			if changed:
				frappe.throw(_("Approved rules are versioned: close this rule with an Effective To date and create a new rule instead of changing {0}.").format(", ".join(changed)))

	def on_trash(self):
		if self.status == "Approved":
			frappe.throw(_("Approved rules cannot be deleted; retire them instead."))
