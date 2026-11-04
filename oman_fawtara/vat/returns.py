"""VAT return preparation and frozen snapshots.

Lifecycle of ``Oman VAT Return``::

    Open → Validation → Reviewed → (submit) Finalized → Filed → Locked

* Collect: pull every active ``Oman VAT Transaction`` of the period from the
  ledger and expand it into box-level ``Oman VAT Return Detail`` rows.
* Validate: flag missing VAT numbers, wrong treatments, unrecorded documents,
  missing evidence and GL reconciliation differences.
* Finalize (submit): freeze figures, rules, rates, account mapping and
  reconciliation into an immutable ``Oman VAT Return Snapshot`` with a
  SHA-256 content hash; link the transactions to the return so they can
  never be reported twice; close the period.
"""

from __future__ import annotations

import re
from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt, getdate, now_datetime

from oman_fawtara import audit
from oman_fawtara.vat import reconciliation
from oman_fawtara.vat.calc import canonical_json, round_money, sha256_hex
from oman_fawtara.vat.utils import has_role, settings


def box_catalogue(on_date):
	on_date = getdate(on_date)
	boxes = frappe.get_all(
		"Oman VAT Return Box",
		filters={"enabled": 1},
		fields=["name", "box_code", "label", "section", "value_type", "sequence", "formula", "effective_from", "effective_to"],
		order_by="sequence asc",
	)
	return [
		b for b in boxes
		if (not b.effective_from or getdate(b.effective_from) <= on_date)
		and (not b.effective_to or getdate(b.effective_to) >= on_date)
	]


_TOKEN = re.compile(r"\s*([+-]?)\s*([A-Za-z0-9_]+)")


def evaluate_formula(formula: str, values: dict) -> float:
	"""Evaluate a box formula made only of box codes joined by + and -."""
	total = 0.0
	pos = 0
	formula = formula.strip()
	while pos < len(formula):
		m = _TOKEN.match(formula, pos)
		if not m:
			frappe.throw(_("Invalid return box formula: {0}").format(formula))
		sign, code = m.groups()
		total += (-1 if sign == "-" else 1) * flt(values.get(code))
		pos = m.end()
	return total


def collect(ret):
	ret.set("details", [])
	txns = frappe.get_all(
		"Oman VAT Transaction",
		filters={
			"vat_registration": ret.vat_registration,
			"vat_period": ret.vat_period,
			"status": "Active",
			"vat_return": ["in", ["", None, ret.name]],
		},
		fields=["name", "source_doctype", "source_name", "tax_point_date", "party", "is_adjustment"],
		order_by="tax_point_date asc, name asc",
	)
	for t in txns:
		for d in frappe.get_all(
			"Oman VAT Transaction Detail",
			filters={"parent": t.name},
			fields=["name", "treatment", "vat_code", "return_boxes", "taxable_amount"],
			order_by="idx asc",
		):
			for box, amount in frappe.parse_json(d.return_boxes or "[]"):
				ret.append(
					"details",
					{
						"vat_transaction": t.name,
						"transaction_detail": d.name,
						"source_doctype": t.source_doctype,
						"source_name": t.source_name,
						"tax_point_date": t.tax_point_date,
						"party": t.party,
						"treatment": d.treatment,
						"vat_code": d.vat_code,
						"box_code": box,
						"amount": amount,
						"is_adjustment": t.is_adjustment,
					},
				)
	compute_totals(ret)
	ret.transaction_count = len(txns)


def compute_totals(ret):
	sums = defaultdict(float)
	for d in ret.details:
		sums[d.box_code] += flt(d.amount)
	cat = box_catalogue(ret.to_date)
	values = {k: float(round_money(v)) for k, v in sums.items()}
	for b in cat:
		if b.formula:
			values[b.box_code] = float(round_money(evaluate_formula(b.formula, values)))
	ret.set("box_totals", [])
	for b in cat:
		ret.append(
			"box_totals",
			{"box_code": b.box_code, "label": b.label, "section": b.section, "value_type": b.value_type,
			"amount": values.get(b.box_code, 0.0)},
		)
	s = settings()
	ret.total_output_vat = values.get(s.total_vat_due_box, 0.0)
	ret.total_input_vat = values.get(s.total_input_vat_box, 0.0)
	ret.net_vat = values.get(s.net_vat_box, flt(ret.total_output_vat) - flt(ret.total_input_vat))


