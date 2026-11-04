# Copyright (c) 2026, thinkNXG and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import flt

from oman_fawtara.vat import reconciliation


class OmanVATReconciliation(Document):
	def validate(self):
		if self.vat_period and not (self.from_date and self.to_date):
			self.from_date, self.to_date = frappe.db.get_value("Oman VAT Period", self.vat_period, ["from_date", "to_date"])
		if not self.items:
			self.compute()
		self.total_difference = sum(abs(flt(i.difference)) for i in self.items)
		tol = flt(frappe.db.get_single_value("Oman VAT Settings", "reconciliation_tolerance") or 0.01)
		self.status = "Reconciled" if all(abs(flt(i.difference)) <= tol for i in self.items) else "Differences"

	@frappe.whitelist()
	def compute(self):
		notes = {i.account: i.explanation for i in self.items}
		self.set("items", [])
		for r in reconciliation.compute(self.company, self.vat_registration, self.from_date, self.to_date):
			self.append("items", {**r, "explanation": notes.get(r["account"])})
		return self.items
