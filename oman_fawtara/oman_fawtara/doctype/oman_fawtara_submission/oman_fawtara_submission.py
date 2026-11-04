# Copyright (c) 2026, thinkNXG and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class OmanFawtaraSubmission(Document):
	def validate(self):
		if not self.is_new() and not self.flags.get("oman_system"):
			frappe.throw(_("Submissions are maintained by the Fawtara queue. Use Retry or Resubmit."))

	def on_trash(self):
		if self.status not in ("Draft", "Cancelled"):
			frappe.throw(_("Only draft or cancelled submissions can be deleted."))

	@frappe.whitelist()
	def retry(self):
		from oman_fawtara.fawtara.queue import retry_now

		return retry_now(self.name)

	@frappe.whitelist()
	def resubmit(self, reason):
		from oman_fawtara.fawtara.queue import resubmit

		return resubmit(self.name, reason)

	@frappe.whitelist()
	def refresh_status(self):
		frappe.only_for(("Fawtara Manager", "Fawtara Operator", "System Manager"))
		from oman_fawtara.fawtara.queue import _envelope, apply_result, _ota_updates
		from oman_fawtara.fawtara.providers import get_adapter

		if not self.provider_reference:
			frappe.throw(_("No provider reference yet."))
		res = get_adapter(self.provider).get_status(self.provider_reference, _envelope(self))
		if self.status == "Processing" and res.outcome in ("accepted", "rejected"):
			apply_result(self, res)
		else:
			upd = _ota_updates(self, res, frappe.utils.now_datetime())
			if upd:
				self.db_set(upd)
		return res.ota_status