def validate_return(ret) -> list[dict]:
	issues = []

	def add(sev, code, msg, ref=None):
		issues.append({"severity": sev, "code": code, "message": msg, "reference": ref})

	# 1. Documents in the period that never reached the VAT ledger
	for dt in ("Sales Invoice", "Purchase Invoice"):
		missing = frappe.db.sql(
			f"""select i.name from `tab{dt}` i
			left join `tabOman VAT Transaction` t on t.source_doctype=%s and t.source_name=i.name and t.status='Active'
			where i.docstatus=1 and i.company=%s and coalesce(i.oman_tax_point_date, i.posting_date) between %s and %s
			and t.name is null""",
			(dt, ret.company, ret.from_date, ret.to_date),
		)
		for (name,) in missing:
			add("Error", "UNRECORDED_DOCUMENT", _("{0} {1} has no Oman VAT Transaction.").format(dt, name), name)

	# 2. Source documents that were submitted with failed validation (advisory mode)
	for d in frappe.db.sql(
		"""select distinct t.source_doctype, t.source_name from `tabOman VAT Transaction` t
		where t.vat_period=%s and t.status='Active' and t.validation_status='Failed'""",
		ret.vat_period,
		as_dict=True,
	):
		add("Error", "FAILED_VALIDATION", _("{0} {1} was submitted with VAT validation errors.").format(
			d.source_doctype, d.source_name), d.source_name)

	# 3. Zero-rated supplies without evidence
	for d in frappe.db.sql(
		"""select distinct t.source_doctype, t.source_name from `tabOman VAT Transaction` t
		join `tabOman VAT Transaction Detail` d on d.parent=t.name
		join `tabOman VAT Treatment` tr on tr.name=d.treatment
		where t.vat_period=%s and t.status='Active' and tr.nature='Zero Rated' and t.direction='Sales'
		and not exists (select 1 from `tabOman VAT Evidence` e where e.reference_doctype=t.source_doctype
			and e.reference_name=t.source_name and e.status in ('Received','Verified'))""",
		ret.vat_period,
		as_dict=True,
	):
		add(settings().zero_rated_evidence_severity_at_return or "Error", "MISSING_ZERO_RATED_EVIDENCE",
			_("{0} {1}: zero-rated supply has no evidence.").format(d.source_doctype, d.source_name), d.source_name)

	# 4. Pending-evidence input claims
	for d in frappe.db.sql(
		"""select distinct t.source_name from `tabOman VAT Transaction` t
		join `tabOman VAT Transaction Detail` d on d.parent=t.name
		where t.vat_period=%s and t.status='Active' and d.recovery_status='Pending Evidence'""",
		ret.vat_period,
		as_dict=True,
	):
		add("Warning", "PENDING_EVIDENCE", _("Purchase Invoice {0}: input VAT pending documentation.").format(
			d.source_name), d.source_name)

	# 5. Register vs General Ledger
	recon = reconciliation.compute(ret.company, ret.vat_registration, ret.from_date, ret.to_date)
	tol = flt(settings().reconciliation_tolerance or 0.01)
	for r in recon:
		if abs(r["difference"]) > tol:
			add("Warning", "GL_DIFFERENCE", _("Account {0}: GL {1} vs VAT register {2} (difference {3}).").format(
				r["account"], r["gl_amount"], r["register_amount"], r["difference"]), r["account"])
	ret.reconciliation_json = canonical_json(recon)

	ret.validation_errors = len([i for i in issues if i["severity"] == "Error"])
	ret.validation_warnings = len([i for i in issues if i["severity"] == "Warning"])
	log = frappe.new_doc("Oman VAT Validation Log")
	log.update(
		{
			"reference_doctype": ret.doctype,
			"reference_name": ret.name,
			"company": ret.company,
			"vat_registration": ret.vat_registration,
			"status": "Failed" if ret.validation_errors else ("Warnings" if ret.validation_warnings else "Passed"),
			"error_count": ret.validation_errors,
			"warning_count": ret.validation_warnings,
			"issues": canonical_json(issues),
			"ruleset_version": settings().active_ruleset_version,
		}
	)
	log.flags.ignore_permissions = True
	log.insert()
	ret.last_validation_log = log.name
	return issues


def build_snapshot(ret) -> dict:
	rules_used = frappe.get_all(
		"Oman VAT Rule",
		filters={"status": "Approved", "enabled": 1, "effective_from": ["<=", ret.to_date]},
		fields=["rule_code", "check_key", "severity", "effective_from", "effective_to", "legal_reference",
			"ruleset_version", "numeric_value", "modified"],
	)
	rate_refs = sorted({
		r for r in frappe.db.sql_list(
			"""select distinct d.rate_reference from `tabOman VAT Transaction Detail` d
			join `tabOman VAT Transaction` t on t.name=d.parent where t.vat_period=%s and t.status='Active'""",
			ret.vat_period,
		) if r
	})
	rates = [
		frappe.db.get_value("Oman VAT Rate History", r, ["name", "treatment", "vat_code", "rate", "effective_from",
			"effective_to", "legal_reference"], as_dict=True)
		for r in rate_refs
	]
	mapping = frappe.get_doc(
		"Oman VAT Account Mapping",
		frappe.db.get_value("Oman VAT Account Mapping", {"company": ret.company, "disabled": 0}),
	).as_dict(no_default_fields=True)
	return {
		"return": ret.name,
		"company": ret.company,
		"vat_registration": ret.vat_registration,
		"vatin": frappe.db.get_value("Oman VAT Registration", ret.vat_registration, "vatin"),
		"period": ret.vat_period,
		"from_date": str(ret.from_date),
		"to_date": str(ret.to_date),
		"ruleset_version": settings().active_ruleset_version,
		"box_totals": [
			{"box_code": b.box_code, "label": b.label, "amount": flt(b.amount)} for b in ret.box_totals
		],
		"details": [
			{
				"vat_transaction": d.vat_transaction,
				"transaction_detail": d.transaction_detail,
				"source_doctype": d.source_doctype,
				"source_name": d.source_name,
				"box_code": d.box_code,
				"amount": flt(d.amount),
				"treatment": d.treatment,
				"tax_point_date": str(d.tax_point_date),
			}
			for d in ret.details
		],
		"transaction_hashes": dict(
			frappe.db.sql(
				"select name, content_hash from `tabOman VAT Transaction` where name in %s",
				[tuple({d.vat_transaction for d in ret.details}) or ("",)],
			)
		),
		"rules": [dict(r, effective_from=str(r.effective_from), effective_to=str(r.effective_to or ""),
			modified=str(r.modified)) for r in rules_used],
		"rates": [{k: str(v) if v is not None else None for k, v in (r or {}).items()} for r in rates],
		"account_mapping": {k: v for k, v in mapping.items() if k.endswith("_account") or k in ("company", "vat_registration")},
		"reconciliation": frappe.parse_json(ret.reconciliation_json or "[]"),
	}


