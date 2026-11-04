# Copyright (c) 2026, thinkNXG and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

ACCOUNT_FIELDS = (
	"output_vat_account", "input_vat_account", "rcm_output_vat_account", "rcm_input_vat_account",
	"import_vat_account", "import_vat_payable_account", "customs_vat_clearing_account",
	"nonrecoverable_vat_account", "vat_adjustment_account",
)


class OmanVATAccountMapping(Document):
	def validate(self):
		for f in ACCOUNT_FIELDS:
			acc = self.get(f)
			if acc and frappe.db.get_value("Account", acc, "company") != self.company:
				frappe.throw(_("{0} {1} does not belong to company {2}.").format(self.meta.get_label(f), acc, self.company))
		if not self.disabled:
			dup = frappe.db.get_value("Oman VAT Account Mapping", {"company": self.company, "disabled": 0,
				"vat_registration": self.vat_registration or ["is", "not set"], "name": ["!=", self.name]})
			if dup:
				frappe.throw(_("An active mapping already exists: {0}").format(dup))

	def on_update(self):
		frappe.clear_document_cache(self.doctype, self.name)
