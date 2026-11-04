# Copyright (c) 2026, thinkNXG and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from oman_fawtara import audit
from oman_fawtara.vat import imports, period, transaction
from oman_fawtara.vat.recovery import cancel_journal


class OmanImportDeclaration(Document):
	def validate(self):
		imports.validate_declaration(self)

	def before_submit(self):
		period.assert_open(self.company, self.vat_registration, self.clearance_date or self.declaration_date)

	def on_submit(self):
		je = imports.post_declaration(self)
		if je:
			self.db_set("journal_entry", je.name)
		tp = self.clearance_date or self.declaration_date
		self.posting_date = tp
		transaction.record(self, "Purchase", imports.declaration_lines(self), party_type="Supplier" if self.supplier else None,
			party=self.supplier, tax_point=tp, registration=self.vat_registration,
			extra={"validation_status": "Passed"})
		for row in self.invoices:
			frappe.db.set_value("Purchase Invoice", row.purchase_invoice, "oman_import_declaration", self.name,
				update_modified=False)
		audit.log_event("Import Declaration Submitted", self.doctype, self.name,
			{"bayan": self.declaration_number, "import_vat": self.import_vat, "method": self.payment_method},
			self.company, self.vat_registration)

	def before_cancel(self):
		period.assert_open(self.company, self.vat_registration, self.clearance_date or self.declaration_date, "cancel")

	def on_cancel(self):
		cancel_journal(self.journal_entry)
		transaction.cancel_for(self.doctype, self.name)
