# Copyright (c) 2026, thinkNXG and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate

from oman_fawtara.vat.calc import ranges_overlap, vrn_is_valid


class OmanVATRegistration(Document):
	def validate(self):
		self.vatin = (self.vatin or "").strip().upper()
		pattern = frappe.db.get_single_value("Oman VAT Settings", "vrn_pattern")
		if not vrn_is_valid(self.vatin, pattern):
			frappe.throw(_("VAT registration number {0} does not match the configured pattern {1}.").format(self.vatin, pattern))
		if self.effective_to and getdate(self.effective_to) < getdate(self.effective_from):
			frappe.throw(_("Effective To cannot be before Effective From."))
		for other in frappe.get_all(
			"Oman VAT Registration",
			filters={"company": self.company, "name": ["!=", self.name], "status": ["!=", "Deregistered"]},
			fields=["name", "effective_from", "effective_to"],
		):
			if ranges_overlap(getdate(self.effective_from), getdate(self.effective_to) if self.effective_to else None,
					getdate(other.effective_from) if other.effective_from else None,
					getdate(other.effective_to) if other.effective_to else None):
				frappe.throw(_("Validity overlaps with registration {0} for {1}.").format(other.name, self.company))
		if self.fawtara_enabled and frappe.db.exists("DocType", "Oman Fawtara Settings"):
			from oman_fawtara.fawtara.applicability import mandate_date

			self.fawtara_mandate_date = mandate_date(self)

	def after_insert(self):
		if not frappe.db.exists("Oman VAT Period", {"vat_registration": self.name}):
			from oman_fawtara.vat.period import generate_periods

			generate_periods(self.name, count=4)

	@frappe.whitelist()
	def generate_periods(self, count=4):
		from oman_fawtara.vat.period import generate_periods

		frappe.only_for(("Oman VAT Manager", "Oman VAT Approver", "System Manager"))
		return generate_periods(self.name, count=int(count))
