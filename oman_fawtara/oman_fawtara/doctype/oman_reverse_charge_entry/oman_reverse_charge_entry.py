# Copyright (c) 2026, thinkNXG and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import flt

from oman_fawtara import audit
from oman_fawtara.vat.recovery import cancel_journal
from oman_fawtara.vat.reverse_charge import post_entry_journal
from oman_fawtara.vat.utils import get_account_mapping


class OmanReverseChargeEntry(Document):
	def validate(self):
		self.total_output_vat = sum(flt(i.output_vat) for i in self.items)
		self.total_recoverable = sum(flt(i.recoverable_vat) for i in self.items)

	def on_submit(self):
		je = post_entry_journal(self, get_account_mapping(self.company, self.vat_registration))
		self.db_set("journal_entry", je.name)
		audit.log_event("Reverse Charge Self-assessed", self.doctype, self.name,
			{"purchase_invoice": self.purchase_invoice, "output_vat": self.total_output_vat,
			"recoverable": self.total_recoverable, "journal": je.name}, self.company, self.vat_registration)

	def on_cancel(self):
		cancel_journal(self.journal_entry)
