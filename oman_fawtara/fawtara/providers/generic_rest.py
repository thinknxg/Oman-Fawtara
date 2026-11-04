"""Configurable REST adapter for accredited service providers.

All endpoint paths, authentication, payload style and response field
locations are configured on the ``Oman Fawtara Provider`` document, so most
JSON/REST provider APIs can be connected without code. Providers with
non-standard flows should get a dedicated adapter class.
"""

from __future__ import annotations

import base64
import json
import time

import frappe
import requests
from frappe.utils import cint, flt

from oman_fawtara.fawtara.providers.base import (
	Envelope,
	FawtaraProvider,
	ProviderConfigurationError,
	ProviderResult,
	TransientProviderError,
)

TRANSIENT_HTTP = {408, 425, 429, 500, 502, 503, 504}


def dig(data, path: str | None):
	"""Read ``a.b.0.c`` style paths from nested JSON."""
	if not path or data is None:
		return None
	cur = data
	for part in path.split("."):
		if isinstance(cur, list):
			try:
				cur = cur[int(part)]
			except (ValueError, IndexError):
				return None
		elif isinstance(cur, dict):
			cur = cur.get(part)
		else:
			return None
	return cur


class GenericRestProvider(FawtaraProvider):
	label = "Generic REST"

	# ---------------------------------------------------------------- auth
	def _token(self) -> str:
		p = self.provider
		key = f"oman_fawtara_token:{p.name}"
		cached = frappe.cache.get_value(key)
		if cached:
			return cached
		try:
			r = requests.post(
				p.token_url,
				data={"grant_type": "client_credentials", "client_id": p.client_id,
					"client_secret": p.get_password("client_secret"), "scope": p.scope or ""},
				timeout=cint(p.timeout_seconds) or 30,
				verify=bool(cint(p.verify_tls)),
			)
		except requests.RequestException as e:
			raise TransientProviderError(f"Token endpoint unreachable: {e}") from e
		if r.status_code in TRANSIENT_HTTP:
			raise TransientProviderError(f"Token endpoint HTTP {r.status_code}")
		if r.status_code >= 400:
			raise ProviderConfigurationError(f"Authentication failed (HTTP {r.status_code})")
		body = r.json()
		token = body.get("access_token")
		frappe.cache.set_value(key, token, expires_in_sec=max(60, cint(body.get("expires_in") or 3600) - 60))
		return token

	def _headers(self, envelope: Envelope | None = None) -> dict:
		p = self.provider
		h = {"Accept": "application/json"}
		if p.auth_type == "API Key Header":
			h[p.api_key_header or "X-API-Key"] = p.get_password("api_key")
		elif p.auth_type == "Bearer Token":
			h["Authorization"] = f"Bearer {p.get_password('api_key')}"
		elif p.auth_type == "OAuth2 Client Credentials":
			h["Authorization"] = f"Bearer {self._token()}"
		if envelope and p.idempotency_header:
			h[p.idempotency_header] = envelope.idempotency_key
		for row in p.get("extra_headers") or []:
			h[row.header] = row.value
		return h

	def _auth(self):
		p = self.provider
		if p.auth_type == "Basic":
			return (p.username, p.get_password("password"))
		return None

	def _cert(self):
		p = self.provider
		if not p.client_certificate:
			return None
		cert = frappe.get_doc("Oman Fawtara Certificate", p.client_certificate)
		return cert.materialize_pem_paths()

	def _url(self, path: str, **fmt) -> str:
		return (self.provider.base_url or "").rstrip("/") + "/" + (path or "").lstrip("/").format(**fmt)

	def _request(self, method, url, **kw):
		p = self.provider
		try:
			return requests.request(
				method,
				url,
				timeout=cint(p.timeout_seconds) or 30,
				verify=bool(cint(p.verify_tls)),
				cert=self._cert(),
				auth=self._auth(),
				**kw,
			)
		except (requests.ConnectionError, requests.Timeout) as e:
			raise TransientProviderError(str(e)) from e
		except requests.RequestException as e:
			raise TransientProviderError(str(e)) from e

	# -------------------------------------------------------------- mapping
	def _parse(self, r) -> ProviderResult:
		p = self.provider
		text = r.text[:20000] if r.text else ""
		if r.status_code in TRANSIENT_HTTP:
			raise TransientProviderError(f"HTTP {r.status_code}: {text[:300]}")
		if r.status_code in (401, 403):
			raise ProviderConfigurationError(f"HTTP {r.status_code}: authentication/authorisation failed")
		try:
			body = r.json()
		except ValueError:
			body = {}
		status = str(dig(body, p.resp_status_path) or "").upper()
		accepted = {v.strip().upper() for v in (p.accepted_values or "ACCEPTED").split(",") if v.strip()}
		pending = {v.strip().upper() for v in (p.pending_values or "PENDING,PROCESSING,QUEUED").split(",") if v.strip()}
		rejected = {v.strip().upper() for v in (p.rejected_values or "REJECTED,INVALID").split(",") if v.strip()}
		errors = dig(body, p.resp_errors_path) or []
		if isinstance(errors, dict):
			errors = [errors]
		norm_errors = [
			{"code": str(dig(e, p.error_code_key or "code") or ""), "message": str(dig(e, p.error_message_key or "message") or e),
				"path": dig(e, p.error_path_key or "path")}
			if isinstance(e, dict) else {"code": "", "message": str(e)}
			for e in errors
		]
		if status in accepted:
			outcome = "accepted"
		elif status in pending:
			outcome = "pending"
		elif status in rejected or 400 <= r.status_code < 500:
			outcome = "rejected"
		else:
			outcome = "pending" if r.status_code in (200, 201, 202) else "rejected"
		receipt = dig(body, p.resp_receipt_path)
		stamped = dig(body, p.resp_stamped_xml_path)
		return ProviderResult(
			outcome=outcome,
			provider_reference=dig(body, p.resp_reference_path),
			ota_status=self._map_ota(dig(body, p.resp_ota_status_path)),
			ota_reference=dig(body, p.resp_ota_reference_path),
			buyer_delivery=dig(body, p.resp_delivery_status_path),
			message=str(dig(body, p.resp_message_path) or status or r.reason),
			errors=norm_errors,
			http_status=r.status_code,
			raw_response=text,
			receipt=base64.b64decode(receipt) if isinstance(receipt, str) and cint(p.receipt_is_base64) else
				(json.dumps(body, indent=2).encode() if outcome == "accepted" else None),
			receipt_filename=None,
			receipt_content_type="application/pdf" if cint(p.receipt_is_base64) else "application/json",
			stamped_xml=base64.b64decode(stamped) if isinstance(stamped, str) else None,
		)

	def _map_ota(self, value):
		if value is None:
			return None
		v = str(value).upper()
		if v in {x.strip().upper() for x in (self.provider.ota_acknowledged_values or "ACKNOWLEDGED,CLEARED").split(",")}:
			return "Acknowledged"
		if v in {x.strip().upper() for x in (self.provider.ota_reported_values or "REPORTED,SUBMITTED").split(",")}:
			return "Reported"
		if v in {x.strip().upper() for x in (self.provider.ota_failed_values or "FAILED,ERROR").split(",")}:
			return "Failed"
		return "Not Reported"

	# ----------------------------------------------------------------- API
	def submit(self, envelope: Envelope) -> ProviderResult:
		p = self.provider
		headers = self._headers(envelope)
		if p.payload_format == "Raw XML":
			headers["Content-Type"] = "application/xml"
			kwargs = {"data": envelope.xml}
		else:
			headers["Content-Type"] = "application/json"
			kwargs = {
				"data": json.dumps(
					{
						p.payload_uuid_key or "uuid": envelope.uuid,
						p.payload_number_key or "invoiceNumber": envelope.invoice_number,
						p.payload_type_key or "documentType": envelope.document_type,
						p.payload_xml_key or "invoice": base64.b64encode(envelope.xml).decode(),
						"supplierVatNumber": envelope.supplier_vrn,
						"buyerVatNumber": envelope.buyer_vrn,
						"issueDate": envelope.issue_date,
						**(envelope.metadata or {}),
					}
				)
			}
		started = time.monotonic()
		r = self._request("POST", self._url(p.submit_path), headers=headers, **kwargs)
		res = self._parse(r)
		res.message = f"{res.message} ({int((time.monotonic() - started) * 1000)} ms)"
		return res

	def get_status(self, provider_reference: str, envelope: Envelope | None = None) -> ProviderResult:
		p = self.provider
		if not p.status_path:
			return ProviderResult(outcome="pending", provider_reference=provider_reference)
		url = self._url(p.status_path, reference=provider_reference, uuid=envelope.uuid if envelope else "")
		return self._parse(self._request("GET", url, headers=self._headers()))

	def ping(self):
		p = self.provider
		if not p.ping_path:
			return True, "No ping endpoint configured"
		try:
			r = self._request("GET", self._url(p.ping_path), headers=self._headers())
		except (TransientProviderError, ProviderConfigurationError) as e:
			return False, str(e)
		return r.status_code < 400, f"HTTP {r.status_code}"

	def list_documents(self, from_date, to_date):
		p = self.provider
		if not p.list_path:
			return []
		r = self._request("GET", self._url(p.list_path), headers=self._headers(),
			params={"from": str(from_date), "to": str(to_date)})
		if r.status_code >= 400:
			return []
		items = dig(r.json(), p.list_items_path) or []
		return [
			{"uuid": dig(i, p.list_uuid_key or "uuid"), "invoice_number": dig(i, p.list_number_key or "invoiceNumber"),
				"status": dig(i, p.list_status_key or "status")}
			for i in items
		]


__all__ = ["GenericRestProvider", "dig", "flt"]
