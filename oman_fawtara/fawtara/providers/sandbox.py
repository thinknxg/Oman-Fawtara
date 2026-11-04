"""Simulated provider for UAT, demos and automated tests. Never use in production."""

from __future__ import annotations

import frappe
from frappe.utils import cint

from oman_fawtara.fawtara.providers.base import (
	Envelope,
	FawtaraProvider,
	ProviderResult,
	TransientProviderError,
)

_SEEN_KEY = "oman_fawtara_sandbox_seen"


class SandboxProvider(FawtaraProvider):
	label = "Sandbox (Simulated)"

	def _seen(self) -> dict:
		return frappe.cache.get_value(_SEEN_KEY) or {}

	def submit(self, envelope: Envelope) -> ProviderResult:
		behaviour = self.provider.sandbox_behaviour or "Accept"
		seen = self._seen()
		# Idempotency: a repeated key returns the original outcome, never a new document.
		if envelope.idempotency_key in seen:
			ref = seen[envelope.idempotency_key]
			return ProviderResult(outcome="accepted", provider_reference=ref, ota_status="Reported",
				ota_reference=f"OTA-{ref}", message="Duplicate request (idempotent replay)")

		attempts_key = f"oman_fawtara_sandbox_attempts:{envelope.idempotency_key}"
		attempts = cint(frappe.cache.get_value(attempts_key)) + 1
		frappe.cache.set_value(attempts_key, attempts)

		if behaviour == "Transient Failure then Accept" and attempts <= cint(self.provider.sandbox_failures or 1):
			raise TransientProviderError(f"Simulated network timeout (attempt {attempts})")
		if behaviour == "Reject":
			return ProviderResult(
				outcome="rejected",
				message="Simulated validation rejection",
				errors=[{"code": "BR-OM-SIM-01", "message": "Buyer VAT number is not registered", "path": "customer.vrn"}],
				http_status=422,
			)
		ref = f"SBX-{envelope.uuid[:8].upper()}"
		seen[envelope.idempotency_key] = ref
		frappe.cache.set_value(_SEEN_KEY, seen)
		ota = "Not Reported" if behaviour == "Accept, OTA Pending" else "Reported"
		receipt = (
			f"Sandbox receipt\nUUID: {envelope.uuid}\nInvoice: {envelope.invoice_number}\nProvider ref: {ref}\n"
		).encode()
		return ProviderResult(
			outcome="accepted",
			provider_reference=ref,
			ota_status=ota,
			ota_reference=f"OTA-{ref}" if ota == "Reported" else None,
			buyer_delivery="Delivered",
			message="Accepted by sandbox",
			http_status=200,
			receipt=receipt,
			receipt_filename=f"{envelope.invoice_number}-receipt.txt",
			receipt_content_type="text/plain",
		)

	def get_status(self, provider_reference: str, envelope: Envelope | None = None) -> ProviderResult:
		return ProviderResult(outcome="accepted", provider_reference=provider_reference, ota_status="Acknowledged",
			ota_reference=f"OTA-{provider_reference}", buyer_delivery="Acknowledged")

	def ping(self):
		return True, "Sandbox reachable"
