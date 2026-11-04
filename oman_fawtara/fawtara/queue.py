"""Fawtara submission queue.

* A submission is created when an eligible invoice is submitted; the XML is
  generated and locally validated synchronously, the provider call is made
  by a background worker after commit.
* Idempotency: one active submission per (document, UUID); the idempotency key
  is unique in the database and sent to the provider on every attempt.
* Transient failures (network, timeouts, HTTP 5xx/429) → ``Retry`` with
  exponential backoff. Rejections → ``Rejected``; never retried automatically.
  A rejected document is resubmitted only by a Fawtara Manager, with a reason,
  after correction.
* Provider acceptance and OTA reporting/acknowledgement are tracked
  separately with their own statuses and timestamps.
"""

from __future__ import annotations

import time
import uuid as uuidlib

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, now_datetime

from oman_fawtara import audit
from oman_fawtara.fawtara import local_validation, mapper, xml_generator
from oman_fawtara.fawtara.applicability import fawtara_settings, is_eligible
from oman_fawtara.fawtara.providers import get_adapter
from oman_fawtara.fawtara.providers.base import (
	Envelope,
	ProviderConfigurationError,
	TransientProviderError,
)
from oman_fawtara.vat.calc import backoff_seconds, canonical_json, idempotency_key, sha256_hex

ACTIVE = ("Draft", "Pending", "Processing", "Retry", "Accepted")
FAWTARA_ROLES = ("Fawtara Manager", "System Manager")


# --------------------------------------------------------------------------
# Generation
# --------------------------------------------------------------------------


def ensure_uuid(doc) -> str:
	if not doc.get("oman_fawtara_uuid"):
		doc.oman_fawtara_uuid = str(uuidlib.uuid4())
		if doc.docstatus == 1 and doc.name:
			doc.db_set("oman_fawtara_uuid", doc.oman_fawtara_uuid, update_modified=False)
	return doc.oman_fawtara_uuid


def generate(doc) -> tuple[dict, bytes, list[dict]]:
	ensure_uuid(doc)
	inv = mapper.build(doc)
	cfg = mapper.config()
	issues = local_validation.validate_canonical(inv, cfg)
	xml = xml_generator.generate(inv, cfg)
	s = fawtara_settings()
	xsd = None
	if s.xsd_file:
		xsd = frappe.get_doc("File", {"file_url": s.xsd_file}).get_full_path()
	issues += local_validation.validate_xml(xml, xsd)
	return inv, xml, issues


def before_invoice_submit(doc):
	"""Generate + locally validate before the invoice is committed."""
	ok, _reason = is_eligible(doc)
	if not ok:
		return
	ensure_uuid(doc)
	inv, xml, issues = generate(doc)
	errors = [i for i in issues if i["severity"] == "Error"]
	doc.flags.oman_fawtara_payload = (inv, xml, issues)
	if errors and cint(fawtara_settings().block_on_local_validation_error):
		frappe.throw(
			"<br>".join(f"• [{e['code']}] {e['message']}" for e in errors),
			title=_("Fawtara e-invoice validation failed"),
		)


# --------------------------------------------------------------------------
# Lifecycle hooks
# --------------------------------------------------------------------------


def on_invoice_submit(doc):
	ok, reason = is_eligible(doc)
	if not ok:
		doc.db_set({"oman_fawtara_status": "Not Required", "oman_fawtara_note": reason}, update_modified=False)
		return None
	existing = frappe.db.get_value(
		"Oman Fawtara Submission",
		{"reference_doctype": doc.doctype, "reference_name": doc.name, "status": ["in", ACTIVE]},
	)
	if existing:
		return existing
	payload = doc.flags.get("oman_fawtara_payload")
	if not payload:
		payload = generate(doc)
	inv, xml, issues = payload
	return create_submission(doc, inv, xml, issues)


