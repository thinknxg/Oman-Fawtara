# Copyright (c) 2026, thinkNXG and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from oman_fawtara.guards import immutable_trash, immutable_validate


class OmanVATTransaction(Document):
	def validate(self):
		immutable_validate(self)

	def on_trash(self):
		immutable_trash(self)
