"""Immutability guards for system-generated compliance records."""

import frappe
from frappe import _


def immutable_validate(doc):
	"""Allow inserts by the system; refuse any later edit through the ORM."""
	if doc.is_new():
		return
	if doc.flags.get("oman_system"):
		return
	frappe.throw(_("{0} records are immutable compliance records and cannot be edited.").format(_(doc.doctype)))


def immutable_trash(doc):
	frappe.throw(_("{0} records cannot be deleted.").format(_(doc.doctype)))
