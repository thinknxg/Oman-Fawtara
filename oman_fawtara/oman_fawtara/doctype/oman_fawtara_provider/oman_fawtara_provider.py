# Copyright (c) 2026, thinkNXG and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from oman_fawtara.fawtara.providers import available_adapters, get_adapter


class OmanFawtaraProvider(Document):
	def validate(self):
		if self.adapter not in available_adapters():
			frappe.throw(_("Unknown adapter {0}. Available: {1}").format(self.adapter, ", ".join(available_adapters())))
		if self.environment == "Production":
			if self.adapter == "Sandbox (Simulated)":
				frappe.throw(_("The simulated sandbox adapter cannot be used in Production."))
			if self.enabled and not frappe.db.get_single_value("Oman VAT Settings", "legal_review_confirmed"):
				frappe.throw(_("Production providers can only be enabled after the legal rule-set review is confirmed "
					"in Oman VAT Settings (incorporating Decision 189/2026)."))
			if not self.accreditation_number:
				frappe.throw(_("Enter the OTA accreditation number of the production service provider."))
			if self.base_url and not self.base_url.startswith("https://"):
				frappe.throw(_("Production endpoints must use HTTPS."))

	@frappe.whitelist()
	def test_connection(self):
		frappe.only_for(("Fawtara Manager", "Fawtara Operator", "System Manager"))
		ok, msg = get_adapter(self.name).ping()
		self.db_set({"last_check_at": frappe.utils.now_datetime(), "last_check_ok": 1 if ok else 0,
			"last_check_message": (msg or "")[:500]})
		return {"ok": ok, "message": msg}