def assert_segregation(ret):
	if settings().enforce_segregation_of_duties and ret.prepared_by == frappe.session.user \
			and frappe.session.user != "Administrator":
		frappe.throw(_("Segregation of duties: the preparer cannot finalize the same VAT return."))


def finalize(ret):
	"""Called from Oman VAT Return.on_submit."""
	s = settings()
	payload = build_snapshot(ret)
	content = canonical_json(payload)
	digest = sha256_hex(content)
	snap = frappe.new_doc("Oman VAT Return Snapshot")
	snap.update(
		{
			"vat_return": ret.name,
			"company": ret.company,
			"vat_registration": ret.vat_registration,
			"vat_period": ret.vat_period,
			"snapshot_json": content,
			"content_hash": digest,
			"generated_by": frappe.session.user,
			"generated_at": now_datetime(),
			"ruleset_version": s.active_ruleset_version,
			"net_vat": ret.net_vat,
		}
	)
	snap.flags.ignore_permissions = True
	snap.flags.oman_system = True
	snap.insert()
	ret.db_set({"snapshot": snap.name, "snapshot_hash": digest, "status": "Finalized",
		"finalized_by": frappe.session.user, "finalized_at": now_datetime()})

	names = list({d.vat_transaction for d in ret.details})
	if names:
		frappe.db.sql(
			"update `tabOman VAT Transaction` set vat_return=%s where name in %s and status='Active'",
			(ret.name, tuple(names)),
		)
	frappe.db.set_value("Oman VAT Period", ret.vat_period, {"status": "Finalized", "vat_return": ret.name})
	audit.log_event("VAT Return Finalized", ret.doctype, ret.name,
		{"snapshot": snap.name, "hash": digest, "net_vat": flt(ret.net_vat)}, ret.company, ret.vat_registration)
	return snap


def verify_snapshot(snapshot_name: str) -> dict:
	snap = frappe.get_doc("Oman VAT Return Snapshot", snapshot_name)
	ok = sha256_hex(snap.snapshot_json) == snap.content_hash
	payload = frappe.parse_json(snap.snapshot_json)
	drift = []
	for name, h in (payload.get("transaction_hashes") or {}).items():
		current = frappe.db.get_value("Oman VAT Transaction", name, ["content_hash", "status"], as_dict=True)
		if not current or current.content_hash != h or current.status != "Active":
			drift.append(name)
	return {"hash_valid": ok, "ledger_drift": drift, "reproducible": ok and not drift}


def require(roles):
	if not has_role(*roles):
		frappe.throw(_("Not permitted"), frappe.PermissionError)


def preview_boxes(vat_period: str) -> list[dict]:
	"""Live box totals for a period straight from the VAT ledger (no document saved)."""
	p = frappe.get_doc("Oman VAT Period", vat_period)
	sums = defaultdict(float)
	for (boxes,) in frappe.db.sql(
		"""select d.return_boxes from `tabOman VAT Transaction` t
		join `tabOman VAT Transaction Detail` d on d.parent=t.name
		where t.vat_period=%s and t.status='Active'""",
		vat_period,
	):
		for box, amount in frappe.parse_json(boxes or "[]"):
			sums[box] += flt(amount)
	values = {k: float(round_money(v)) for k, v in sums.items()}
	cat = box_catalogue(p.to_date)
	for b in cat:
		if b.formula:
			values[b.box_code] = float(round_money(evaluate_formula(b.formula, values)))
	return [
		{"section": b.section, "box_code": b.box_code, "label": b.label, "value_type": b.value_type,
		"amount": values.get(b.box_code, 0.0)}
		for b in cat
	]
