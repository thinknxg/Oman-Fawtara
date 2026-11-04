# Copyright (c) 2026, thinkNXG and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class OmanVATEvidence(Document):
	def validate(self):
		before = self.get_doc_before_save()
		if self.status == "Verified" and (not before or before.status != "Verified"):
			frappe.only_for(("Oman VAT Manager", "Oman VAT Approver", "System Manager"))
			self.verified_by = frappe.session.user
			self.verified_on = now_datetime()
		if not self.company and self.reference_doctype and self.reference_name:
			self.company = frappe.db.get_value(self.reference_doctype, self.reference_name, "company")
