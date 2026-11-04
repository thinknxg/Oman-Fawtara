import frappe


def after_install():
	from oman_fawtara.setup.custom_fields import make_custom_fields
	from oman_fawtara.setup.seed import seed_all

	make_custom_fields()
	seed_all()
	frappe.db.commit()


def after_migrate():
	from oman_fawtara.setup.custom_fields import make_custom_fields
	from oman_fawtara.setup.seed import seed_all

	make_custom_fields()
	seed_all()


def before_uninstall():
	"""Remove custom fields from ERPNext doctypes.

	Accounting entries (journals, GL) created by the app are standard ERPNext
	records and are intentionally kept. Export compliance data (VAT returns,
	snapshots, Fawtara archive, audit log) before uninstalling: the app's own
	doctypes and their data are dropped by Frappe on uninstall.
	"""
	from oman_fawtara.setup.custom_fields import delete_custom_fields

	delete_custom_fields()
	for role in ("Oman VAT User", "Oman VAT Manager", "Oman VAT Approver", "Fawtara Operator", "Fawtara Manager"):
		if frappe.db.exists("Role", role) and not frappe.db.count("Has Role", {"role": role, "parenttype": "User"}):
			frappe.delete_doc("Role", role, ignore_permissions=True, force=True)


def has_app_permission():
	if frappe.session.user == "Administrator":
		return True
	roles = set(frappe.get_roles())
	return bool(roles & {"System Manager", "Oman VAT User", "Oman VAT Manager", "Oman VAT Approver",
		"Fawtara Operator", "Fawtara Manager", "Accounts Manager"})