def create_submission(doc, inv, xml, issues, reason=None, supersedes=None):
	s = fawtara_settings()
	reg = frappe.get_cached_doc("Oman VAT Registration", doc.oman_vat_registration)
	provider = reg.fawtara_provider or s.default_provider
	if not provider:
		frappe.throw(_("No Fawtara provider configured for registration {0}").format(reg.name))
	errors = [i for i in issues if i["severity"] == "Error"]
	key = idempotency_key(doc.company, doc.doctype, doc.name, inv["uuid"])
	sub = frappe.new_doc("Oman Fawtara Submission")
	sub.update(
		{
			"reference_doctype": doc.doctype,
			"reference_name": doc.name,
			"company": doc.company,
			"vat_registration": doc.oman_vat_registration,
			"provider": provider,
			"document_uuid": inv["uuid"],
			"document_type": inv["document_type"],
			"invoice_number": inv["invoice_number"],
			"issue_date": inv["issue_date"],
			"transaction_type": ", ".join(k for k, v in (inv.get("flags") or {}).items() if v),
			"idempotency_key": key,
			"xml_hash": sha256_hex(xml),
			"canonical_json": canonical_json(inv),
			"status": "Draft" if errors else "Pending",
			"ota_status": "Not Reported",
			"next_attempt_at": None if errors else now_datetime(),
			"resubmission_reason": reason,
			"supersedes": supersedes,
			"local_validation": canonical_json(issues),
		}
	)
	sub.flags.ignore_permissions = True
	sub.insert()
	_save_xml(sub, xml)
	for e in issues:
		_error(sub, "Local Validation", e)
	doc.db_set(
		{"oman_fawtara_status": sub.status, "oman_fawtara_submission": sub.name},
		update_modified=False,
	)
	audit.log_event("Fawtara Submission Created", sub.doctype, sub.name,
		{"reference": doc.name, "uuid": inv["uuid"], "xml_hash": sub.xml_hash, "status": sub.status},
		doc.company, doc.oman_vat_registration)
	if sub.status == "Pending" and cint(s.submit_immediately):
		frappe.enqueue(
			"oman_fawtara.fawtara.queue.process_submission",
			queue="short",
			submission=sub.name,
			enqueue_after_commit=True,
			job_id=f"oman_fawtara::{sub.name}",
			deduplicate=True,
		)
	return sub.name


def _save_xml(sub, xml: bytes, kind: str = "Submitted XML"):
	f = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": f"{sub.invoice_number}-{sub.document_uuid}.xml",
			"attached_to_doctype": sub.doctype,
			"attached_to_name": sub.name,
			"is_private": 1,
			"content": xml,
		}
	)
	f.flags.ignore_permissions = True
	f.insert()
	if kind == "Submitted XML":
		sub.db_set("xml_file", f.file_url, update_modified=False)
	return f


def _error(sub, category, e: dict):
	frappe.get_doc(
		{
			"doctype": "Oman Fawtara Error Log",
			"submission": sub.name,
			"reference_doctype": sub.reference_doctype,
			"reference_name": sub.reference_name,
			"category": category,
			"severity": e.get("severity") or "Error",
			"error_code": e.get("code"),
			"message": (e.get("message") or "")[:1000],
			"field_path": e.get("path"),
			"attempt": sub.attempt_count,
		}
	).insert(ignore_permissions=True)


def assert_cancellable(doc):
	accepted = frappe.db.get_value(
		"Oman Fawtara Submission",
		{"reference_doctype": doc.doctype, "reference_name": doc.name, "status": ["in", ["Accepted", "Processing"]]},
		["name", "status"],
		as_dict=True,
	)
	if accepted:
		frappe.throw(
			_("{0} has been sent to Fawtara ({1}: {2}). Issue a credit note instead of cancelling.").format(
				doc.name, accepted.name, accepted.status),
			title=_("E-invoice already issued"),
		)


def on_invoice_cancel(doc):
	for name in frappe.get_all(
		"Oman Fawtara Submission",
		filters={"reference_doctype": doc.doctype, "reference_name": doc.name, "status": ["in", ["Draft", "Pending", "Retry"]]},
		pluck="name",
	):
		frappe.db.set_value("Oman Fawtara Submission", name, {"status": "Cancelled", "next_attempt_at": None})


