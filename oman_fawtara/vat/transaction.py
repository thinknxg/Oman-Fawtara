"""Oman VAT Transaction ledger.

On submission of every VAT-relevant document the engine writes an
``Oman VAT Transaction`` holding the frozen per-line VAT figures, the
treatment, rate reference and return boxes. Returns are built from this
ledger (not from live invoice data or report filters), so a finalized return
remains reproducible even if masters or mappings change later.
"""

from __future__ import annotations

import frappe
from frappe.utils import cint, flt

from oman_fawtara.vat.calc import canonical_json, sha256_hex
from oman_fawtara.vat.utils import get_period_for, party_country


def _code_boxes(code: str | None) -> dict:
	if not code:
		return {}
	return frappe.get_cached_value(
		"Oman VAT Code",
		code,
		[
			"output_value_box",
			"output_vat_box",
			"input_value_box",
			"input_vat_box",
			"fixed_asset_input_vat_box",
			"output_adjustment_box",
			"input_adjustment_box",
		],
		as_dict=True,
	) or {}


def _boxes_for_line(direction, line, is_adjustment, s):
	"""Return list of (box_code, amount) for a transaction detail line."""
	b = _code_boxes(line.get("vat_code"))
	out = []
	adj_mode = s.credit_note_reporting == "Adjustment Box" and is_adjustment

	def put(box, amount):
		if box and flt(amount):
			out.append((box, flt(amount)))

	if direction == "Sales":
		if adj_mode:
			put(b.get("output_adjustment_box"), line["output_vat"])
		else:
			put(b.get("output_value_box"), line["taxable"])
			put(b.get("output_vat_box"), line["output_vat"])
		return out

	# Purchases: reverse-charge self-assessed output
	if line.get("reverse_charge"):
		put(b.get("output_value_box"), line["taxable"])
		put(b.get("output_vat_box"), line["rcm_output"])
	if adj_mode:
		put(b.get("input_adjustment_box"), line["recoverable"])
		return out
	vat_box = b.get("fixed_asset_input_vat_box") if line.get("is_fixed_asset") and b.get("fixed_asset_input_vat_box") else b.get("input_vat_box")
	if line.get("recovery_status") == "Pending Evidence" and cint(s.exclude_pending_from_return):
		return out
	put(b.get("input_value_box"), line["taxable"])
	put(vat_box, line["recoverable"])
	return out


def record(source_doc, direction: str, lines: list[dict], *, party_type=None, party=None, party_vrn=None,
		tax_point=None, registration=None, is_adjustment=False, original=None, extra=None):
	"""Create an immutable Oman VAT Transaction for ``source_doc``."""
	s = frappe.get_cached_doc("Oman VAT Settings")
	existing = frappe.db.get_value(
		"Oman VAT Transaction",
		{"source_doctype": source_doc.doctype, "source_name": source_doc.name, "status": "Active"},
	)
	if existing:
		return frappe.get_doc("Oman VAT Transaction", existing)

	period = get_period_for(registration, tax_point) if registration else None
	t = frappe.new_doc("Oman VAT Transaction")
	t.update(
		{
			"source_doctype": source_doc.doctype,
			"source_name": source_doc.name,
			"company": source_doc.company,
			"vat_registration": registration,
			"direction": direction,
			"party_type": party_type,
			"party": party,
			"party_vrn": party_vrn,
			"party_country": party_country(party_type, party) if party_type and party else None,
			"tax_point_date": tax_point,
			"posting_date": source_doc.get("posting_date") or tax_point,
			"vat_period": period.name if period else None,
			"currency": source_doc.get("currency") or "OMR",
			"conversion_rate": source_doc.get("conversion_rate") or 1,
			"is_adjustment": 1 if is_adjustment else 0,
			"original_doctype": (original or {}).get("doctype"),
			"original_name": (original or {}).get("name"),
			"ruleset_version": s.active_ruleset_version,
			"status": "Active",
			**(extra or {}),
		}
	)
	totals = dict.fromkeys(
		("taxable", "output_vat", "input_vat", "recoverable", "nonrecoverable", "rcm_output"), 0.0
	)
	for line in lines:
		boxes = _boxes_for_line(direction, line, is_adjustment, s)
		row = t.append(
			"details",
			{
				"source_row": line.get("row"),
				"item_code": line.get("item_code"),
				"treatment": line.get("treatment"),
				"vat_code": line.get("vat_code"),
				"rate": line.get("rate"),
				"rate_reference": line.get("rate_ref"),
				"supply_category": line.get("supply_category"),
				"taxable_amount": line.get("taxable"),
				"output_vat": line.get("output_vat"),
				"input_vat": line.get("input_vat"),
				"recovery_percentage": line.get("recovery_pct"),
				"recoverable_vat": line.get("recoverable"),
				"nonrecoverable_vat": line.get("nonrecoverable"),
				"rcm_output_vat": line.get("rcm_output"),
				"reverse_charge": 1 if line.get("reverse_charge") else 0,
				"is_import": 1 if line.get("is_import") else 0,
				"recovery_status": line.get("recovery_status"),
				"recovery_profile": line.get("recovery_profile"),
				"return_boxes": canonical_json(boxes),
			},
		)
		for k in totals:
			totals[k] += flt(line.get(k))
		row.flags.boxes = boxes
	t.update({f"total_{k}": v for k, v in totals.items()})
	t.content_hash = sha256_hex(canonical_json([d.as_dict(no_default_fields=True) for d in t.details]))
	t.flags.ignore_permissions = True
	t.flags.oman_system = True
	t.insert()
	return t


