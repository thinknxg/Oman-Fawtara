# Copyright (c) 2026, thinkNXG and contributors
# For license information, please see license.txt

import hashlib
import os

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate


class OmanFawtaraCertificate(Document):
	def validate(self):
		for f in ("certificate_file", "private_key_file"):
			url = self.get(f)
			if url and not url.startswith("/private/"):
				frappe.throw(_("{0} must be a private file.").format(self.meta.get_label(f)))
		if self.certificate_file:
			self._inspect()
		if self.valid_to and getdate(self.valid_to) < getdate() and self.status == "Active":
			self.status = "Expired"

	def _content(self, url):
		return frappe.get_doc("File", {"file_url": url}).get_content()

	def _inspect(self):
		try:
			from cryptography import x509
		except ImportError:
			return
		data = self._content(self.certificate_file)
		if isinstance(data, str):
			data = data.encode()
		try:
			cert = x509.load_pem_x509_certificate(data)
		except ValueError:
			frappe.throw(_("Certificate file is not a valid PEM X.509 certificate."))
		self.fingerprint = hashlib.sha256(cert.public_bytes(encoding=__import__("cryptography.hazmat.primitives.serialization", fromlist=["Encoding"]).Encoding.DER)).hexdigest()
		self.subject = cert.subject.rfc4514_string()[:140]
		self.issuer = cert.issuer.rfc4514_string()[:140]
		self.valid_from = getdate(cert.not_valid_before_utc)
		self.valid_to = getdate(cert.not_valid_after_utc)

	def materialize_pem_paths(self):
		"""Return (cert_path, key_path) of the private files for requests' ``cert=``."""
		if self.status != "Active":
			frappe.throw(_("Certificate {0} is {1}.").format(self.name, self.status))
		cert = frappe.get_doc("File", {"file_url": self.certificate_file}).get_full_path()
		key = frappe.get_doc("File", {"file_url": self.private_key_file}).get_full_path() if self.private_key_file else None
		if key and self.get_password("key_password", raise_exception=False):
			frappe.throw(_("Encrypted private keys are not supported by the HTTP client; store an unencrypted key in a private file."))
		return (cert, key) if key else cert


def check_expiry():
	"""Daily: flag certificates expiring within 30 days."""
	soon = frappe.utils.add_days(getdate(), 30)
	for c in frappe.get_all("Oman Fawtara Certificate", filters={"status": "Active", "valid_to": ["<=", soon]},
			fields=["name", "valid_to"]):
		if getdate(c.valid_to) < getdate():
			frappe.db.set_value("Oman Fawtara Certificate", c.name, "status", "Expired")
		frappe.log_error(title=f"Fawtara certificate {c.name} expires {c.valid_to}", message="Renew the certificate.")


__all__ = ["os"]