# --------------------------------------------------------------------------
# Processing
# --------------------------------------------------------------------------


def _envelope(sub) -> Envelope:
	xml = frappe.get_doc("File", {"file_url": sub.xml_file}).get_content()
	if isinstance(xml, str):
		xml = xml.encode()
	inv = frappe.parse_json(sub.canonical_json)
	return Envelope(
		uuid=sub.document_uuid,
		idempotency_key=sub.idempotency_key,
		invoice_number=sub.invoice_number,
		document_type=sub.document_type,
		xml=xml,
		issue_date=str(sub.issue_date),
		supplier_vrn=(inv.get("supplier") or {}).get("vrn"),
		buyer_vrn=(inv.get("customer") or {}).get("vrn"),
		metadata={"flags": inv.get("flags")},
	)


def process_submission(submission: str):
	"""Send one submission to its provider. Safe to call concurrently."""
	row = frappe.db.sql(
		"select name, status from `tabOman Fawtara Submission` where name=%s for update", submission, as_dict=True
	)
	if not row or row[0].status not in ("Pending", "Retry"):
		return
	sub = frappe.get_doc("Oman Fawtara Submission", submission)
	sub.db_set({"status": "Processing", "attempt_count": cint(sub.attempt_count) + 1,
		"last_attempt_at": now_datetime(), "submitted_at": sub.submitted_at or now_datetime()},
		update_modified=False)
	frappe.db.commit()  # release the row lock before the network call

	s = fawtara_settings()
	started = time.monotonic()
	try:
		adapter = get_adapter(sub.provider)
		result = adapter.submit(_envelope(sub))
	except TransientProviderError as e:
		_log_attempt(sub, "Transient Error", str(e), started)
		return _schedule_retry(sub, str(e), s)
	except ProviderConfigurationError as e:
		_log_attempt(sub, "Configuration Error", str(e), started)
		_error(sub, "Authentication / Configuration", {"code": "CONFIG", "message": str(e)})
		return _schedule_retry(sub, str(e), s, needs_attention=True)
	except Exception as e:  # noqa: BLE001 — unknown failure: keep safe, retry, alert
		frappe.log_error(title=f"Fawtara submission {sub.name} failed")
		_log_attempt(sub, "Exception", str(e), started)
		return _schedule_retry(sub, str(e), s, needs_attention=True)

	_log_attempt(sub, result.outcome, result.message, started, result)
	apply_result(sub, result)


def _log_attempt(sub, outcome, message, started, result=None):
	frappe.get_doc(
		{
			"doctype": "Oman Fawtara Submission Log",
			"submission": sub.name,
			"attempt": sub.attempt_count,
			"outcome": outcome,
			"http_status": getattr(result, "http_status", None),
			"message": (message or "")[:1000],
			"duration_ms": int((time.monotonic() - started) * 1000),
			"response": (getattr(result, "raw_response", None) or "")[:20000],
			"request_hash": sub.xml_hash,
			"idempotency_key": sub.idempotency_key,
		}
	).insert(ignore_permissions=True)


def _schedule_retry(sub, message, s, needs_attention=False):
	attempts = cint(sub.attempt_count)
	max_attempts = cint(s.max_attempts) or 8
	exhausted = attempts >= max_attempts
	nxt = None if exhausted else add_to_date(now_datetime(), seconds=backoff_seconds(attempts, cint(s.retry_base_seconds) or 60))
	sub.db_set(
		{
			"status": "Retry",
			"next_attempt_at": nxt,
			"last_error": (message or "")[:1000],
			"needs_attention": 1 if (exhausted or needs_attention) else 0,
		},
		update_modified=False,
	)
	_sync_invoice(sub, "Retry")
	if exhausted:
		_notify(sub, _("Fawtara submission {0} exhausted {1} retries").format(sub.name, attempts))
	frappe.db.commit()


