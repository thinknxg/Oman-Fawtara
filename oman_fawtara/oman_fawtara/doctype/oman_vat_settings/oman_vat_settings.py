# Copyright (c) 2026, thinkNXG and contributors
# For license information, please see license.txt

import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


class OmanVATSettings(Document):
	def validate(self):
		try:
			re.compile(self.vrn_pattern or "")
		except re.error as e:
			frappe.throw(_("Invalid VAT number pattern: {0}").format(e))
		before = self.get_doc_before_save()
		if self.legal_review_confirmed and (not before or not before.legal_review_confirmed):
			frappe.only_for(("Oman VAT Approver", "System Manager"))
			if not self.legal_review_notes:
				frappe.throw(_("Record the specialist review reference in Review Notes."))
			self.legal_reviewed_by = frappe.session.user
			self.legal_reviewed_on = now_datetime()
			from oman_fawtara import audit

			audit.log_event("Legal Rule-set Confirmed", self.doctype, self.name,
				{"ruleset": self.active_ruleset_version, "notes": self.legal_review_notes})

	def on_update(self):
		frappe.clear_document_cache(self.doctype, self.name)
