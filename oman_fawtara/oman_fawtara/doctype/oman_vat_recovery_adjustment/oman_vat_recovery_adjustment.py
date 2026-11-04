# Copyright (c) 2026, thinkNXG and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from oman_fawtara import audit
from oman_fawtara.vat import calc, period, transaction
from oman_fawtara.vat.recovery import cancel_journal, make_journal_entry
from oman_fawtara.vat.utils import get_account_mapping


class OmanVATRecoveryAdjustment(Document):
	"""Annual true-up of residual input VAT recovered on a provisional ratio."""

	def validate(self):
		self.compute()

	@frappe.whitelist()
	def compute(self):
		args = (self.vat_registration, self.period_from, self.period_to)
		self.taxable_supplies = flt(frappe.db.sql(
			"""select coalesce(sum(d.taxable_amount),0) from `tabOman VAT Transaction` t
			join `tabOman VAT Transaction Detail` d on d.parent=t.name
			join `tabOman VAT Treatment` tr on tr.name=d.treatment
			where t.vat_registration=%s and t.status='Active' and t.direction='Sales'
			and tr.nature in ('Standard Rated','Zero Rated') and t.tax_point_date between %s and %s""", args)[0][0])
		self.exempt_supplies = flt(frappe.db.sql(
			"""select coalesce(sum(d.taxable_amount),0) from `tabOman VAT Transaction` t
			join `tabOman VAT Transaction Detail` d on d.parent=t.name
			join `tabOman VAT Treatment` tr on tr.name=d.treatment
			where t.vat_registration=%s and t.status='Active' and t.direction='Sales'
			and tr.nature='Exempt' and t.tax_point_date between %s and %s""", args)[0][0])
		self.actual_ratio = float(calc.apportionment_ratio(self.taxable_supplies, self.taxable_supplies + self.exempt_supplies))
		res = frappe.db.sql(
			"""select coalesce(sum(d.input_vat),0), coalesce(sum(d.recoverable_vat),0) from `tabOman VAT Transaction` t
			join `tabOman VAT Transaction Detail` d on d.parent=t.name
			where t.vat_registration=%s and t.status='Active' and d.recovery_profile=%s
			and t.tax_point_date between %s and %s""",
			(self.vat_registration, self.recovery_profile, self.period_from, self.period_to),
		)[0]
		self.residual_input_vat = flt(res[0])
		self.provisionally_recovered = flt(res[1])
		self.provisional_ratio = flt(frappe.db.get_value("Oman VAT Recovery Profile", self.recovery_profile, "provisional_percentage"))
		self.actually_recoverable = float(calc.split_recovery(self.residual_input_vat, self.actual_ratio)[0])
		self.adjustment_amount = float(calc.round_money(flt(self.actually_recoverable) - flt(self.provisionally_recovered)))
		return self.as_dict()

	def before_submit(self):
		period.assert_open(self.company, self.vat_registration, self.posting_date)

	def on_submit(self):
		amt = flt(self.adjustment_amount)
		m = get_account_mapping(self.company, self.vat_registration)
		contra = self.contra_account or m.nonrecoverable_vat_account
		if self.post_journal_entry and amt:
			if not contra:
				frappe.throw(_("Set a contra account or the Non-Recoverable VAT Account."))
			lines = [(m.input_vat_account, amt, 0, None), (contra, 0, amt, None)] if amt > 0 else \
				[(contra, -amt, 0, None), (m.input_vat_account, 0, -amt, None)]
			je = make_journal_entry(company=self.company, posting_date=self.posting_date, lines=lines,
				remark=_("Annual input VAT apportionment adjustment {0}").format(self.name),
				source_doctype=self.doctype, source_name=self.name)
			self.db_set("journal_entry", je.name)
		transaction.record(self, "Purchase", [{
			"row": None, "item_code": None, "treatment": None, "vat_code": None, "rate": 0, "rate_ref": None,
			"supply_category": None, "taxable": 0, "output_vat": 0, "input_vat": amt, "recovery_pct": 100,
			"recoverable": amt, "nonrecoverable": 0, "rcm_output": 0, "reverse_charge": 0, "is_import": 0,
			"recovery_status": "Annual Adjustment",
		}], tax_point=self.posting_date, registration=self.vat_registration, is_adjustment=True,
			extra={"adjustment_reason": "Annual apportionment", "validation_status": "Passed"})
		if self.update_profile_provisional:
			p = frappe.get_doc("Oman VAT Recovery Profile", self.recovery_profile)
			p.flags.oman_system = True
			p.provisional_percentage = self.actual_ratio
			p.save(ignore_permissions=True)
		audit.log_event("Recovery Apportionment Adjustment", self.doctype, self.name,
			{"actual_ratio": self.actual_ratio, "provisional_ratio": self.provisional_ratio, "adjustment": amt},
			self.company, self.vat_registration)

	def on_cancel(self):
		cancel_journal(self.journal_entry)
		transaction.cancel_for(self.doctype, self.name)