def apply_result(sub, result):
	now = now_datetime()
	if result.outcome == "accepted":
		updates = {
			"status": "Accepted",
			"provider_reference": result.provider_reference,
			"provider_accepted_at": now,
			"next_attempt_at": None,
			"needs_attention": 0,
			"last_error": None,
		}
		updates.update(_ota_updates(sub, result, now))
		sub.db_set(updates, update_modified=False)
		_store_receipt(sub, result)
		_archive(sub, result)
		_sync_invoice(sub, "Accepted" if updates.get("ota_status") not in ("Reported", "Acknowledged") else updates["ota_status"])
		audit.log_event("Fawtara Accepted", sub.doctype, sub.name,
			{"provider_reference": result.provider_reference, "ota_status": updates.get("ota_status")},
			sub.company, sub.vat_registration)
	elif result.outcome == "pending":
		sub.db_set({"provider_reference": result.provider_reference or sub.provider_reference,
			"status": "Processing", "next_attempt_at": None}, update_modified=False)
		_sync_invoice(sub, "Processing")
	else:
		sub.db_set({"status": "Rejected", "rejected_at": now, "next_attempt_at": None,
			"last_error": (result.message or "")[:1000], "provider_reference": result.provider_reference},
			update_modified=False)
		for e in result.errors or [{"code": "REJECTED", "message": result.message}]:
			_error(sub, "Provider Rejection", e)
		_sync_invoice(sub, "Rejected")
		_notify(sub, _("Fawtara rejected {0}: {1}").format(sub.reference_name, result.message))
		audit.log_event("Fawtara Rejected", sub.doctype, sub.name,
			{"errors": result.errors, "message": result.message}, sub.company, sub.vat_registration)
	frappe.db.commit()


def _ota_updates(sub, result, now):
	u = {}
	if result.ota_status:
		u["ota_status"] = result.ota_status
		if result.ota_status in ("Reported", "Acknowledged") and not sub.ota_reported_at:
			u["ota_reported_at"] = now
		if result.ota_status == "Acknowledged" and not sub.ota_acknowledged_at:
			u["ota_acknowledged_at"] = now
	if result.ota_reference:
		u["ota_reference"] = result.ota_reference
	if result.buyer_delivery:
		u["buyer_delivery_status"] = result.buyer_delivery
		if result.buyer_delivery in ("Delivered", "Acknowledged") and not sub.buyer_delivered_at:
			u["buyer_delivered_at"] = now
	return u


def _store_receipt(sub, result):
	if not result.receipt:
		return
	rc = frappe.get_doc(
		{
			"doctype": "Oman Fawtara Receipt",
			"submission": sub.name,
			"reference_doctype": sub.reference_doctype,
			"reference_name": sub.reference_name,
			"provider_reference": result.provider_reference,
			"ota_reference": result.ota_reference,
			"receipt_type": "Provider Acceptance",
			"received_at": now_datetime(),
			"content_hash": sha256_hex(result.receipt),
		}
	)
	rc.insert(ignore_permissions=True)
	f = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": result.receipt_filename or f"{sub.invoice_number}-receipt",
			"attached_to_doctype": rc.doctype,
			"attached_to_name": rc.name,
			"is_private": 1,
			"content": result.receipt,
		}
	).insert(ignore_permissions=True)
	rc.db_set("receipt_file", f.file_url, update_modified=False)
	sub.db_set("receipt", rc.name, update_modified=False)


