# Copyright (c) 2026, thinkNXG and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class OmanFawtaraSettings(Document):
	def validate(self):
		if self.enabled and not self.default_provider:
			frappe.throw(_("Select a default service provider before enabling Fawtara."))
		if self.default_provider and not frappe.db.get_value("Oman Fawtara Provider", self.default_provider, "enabled"):
			frappe.throw(_("Provider {0} is disabled.").format(self.default_provider))
		if self.phase_1_date and self.phase_2_date and self.phase_1_date > self.phase_2_date:
			frappe.throw(_("Phase 1 date must not be after Phase 2 date."))

	def on_update(self):
		frappe.clear_document_cache(self.doctype, self.name)
