"""One-click Oman VAT setup for a company.

Creates (if missing) the VAT accounts, ERPNext Item Tax Templates, Sales and
Purchase Taxes and Charges Templates, maps the templates to the Oman VAT
codes, and creates the account mapping and VAT registration. Everything stays
standard ERPNext so the app reuses ERPNext tax computation and the GL.
"""

import frappe
from frappe import _

ACCOUNTS = [
	# key, account name, parent group (by account_name), account_type, root
	("output", "Oman Output VAT", "Duties and Taxes", "Tax"),
	("input", "Oman Input VAT", "Duties and Taxes", "Tax"),
	("rcm_output", "Oman Reverse Charge Output VAT", "Duties and Taxes", "Tax"),
	("rcm_input", "Oman Reverse Charge Input VAT", "Duties and Taxes", "Tax"),
	("import_input", "Oman Import VAT Recoverable", "Duties and Taxes", "Tax"),
	("import_payable", "Oman Postponed Import VAT Payable", "Duties and Taxes", "Tax"),
	("customs_clearing", "Oman Customs VAT Clearing", "Duties and Taxes", "Tax"),
	("adjustment", "Oman VAT Adjustments", "Duties and Taxes", "Tax"),
	("nonrecoverable", "Non-recoverable VAT", "Indirect Expenses", "Chargeable"),
]

TEMPLATE_FOR_CODE = {
	"OM-S5": "5", "OM-MX": "5", "OM-BL": "5",
	"OM-Z0": "0", "OM-ZX": "0", "OM-EX": "0", "OM-OS": "0", "OM-RC": "0", "OM-IS": "0", "OM-IG": "0",
}


def _group(company, account_name):
	acc = frappe.db.get_value("Account", {"company": company, "account_name": account_name, "is_group": 1})
	if acc:
		return acc
	root = "Liability" if account_name == "Duties and Taxes" else "Expense"
	acc = frappe.db.get_value("Account", {"company": company, "is_group": 1, "root_type": root}, order_by="lft desc")
	if not acc:
		frappe.throw(_("Could not find a parent account group for {0}").format(account_name))
	return acc


def _account(company, name, parent, account_type):
	abbr = frappe.get_cached_value("Company", company, "abbr")
	full = f"{name} - {abbr}"
	if frappe.db.exists("Account", full):
		return full
	acc = frappe.get_doc(
		{
			"doctype": "Account",
			"account_name": name,
			"company": company,
			"parent_account": _group(company, parent),
			"account_type": account_type,
			"is_group": 0,
		}
	)
	acc.flags.ignore_permissions = True
	acc.insert()
	return acc.name


def _item_tax_template(company, rate, accounts):
	abbr = frappe.get_cached_value("Company", company, "abbr")
	title = f"Oman VAT {rate}%"
	name = f"{title} - {abbr}"
	if frappe.db.exists("Item Tax Template", name):
		return name
	t = frappe.get_doc(
		{
			"doctype": "Item Tax Template",
			"title": title,
			"company": company,
			"taxes": [{"tax_type": a, "tax_rate": float(rate)} for a in accounts],
		}
	)
	t.flags.ignore_permissions = True
	t.insert()
	return t.name


def _taxes_template(doctype, company, title, account, extra=None):
	abbr = frappe.get_cached_value("Company", company, "abbr")
	name = f"{title} - {abbr}"
	if frappe.db.exists(doctype, name):
		return name
	row = {"charge_type": "On Net Total", "account_head": account, "description": "VAT 5%", "rate": 5, **(extra or {})}
	t = frappe.get_doc({"doctype": doctype, "title": title, "company": company, "taxes": [row]})
	t.flags.ignore_permissions = True
	t.insert()
	return t.name


@frappe.whitelist()
def setup_company(company: str, vatin: str | None = None, legal_name: str | None = None,
		effective_from: str = "2021-04-16", return_frequency: str = "Quarterly", first_period_start: str | None = None):
	frappe.only_for(("System Manager", "Oman VAT Approver", "Oman VAT Manager"))
	acc = {key: _account(company, name, parent, atype) for key, name, parent, atype in ACCOUNTS}

	t5 = _item_tax_template(company, 5, [acc["output"], acc["input"]])
	t0 = _item_tax_template(company, 0, [acc["output"], acc["input"]])
	for code, rate in TEMPLATE_FOR_CODE.items():
		if not frappe.db.exists("Oman VAT Code", code):
			continue
		c = frappe.get_doc("Oman VAT Code", code)
		if not any(r.company == company for r in c.templates):
			c.append("templates", {"company": company, "item_tax_template": t5 if rate == "5" else t0})
			c.flags.ignore_permissions = True
			c.save()

	stc = _taxes_template("Sales Taxes and Charges Template", company, "Oman VAT", acc["output"])
	ptc = _taxes_template("Purchase Taxes and Charges Template", company, "Oman Input VAT", acc["input"],
		{"category": "Total", "add_deduct_tax": "Add"})

	reg_name = None
	if vatin:
		reg_name = frappe.db.get_value("Oman VAT Registration", {"company": company, "vatin": vatin.upper()})
		if not reg_name:
			reg = frappe.get_doc(
				{
					"doctype": "Oman VAT Registration",
					"company": company,
					"vatin": vatin.upper(),
					"legal_name": legal_name or company,
					"status": "Active",
					"is_default": 1,
					"effective_from": effective_from,
					"return_frequency": return_frequency,
					"first_period_start": first_period_start or effective_from,
				}
			)
			reg.flags.ignore_permissions = True
			reg.insert()
			reg_name = reg.name

	mapping = frappe.db.get_value("Oman VAT Account Mapping", {"company": company, "disabled": 0})
	if not mapping:
		m = frappe.get_doc(
			{
				"doctype": "Oman VAT Account Mapping",
				"company": company,
				"vat_registration": reg_name,
				"output_vat_account": acc["output"],
				"input_vat_account": acc["input"],
				"rcm_output_vat_account": acc["rcm_output"],
				"rcm_input_vat_account": acc["rcm_input"],
				"import_vat_account": acc["import_input"],
				"import_vat_payable_account": acc["import_payable"],
				"customs_vat_clearing_account": acc["customs_clearing"],
				"nonrecoverable_vat_account": acc["nonrecoverable"],
				"vat_adjustment_account": acc["adjustment"],
			}
		)
		m.flags.ignore_permissions = True
		m.insert()
		mapping = m.name
	return {
		"accounts": acc,
		"item_tax_templates": [t5, t0],
		"sales_taxes_template": stc,
		"purchase_taxes_template": ptc,
		"registration": reg_name,
		"account_mapping": mapping,
	}