def lines_from_document(doc) -> list[dict]:
	"""Rebuild engine lines from the persisted ``oman_*`` fields of a submitted invoice."""
	out = []
	for i in doc.items:
		if not i.get("oman_vat_treatment"):
			continue
		out.append(
			{
				"row": i.name,
				"item_code": i.item_code,
				"treatment": i.oman_vat_treatment,
				"vat_code": i.oman_vat_code,
				"rate": i.oman_vat_rate,
				"rate_ref": i.get("oman_rate_reference"),
				"supply_category": i.oman_supply_category,
				"taxable": flt(i.oman_taxable_amount),
				"output_vat": flt(i.oman_output_vat),
				"input_vat": flt(i.oman_input_vat),
				"recovery_pct": flt(i.oman_recovery_percentage),
				"recoverable": flt(i.oman_recoverable_vat),
				"nonrecoverable": flt(i.oman_nonrecoverable_vat),
				"rcm_output": flt(i.oman_input_vat) if cint(i.oman_reverse_charge) else 0,
				"reverse_charge": cint(i.oman_reverse_charge),
				"is_import": cint(frappe.get_cached_value("Oman VAT Treatment", i.oman_vat_treatment, "is_import")),
				"is_fixed_asset": cint(i.get("is_fixed_asset")),
				"recovery_status": i.get("oman_recovery_status"),
				"recovery_profile": i.get("oman_recovery_profile"),
			}
		)
	return out


def cancel_for(source_doctype: str, source_name: str):
	for name in frappe.get_all(
		"Oman VAT Transaction",
		filters={"source_doctype": source_doctype, "source_name": source_name, "status": "Active"},
		pluck="name",
	):
		included = frappe.db.get_value("Oman VAT Transaction", name, "vat_return")
		if included and frappe.db.get_value("Oman VAT Return", included, "docstatus") == 1:
			frappe.throw(
				frappe._("{0} {1} is included in finalized VAT return {2} and cannot be cancelled.").format(
					source_doctype, source_name, included)
			)
		frappe.db.set_value("Oman VAT Transaction", name, {"status": "Cancelled", "vat_return": None})


@frappe.whitelist()
def backfill(company: str, from_date: str, to_date: str, dry_run: int = 1):
	"""Create missing VAT ledger entries for submitted invoices (go-live / after reinstall).

	Each invoice is re-analysed with the rules in force at its tax point and
	recorded as an Oman VAT Transaction flagged as backfilled. No journals are
	posted: the GL of historic documents is final, so differences (e.g. absent
	non-recoverable allocations) surface in the GL reconciliation for review.
	"""
	from oman_fawtara import audit
	from oman_fawtara.vat import engine

	frappe.only_for(("Oman VAT Approver", "System Manager"))
	done, failed = [], []
	for dt in ("Sales Invoice", "Purchase Invoice"):
		names = frappe.db.sql(
			f"""select i.name from `tab{dt}` i
			left join `tabOman VAT Transaction` t on t.source_doctype=%s and t.source_name=i.name and t.status='Active'
			where i.docstatus=1 and i.company=%s and i.posting_date between %s and %s and t.name is null
			order by i.posting_date, i.name""",
			(dt, company, from_date, to_date),
		)
		for (name,) in names:
			doc = frappe.get_doc(dt, name)
			a = engine.analyse(doc, persist=False)
			if not a.registration:
				failed.append({"doctype": dt, "name": name, "reason": "no registration"})
				continue
			if cint(dry_run):
				done.append({"doctype": dt, "name": name, "status": a.status})
				continue
			party_type, party_field = engine.PARTY[dt]
			lines = [{**l, "taxable": flt(l["taxable"]), "charged_vat": None} for l in a.lines]
			record(doc, a.direction, lines, party_type=party_type, party=doc.get(party_field),
				party_vrn=doc.get("tax_id"), tax_point=a.tax_point, registration=a.registration,
				is_adjustment=bool(cint(doc.get("is_return")) or cint(doc.get("is_debit_note"))),
				original={"doctype": dt, "name": doc.return_against} if doc.get("return_against") else None,
				extra={"validation_status": a.status, "adjustment_reason": "Backfilled ledger entry"})
			done.append({"doctype": dt, "name": name, "status": a.status})
	if not cint(dry_run) and done:
		audit.log_event("VAT Ledger Backfill", None, None,
			{"company": company, "from": str(from_date), "to": str(to_date), "count": len(done)}, company)
	return {"processed": done, "failed": failed, "dry_run": bool(cint(dry_run))}
