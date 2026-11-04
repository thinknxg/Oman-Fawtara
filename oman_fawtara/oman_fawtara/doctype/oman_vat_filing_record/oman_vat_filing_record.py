# Copyright (c) 2026, thinkNXG and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from oman_fawtara import audit


class OmanVATFilingRecord(Document):
	def validate(self):
		ret = frappe.db.get_value("Oman VAT Return", self.vat_return, ["docstatus", "status", "net_vat"], as_dict=True)
		if not ret or ret.docstatus != 1:
			frappe.throw(_("The VAT return must be finalized before it can be filed."))
		self.net_vat = ret.net_vat
		if self.is_new():
			if frappe.db.exists("Oman VAT Filing Record", {"vat_return": self.vat_return}):
				frappe.throw(_("A filing record already exists for {0}.").format(self.vat_return))
			self.filed_by = frappe.session.user

	def after_insert(self):
		ret = frappe.get_doc("Oman VAT Return", self.vat_return)
		ret.db_set({
			"status": "Filed",
			"filing_record": self.name,
			"filing_reference": self.filing_reference,
			"filing_date": self.filing_date,
			"acknowledgement_reference": self.acknowledgement_reference,
			"payment_reference": self.payment_reference,
			"payment_date": self.payment_date,
		})
		frappe.db.set_value("Oman VAT Period", ret.vat_period, "status", "Filed")
		audit.log_event("VAT Return Filed", self.doctype, self.name,
			{"return": self.vat_return, "reference": self.filing_reference, "snapshot_hash": ret.snapshot_hash},
			self.company, self.vat_registration)

	def on_update(self):
		if not self.is_new():
			frappe.db.set_value("Oman VAT Return", self.vat_return, {
				"acknowledgement_reference": self.acknowledgement_reference,
				"payment_reference": self.payment_reference,
				"payment_date": self.payment_date,
			})

	def on_trash(self):
		frappe.throw(_("Filing records cannot be deleted."))