def _archive(sub, result):
	"""Immutable e-invoice archive: final XML (provider-stamped when returned)."""
	xml = result.stamped_xml or frappe.get_doc("File", {"file_url": sub.xml_file}).get_content()
	if isinstance(xml, str):
		xml = xml.encode()
	d = frappe.get_doc(
		{
			"doctype": "Oman Fawtara Document",
			"submission": sub.name,
			"reference_doctype": sub.reference_doctype,
			"reference_name": sub.reference_name,
			"company": sub.company,
			"document_uuid": sub.document_uuid,
			"invoice_number": sub.invoice_number,
			"document_type": sub.document_type,
			"issue_date": sub.issue_date,
			"xml_hash": sha256_hex(xml),
			"is_provider_stamped": 1 if result.stamped_xml else 0,
			"provider_reference": result.provider_reference,
			"retention_until": add_to_date(sub.issue_date, years=cint(fawtara_settings().retention_years) or 10),
		}
	)
	d.flags.oman_system = True
	d.insert(ignore_permissions=True)
	f = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": f"{sub.invoice_number}-{sub.document_uuid}-archive.xml",
			"attached_to_doctype": d.doctype,
			"attached_to_name": d.name,
			"is_private": 1,
			"content": xml,
		}
	).insert(ignore_permissions=True)
	d.db_set("xml_file", f.file_url, update_modified=False)


def _sync_invoice(sub, status):
	if frappe.db.exists(sub.reference_doctype, sub.reference_name):
		frappe.db.set_value(sub.reference_doctype, sub.reference_name, "oman_fawtara_status", status,
			update_modified=False)


def _notify(sub, subject):
	users = frappe.get_all("Has Role", filters={"role": "Fawtara Manager", "parenttype": "User"}, pluck="parent")
	for u in set(users):
		if u in ("Administrator", "Guest"):
			continue
		frappe.get_doc(
			{
				"doctype": "Notification Log",
				"for_user": u,
				"type": "Alert",
				"document_type": sub.doctype,
				"document_name": sub.name,
				"subject": subject,
			}
		).insert(ignore_permissions=True)


# --------------------------------------------------------------------------
# Scheduler entry points
# --------------------------------------------------------------------------


def process_due():
	if not cint(fawtara_settings().enabled):
		return
	for name in frappe.get_all(
		"Oman Fawtara Submission",
		filters={"status": ["in", ["Pending", "Retry"]], "next_attempt_at": ["<=", now_datetime()]},
		pluck="name",
		limit=cint(fawtara_settings().batch_size) or 200,
		order_by="next_attempt_at asc",
	):
		try:
			process_submission(name)
		except Exception:
			frappe.db.rollback()
			frappe.log_error(title=f"Fawtara queue: {name}")


def poll_status():
	"""Follow up pending provider processing and OTA reporting/acknowledgement."""
	if not cint(fawtara_settings().enabled):
		return
	rows = frappe.get_all(
		"Oman Fawtara Submission",
		filters=[
			["provider_reference", "is", "set"],
			["status", "in", ["Processing", "Accepted"]],
			["ota_status", "not in", ["Acknowledged", "Failed"]],
		],
		pluck="name",
		limit=500,
	)
	for name in rows:
		sub = frappe.get_doc("Oman Fawtara Submission", name)
		try:
			res = get_adapter(sub.provider).get_status(sub.provider_reference, _envelope(sub))
		except Exception as e:  # noqa: BLE001
			_log_attempt(sub, "Status Poll Error", str(e), time.monotonic())
			continue
		if sub.status == "Processing" and res.outcome in ("accepted", "rejected"):
			apply_result(sub, res)
			continue
		upd = _ota_updates(sub, res, now_datetime())
		if upd:
			sub.db_set(upd, update_modified=False)
			if upd.get("ota_status"):
				_sync_invoice(sub, upd["ota_status"] if upd["ota_status"] != "Not Reported" else "Accepted")
			if upd.get("ota_status") == "Failed":
				_notify(sub, _("OTA reporting failed for {0}").format(sub.reference_name))
	frappe.db.commit()


def check_providers():
	for name in frappe.get_all("Oman Fawtara Provider", filters={"enabled": 1}, pluck="name"):
		try:
			ok, msg = get_adapter(name).ping()
		except Exception as e:  # noqa: BLE001
			ok, msg = False, str(e)
		frappe.db.set_value("Oman Fawtara Provider", name,
			{"last_check_at": now_datetime(), "last_check_ok": 1 if ok else 0, "last_check_message": (msg or "")[:500]})


