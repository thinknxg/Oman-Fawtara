# Copyright (c) 2026, thinkNXG and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, now_datetime

from oman_fawtara import audit
from oman_fawtara.vat import returns
from oman_fawtara.vat.utils import has_role

REVIEWERS = ("Oman VAT Manager", "Oman VAT Approver", "System Manager")


class OmanVATReturn(Document):
	def validate(self):
		p = frappe.db.get_value("Oman VAT Period", self.vat_period, ["vat_registration", "from_date", "to_date", "status"], as_dict=True)
		if p.vat_registration != self.vat_registration:
			frappe.throw(_("Period {0} does not belong to registration {1}.").format(self.vat_period, self.vat_registration))
		self.from_date, self.to_date = p.from_date, p.to_date
		dup = frappe.db.get_value("Oman VAT Return", {"vat_period": self.vat_period, "docstatus": ["<", 2], "name": ["!=", self.name]})
		if dup:
			frappe.throw(_("VAT return {0} already exists for this period.").format(dup))
		if self.is_new():
			self.prepared_by = frappe.session.user
			self.status = "Open"

	def after_insert(self):
		frappe.db.set_value("Oman VAT Period", self.vat_period, {"status": "Under Review", "vat_return": self.name})

	@frappe.whitelist()
	def collect_transactions(self):
		self.check_permission("write")
		returns.collect(self)
		self.status = "Open"
		self.reviewed_by = None
		self.save()
		return {"transactions": self.transaction_count, "lines": len(self.details)}

	@frappe.whitelist()
	def run_validation(self):
		self.check_permission("write")
		returns.collect(self)
		issues = returns.validate_return(self)
		self.status = "Validation"
		self.reviewed_by = None
		self.save()
		return issues

	@frappe.whitelist()
	def mark_reviewed(self, notes=None):
		if not has_role(*REVIEWERS):
			frappe.throw(_("Only an Oman VAT Manager can review a return."), frappe.PermissionError)
		if self.status != "Validation":
			frappe.throw(_("Run validation before review."))
		if cint(self.validation_errors):
			frappe.throw(_("Resolve {0} validation error(s) before review.").format(self.validation_errors))
		if cint(self.validation_warnings) and not cint(self.waive_warnings):
			frappe.throw(_("Review the warnings and tick 'Warnings Reviewed and Accepted'."))
		self.status = "Reviewed"
		self.reviewed_by = frappe.session.user
		self.reviewed_on = now_datetime()
		if notes:
			self.review_notes = notes
		self.save()
		audit.log_event("VAT Return Reviewed", self.doctype, self.name,
			{"net_vat": flt(self.net_vat), "warnings": self.validation_warnings}, self.company, self.vat_registration)

	def before_submit(self):
		if self.status != "Reviewed":
			frappe.throw(_("The return must be reviewed before it can be finalized."))
		returns.assert_segregation(self)
		# The ledger must not have moved since review.
		before_net, before_lines = flt(self.net_vat), len(self.details)
		returns.collect(self)
		if abs(flt(self.net_vat) - before_net) > 0.0005 or len(self.details) != before_lines:
			frappe.throw(_("Transactions changed after review (net VAT {0} → {1}). Re-run validation and review.").format(
				before_net, self.net_vat))

	def on_submit(self):
		returns.finalize(self)

	def before_cancel(self):
		if self.filing_record:
			frappe.throw(_("A filed return cannot be cancelled. Correct errors through adjustments in an open period."))
		if not has_role("Oman VAT Approver", "System Manager"):
			frappe.throw(_("Only an Oman VAT Approver can cancel a finalized return."), frappe.PermissionError)

	def on_cancel(self):
		frappe.db.sql("update `tabOman VAT Transaction` set vat_return=NULL where vat_return=%s", self.name)
		frappe.db.set_value("Oman VAT Period", self.vat_period, {"status": "Under Review"})
		self.db_set("status", "Open")
		audit.log_event("VAT Return Cancelled", self.doctype, self.name, {"snapshot": self.snapshot},
			self.company, self.vat_registration)

	def on_trash(self):
		if frappe.db.get_value("Oman VAT Period", self.vat_period, "vat_return") == self.name:
			frappe.db.set_value("Oman VAT Period", self.vat_period, {"status": "Open", "vat_return": None})

	@frappe.whitelist()
	def verify_snapshot(self):
		if not self.snapshot:
			frappe.throw(_("No snapshot."))
		return returns.verify_snapshot(self.snapshot)

	@frappe.whitelist()
	def lock_period(self, note):
		frappe.only_for(("Oman VAT Approver", "System Manager"))
		lock = frappe.get_doc({"doctype": "Oman VAT Period Lock", "vat_period": self.vat_period, "lock_reason": note})
		lock.insert()
		lock.submit()
		return lock.name
