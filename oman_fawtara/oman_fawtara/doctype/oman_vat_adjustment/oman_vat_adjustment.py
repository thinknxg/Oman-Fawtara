# Copyright (c) 2026, thinkNXG and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from oman_fawtara import audit
from oman_fawtara.vat import adjustments, period, transaction
from oman_fawtara.vat.recovery import cancel_journal
from oman_fawtara.vat.utils import get_period_for


class OmanVATAdjustment(Document):
	def validate(self):
		adjustments.validate_adjustment(self)
		p = get_period_for(self.vat_registration, self.posting_date)
		self.vat_period = p.name if p else None

	def before_submit(self):
		period.assert_open(self.company, self.vat_registration, self.posting_date)
		self.approved_by = frappe.session.user

	def on_submit(self):
		je = adjustments.post_adjustment(self)
		if je:
			self.db_set("journal_entry", je.name)
		transaction.record(
			self,
			"Sales" if self.direction == "Output" else "Purchase",
			adjustments.adjustment_lines(self),
			tax_point=self.posting_date,
			registration=self.vat_registration,
			is_adjustment=True,
			original={"doctype": self.original_doctype, "name": self.original_name} if self.original_name else None,
			extra={"adjustment_reason": (self.reason or "")[:140], "validation_status": "Passed"},
		)
		audit.log_event("VAT Adjustment", self.doctype, self.name,
			{"type": self.adjustment_type, "direction": self.direction, "vat": self.vat_adjustment,
			"original": self.original_name, "reason": self.reason}, self.company, self.vat_registration)

	def before_cancel(self):
		period.assert_open(self.company, self.vat_registration, self.posting_date, "cancel")

	def on_cancel(self):
		cancel_journal(self.journal_entry)
		transaction.cancel_for(self.doctype, self.name)
