# Copyright (c) 2026, thinkNXG and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from oman_fawtara.vat.recovery import cancel_journal, make_journal_entry


class OmanVATRecoveryAllocation(Document):
	def validate(self):
		self.total_nonrecoverable = sum(flt(i.nonrecoverable_vat) for i in self.items)

	def on_submit(self):
		lines = [(i.debit_account, i.nonrecoverable_vat, 0, i.cost_center) for i in self.items if flt(i.nonrecoverable_vat)]
		lines.append((self.credit_account, 0, self.total_nonrecoverable, None))
		je = make_journal_entry(
			company=self.company,
			posting_date=self.posting_date,
			lines=lines,
			remark=_("Non-recoverable input VAT on {0}").format(self.purchase_invoice),
			source_doctype=self.doctype,
			source_name=self.name,
		)
		self.db_set("journal_entry", je.name)

	def on_cancel(self):
		cancel_journal(self.journal_entry)
