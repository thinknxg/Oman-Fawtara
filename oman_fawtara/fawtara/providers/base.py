"""Accredited service provider (C2) adapter interface.

The VAT engine and queue only ever talk to this interface; each accredited
provider gets its own adapter. Register additional adapters from any app via
the ``oman_fawtara_provider_adapters`` hook::

    oman_fawtara_provider_adapters = {"My ASP": "my_app.fawtara.MyAspAdapter"}

The application never files directly with the OTA: under the five-corner
model the provider validates, exchanges and reports invoice data.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class TransientProviderError(Exception):
	"""Network/availability problem: safe to retry with the same idempotency key."""


class ProviderConfigurationError(Exception):
	"""Configuration/authentication problem: needs an operator, not a blind retry."""


@dataclass
class Envelope:
	uuid: str
	idempotency_key: str
	invoice_number: str
	document_type: str
	xml: bytes
	issue_date: str
	supplier_vrn: str
	buyer_vrn: str | None = None
	metadata: dict = field(default_factory=dict)


@dataclass
class ProviderResult:
	# accepted | rejected | pending | transient_error
	outcome: str
	provider_reference: str | None = None
	# Not Reported | Reported | Acknowledged | Failed
	ota_status: str | None = None
	ota_reference: str | None = None
	buyer_delivery: str | None = None  # Not Delivered | Delivered | Acknowledged
	message: str | None = None
	errors: list = field(default_factory=list)
	http_status: int | None = None
	raw_response: str | None = None
	receipt: bytes | None = None
	receipt_filename: str | None = None
	receipt_content_type: str | None = None
	stamped_xml: bytes | None = None


class FawtaraProvider:
	"""Base class. ``provider`` is the ``Oman Fawtara Provider`` document."""

	label = "Base"

	def __init__(self, provider):
		self.provider = provider

	def submit(self, envelope: Envelope) -> ProviderResult:
		raise NotImplementedError

	def get_status(self, provider_reference: str, envelope: Envelope | None = None) -> ProviderResult:
		raise NotImplementedError

	def ping(self) -> tuple[bool, str]:
		return True, "No connectivity check implemented"

	def list_documents(self, from_date, to_date) -> list[dict]:
		"""Optional: provider-side records for reconciliation ({uuid, invoice_number, status})."""
		return []