# --------------------------------------------------------------------------
# Manual actions (whitelisted)
# --------------------------------------------------------------------------


@frappe.whitelist()
def retry_now(submission: str):
	frappe.only_for(("Fawtara Operator",) + FAWTARA_ROLES)
	sub = frappe.get_doc("Oman Fawtara Submission", submission)
	if sub.status != "Retry":
		frappe.throw(_("Only submissions in Retry can be retried; rejected documents must be corrected and resubmitted."))
	sub.db_set({"next_attempt_at": now_datetime(), "needs_attention": 0})
	frappe.enqueue("oman_fawtara.fawtara.queue.process_submission", queue="short", submission=submission,
		enqueue_after_commit=True)
	return "queued"


@frappe.whitelist()
def resubmit(submission: str, reason: str):
	"""Authorised resubmission of a rejected document after correction.

	The XML is regenerated from the current (corrected) masters; a new UUID and
	idempotency key are issued when configured, and the old submission is
	linked as superseded.
	"""
	frappe.only_for(FAWTARA_ROLES)
	if not (reason or "").strip():
		frappe.throw(_("A resubmission reason is required."))
	old = frappe.get_doc("Oman Fawtara Submission", submission)
	if old.status != "Rejected":
		frappe.throw(_("Only rejected submissions can be resubmitted."))
	doc = frappe.get_doc(old.reference_doctype, old.reference_name)
	if doc.docstatus != 1:
		frappe.throw(_("The referenced document is not submitted (cancelled/amended). Submit the amended document instead."))
	if cint(fawtara_settings().new_uuid_on_resubmit):
		doc.db_set("oman_fawtara_uuid", str(uuidlib.uuid4()), update_modified=False)
		doc.oman_fawtara_uuid = doc.get("oman_fawtara_uuid")
	inv, xml, issues = generate(doc)
	if sha256_hex(xml) == old.xml_hash and not cint(fawtara_settings().new_uuid_on_resubmit):
		frappe.throw(_("Nothing changed since the rejection. Correct the data before resubmitting."))
	new = create_submission(doc, inv, xml, issues, reason=reason, supersedes=old.name)
	old.db_set("superseded_by", new)
	audit.log_event("Fawtara Resubmitted", old.doctype, old.name, {"new": new, "reason": reason},
		old.company, old.vat_registration)
	return new


@frappe.whitelist()
def submit_document(doctype: str, name: str):
	"""Create a submission for an eligible submitted invoice that has none (e.g. after go-live backfill)."""
	frappe.only_for(FAWTARA_ROLES)
	doc = frappe.get_doc(doctype, name)
	if doc.docstatus != 1:
		frappe.throw(_("Document must be submitted."))
	return on_invoice_submit(doc)


@frappe.whitelist()
def reconcile_with_provider(provider: str, from_date: str, to_date: str):
	"""Compare provider-side records with ERPNext submissions (adapter must implement list_documents)."""
	frappe.only_for(("Fawtara Operator",) + FAWTARA_ROLES)
	remote = {r["uuid"]: r for r in get_adapter(provider).list_documents(from_date, to_date) if r.get("uuid")}
	local = {
		r.document_uuid: r
		for r in frappe.get_all(
			"Oman Fawtara Submission",
			filters={"provider": provider, "issue_date": ["between", [from_date, to_date]], "status": ["!=", "Cancelled"]},
			fields=["name", "document_uuid", "invoice_number", "status"],
		)
	}
	return {
		"missing_at_provider": [local[u].name for u in local.keys() - remote.keys() if local[u].status == "Accepted"],
		"unknown_in_erpnext": [remote[u] for u in remote.keys() - local.keys()],
		"status_mismatch": [
			{"submission": local[u].name, "erpnext": local[u].status, "provider": remote[u].get("status")}
			for u in local.keys() & remote.keys()
			if (local[u].status == "Accepted") != (str(remote[u].get("status") or "").upper() in ("ACCEPTED", "CLEARED", "REPORTED"))
		],
		"checked": len(local),
	}
