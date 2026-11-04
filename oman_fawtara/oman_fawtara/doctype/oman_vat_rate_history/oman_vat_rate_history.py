# Copyright (c) 2026, thinkNXG and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate

from oman_fawtara.vat.calc import ranges_overlap


class OmanVATRateHistory(Document):
	def validate(self):
		if flt(self.rate) < 0 or flt(self.rate) > 100:
			frappe.throw(_("Rate must be between 0 and 100."))
		if self.effective_to and getdate(self.effective_to) < getdate(self.effective_from):
			frappe.throw(_("Effective To cannot be before Effective From."))
		filters = {"treatment": self.treatment, "name": ["!=", self.name]}
		filters["vat_code"] = self.vat_code if self.vat_code else ["is", "not set"]
		for o in frappe.get_all("Oman VAT Rate History", filters=filters, fields=["name", "effective_from", "effective_to"]):
			if ranges_overlap(getdate(self.effective_from), getdate(self.effective_to) if self.effective_to else None,
					getdate(o.effective_from), getdate(o.effective_to) if o.effective_to else None):
				frappe.throw(_("Overlaps with rate entry {0}. Close the earlier entry with an Effective To date first.").format(o.name))
		before = self.get_doc_before_save()
		if before and self._is_used():
			for f in ("treatment", "vat_code", "rate", "effective_from"):
				if str(self.get(f) or "") != str(before.get(f) or ""):
					frappe.throw(_("This rate has been applied to transactions; only Effective To and notes can change."))

	def _is_used(self):
		return frappe.db.exists("Oman VAT Transaction Detail", {"rate_reference": self.name})

	def on_trash(self):
		if self._is_used():
			frappe.throw(_("This rate has been applied to transactions and cannot be deleted."))
