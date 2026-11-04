"""Provider adapter registry."""

from __future__ import annotations

import frappe
from frappe import _

BUILTIN = {
	"Sandbox (Simulated)": "oman_fawtara.fawtara.providers.sandbox.SandboxProvider",
	"Generic REST": "oman_fawtara.fawtara.providers.generic_rest.GenericRestProvider",
}


def available_adapters() -> dict:
	adapters = dict(BUILTIN)
	for mapping in frappe.get_hooks("oman_fawtara_provider_adapters") or []:
		if isinstance(mapping, dict):
			adapters.update(mapping)
	return adapters


def get_adapter(provider_name: str):
	provider = frappe.get_doc("Oman Fawtara Provider", provider_name)
	path = available_adapters().get(provider.adapter)
	if not path:
		frappe.throw(_("Unknown Fawtara adapter {0}").format(provider.adapter))
	cls = frappe.get_attr(path)
	return cls(provider)


@frappe.whitelist()
def get_adapter_names():
	return sorted(available_adapters().keys())
