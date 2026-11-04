"""Immutable, hash-chained compliance audit trail.

Every compliance event (VAT analysis result at submission, recovery
override, reverse-charge posting, period lock, return finalisation, Fawtara
submission/acceptance/rejection, ...) is appended to ``Oman Compliance Audit
Log``. Each entry stores the SHA-256 of its canonical payload chained to the
previous entry's hash, so any later tampering with a row breaks the chain and
is detected by :func:`verify_chain`.
"""

from __future__ import annotations

import frappe
from frappe.utils import now_datetime

from oman_fawtara.vat.calc import canonical_json, chain_hash


def log_event(event_type: str, reference_doctype: str | None = None, reference_name: str | None = None,
		payload: dict | None = None, company: str | None = None, vat_registration: str | None = None):
	payload = payload or {}
	# Serialise writers so the chain stays linear under concurrency.
	frappe.db.sql("SELECT GET_LOCK('oman_fawtara_audit_chain', 10)")
	try:
		last = frappe.db.sql(
			"select entry_hash from `tabOman Compliance Audit Log` order by sequence desc limit 1",
			as_dict=True,
		)
		prev = last[0].entry_hash if last else None
		seq = (frappe.db.sql("select coalesce(max(sequence), 0) from `tabOman Compliance Audit Log`")[0][0] or 0) + 1
		ts = now_datetime()
		body = {
			"sequence": seq,
			"event_type": event_type,
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
			"company": company,
			"vat_registration": vat_registration,
			"user": frappe.session.user,
			"timestamp": str(ts),
			"payload": payload,
		}
		doc = frappe.new_doc("Oman Compliance Audit Log")
		doc.update(
			{
				"sequence": seq,
				"event_type": event_type,
				"reference_doctype": reference_doctype,
				"reference_name": reference_name,
				"company": company,
				"vat_registration": vat_registration,
				"event_user": frappe.session.user,
				"event_timestamp": ts,
				"payload": canonical_json(payload),
				"previous_hash": prev,
				"entry_hash": chain_hash(prev, body),
			}
		)
		doc.flags.ignore_permissions = True
		doc.flags.oman_audit_insert = True
		doc.insert()
		return doc.name
	finally:
		frappe.db.sql("SELECT RELEASE_LOCK('oman_fawtara_audit_chain')")


@frappe.whitelist()
def verify_chain(limit: int | None = None) -> dict:
	"""Recompute every link of the chain; return the first broken sequence, if any."""
	frappe.only_for(("Oman VAT Manager", "Oman VAT Approver", "System Manager"))
	rows = frappe.db.sql(
		"""select sequence, event_type, reference_doctype, reference_name, company, vat_registration,
		event_user, event_timestamp, payload, previous_hash, entry_hash
		from `tabOman Compliance Audit Log` order by sequence asc""",
		as_dict=True,
	)
	prev = None
	checked = 0
	for r in rows:
		body = {
			"sequence": r.sequence,
			"event_type": r.event_type,
			"reference_doctype": r.reference_doctype,
			"reference_name": r.reference_name,
			"company": r.company,
			"vat_registration": r.vat_registration,
			"user": r.event_user,
			"timestamp": str(r.event_timestamp),
			"payload": frappe.parse_json(r.payload) if r.payload else {},
		}
		if r.previous_hash != prev or chain_hash(prev, body) != r.entry_hash:
			return {"valid": False, "broken_at": r.sequence, "checked": checked}
		prev = r.entry_hash
		checked += 1
	return {"valid": True, "checked": checked}
