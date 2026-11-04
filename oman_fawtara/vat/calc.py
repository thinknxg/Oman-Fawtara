"""Pure tax arithmetic for thinkNXG Oman Fawtara.

This module deliberately has no Frappe imports so that the arithmetic that
drives every VAT figure can be unit-tested in isolation and reasoned about by
a tax reviewer. All money is handled as ``Decimal`` and rounded half-up to the
OMR minor unit (3 decimal places, baisa).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

OMR_PLACES = 3
ZERO = Decimal("0")
HUNDRED = Decimal("100")


def D(value) -> Decimal:
	"""Convert anything numeric (float, str, int, None, Decimal) to Decimal."""
	if value is None or value == "":
		return ZERO
	if isinstance(value, Decimal):
		return value
	try:
		# str() avoids binary float artefacts: D(0.1) -> Decimal('0.1')
		return Decimal(str(value))
	except (InvalidOperation, ValueError):
		return ZERO


def round_money(value, places: int = OMR_PLACES) -> Decimal:
	quant = Decimal(1).scaleb(-places)
	return D(value).quantize(quant, rounding=ROUND_HALF_UP)


def vat_on(taxable, rate, places: int = OMR_PLACES) -> Decimal:
	"""VAT on a tax-exclusive taxable amount at ``rate`` percent."""
	return round_money(D(taxable) * D(rate) / HUNDRED, places)


def taxable_from_inclusive(gross, rate, places: int = OMR_PLACES) -> Decimal:
	"""Back out the taxable amount from a tax-inclusive gross."""
	rate = D(rate)
	if rate == ZERO:
		return round_money(gross, places)
	return round_money(D(gross) * HUNDRED / (HUNDRED + rate), places)


def split_recovery(input_vat, recovery_pct, places: int = OMR_PLACES) -> tuple[Decimal, Decimal]:
	"""Split input VAT into (recoverable, non-recoverable).

	The non-recoverable part is computed as the remainder so the two parts
	always add back to the original input VAT exactly.
	"""
	input_vat = round_money(input_vat, places)
	pct = max(ZERO, min(HUNDRED, D(recovery_pct)))
	recoverable = round_money(input_vat * pct / HUNDRED, places)
	return recoverable, input_vat - recoverable


@dataclass
class LineResult:
	taxable: Decimal = ZERO
	rate: Decimal = ZERO
	output_vat: Decimal = ZERO
	input_vat: Decimal = ZERO
	recovery_pct: Decimal = ZERO
	recoverable: Decimal = ZERO
	nonrecoverable: Decimal = ZERO
	rcm_output: Decimal = ZERO
	rcm_input: Decimal = ZERO
	charged_vat: Decimal = ZERO
	expected_vat: Decimal = ZERO
	notes: list = field(default_factory=list)

	def as_dict(self) -> dict:
		d = asdict(self)
		return {k: (float(v) if isinstance(v, Decimal) else v) for k, v in d.items()}


def compute_line(
	*,
	direction: str,
	taxable,
	rate,
	charges_vat: bool,
	reverse_charge: bool = False,
	recovery_pct=100,
	charged_vat=None,
	places: int = OMR_PLACES,
) -> LineResult:
	"""Compute the VAT figures for one invoice line.

	direction      "Sales" or "Purchase"
	taxable        taxable amount in the reporting currency (OMR)
	rate           applicable rate from the versioned rule set
	charges_vat    False for zero-rated / exempt / out-of-scope treatments
	reverse_charge purchase is self-assessed by the recipient
	charged_vat    VAT actually charged on the document line (from ERPNext's
	               Item Wise Tax Detail). For purchases the claimable input VAT
	               is the VAT actually charged on the supplier's tax invoice.
	"""
	r = LineResult(taxable=round_money(taxable, places), rate=D(rate))
	r.expected_vat = vat_on(r.taxable, r.rate, places) if (charges_vat or reverse_charge) else ZERO
	r.charged_vat = round_money(charged_vat, places) if charged_vat is not None else r.expected_vat

	if direction == "Sales":
		r.output_vat = r.charged_vat if charges_vat else ZERO
		return r

	# Purchases
	if reverse_charge:
		# The supplier charges nothing; the recipient self-assesses both sides.
		r.rcm_output = r.expected_vat
		r.input_vat = r.expected_vat
	else:
		r.input_vat = r.charged_vat if charges_vat else ZERO
	r.recovery_pct = max(ZERO, min(HUNDRED, D(recovery_pct)))
	r.recoverable, r.nonrecoverable = split_recovery(r.input_vat, r.recovery_pct, places)
	if reverse_charge:
		r.rcm_input = r.recoverable
	return r


def reconcile(engine_total, erpnext_total, tolerance) -> tuple[bool, Decimal]:
	"""Return (within_tolerance, difference) for engine vs ERPNext VAT totals."""
	diff = round_money(D(engine_total) - D(erpnext_total))
	return abs(diff) <= D(tolerance), diff


def line_tolerance(line_count: int, per_line=Decimal("0.001"), floor=Decimal("0.005")) -> Decimal:
	"""Rounding tolerance grows with the number of lines (one baisa per line)."""
	return max(D(floor), D(per_line) * max(1, int(line_count)))


def apportionment_ratio(taxable_supplies, total_supplies, places: int = 2) -> Decimal:
	"""Standard input-tax apportionment ratio (percent).

	taxable_supplies: supplies that give a right to deduct (standard + zero rated)
	total_supplies:   taxable_supplies + exempt supplies
	"""
	total = D(total_supplies)
	if total <= ZERO:
		return HUNDRED
	ratio = D(taxable_supplies) * HUNDRED / total
	return max(ZERO, min(HUNDRED, ratio.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)))


def backoff_seconds(attempt: int, base: int = 60, cap: int = 6 * 3600) -> int:
	"""Exponential retry delay: base * 2^(attempt-1), capped."""
	attempt = max(1, int(attempt))
	return int(min(cap, base * (2 ** (attempt - 1))))


def canonical_json(payload) -> str:
	return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)


def sha256_hex(text: str | bytes) -> str:
	if isinstance(text, str):
		text = text.encode("utf-8")
	return hashlib.sha256(text).hexdigest()


def idempotency_key(*parts) -> str:
	return sha256_hex("|".join(str(p or "") for p in parts))


def chain_hash(previous_hash: str | None, payload) -> str:
	"""Hash-chain link for the immutable compliance audit trail."""
	return sha256_hex((previous_hash or "GENESIS") + "|" + canonical_json(payload))


def normalize_invoice_number(value: str | None) -> str:
	"""Normalise supplier invoice numbers for duplicate detection.

	Removes whitespace, separators and leading zeros of each numeric run so
	that "INV-0012", "inv 12" and "INV/12" are treated as the same number.
	"""
	if not value:
		return ""
	text = re.sub(r"[\s\-_/\\.#:]", "", str(value).upper())
	return re.sub(r"0*(\d+)", lambda m: m.group(1).lstrip("0") or "0", text)


DEFAULT_VRN_PATTERN = r"^OM\d{10}$"


def vrn_is_valid(vrn: str | None, pattern: str | None = None) -> bool:
	if not vrn:
		return False
	return bool(re.fullmatch(pattern or DEFAULT_VRN_PATTERN, vrn.strip().upper()))


def ranges_overlap(a_from, a_to, b_from, b_to) -> bool:
	"""Inclusive date-range overlap where ``None`` means open-ended."""
	if a_to is not None and b_from is not None and a_to < b_from:
		return False
	if b_to is not None and a_from is not None and b_to < a_from:
		return False
	return True


def is_effective(on_date, effective_from, effective_to) -> bool:
	if effective_from and on_date < effective_from:
		return False
	if effective_to and on_date > effective_to:
		return False
	return True
