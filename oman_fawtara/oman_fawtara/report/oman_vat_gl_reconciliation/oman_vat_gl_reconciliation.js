frappe.query_reports["Oman VAT GL Reconciliation"] = {
	filters: [
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company", reqd: 1,
			default: frappe.defaults.get_user_default("Company") },
		{ fieldname: "vat_registration", label: __("VAT Registration"), fieldtype: "Link", options: "Oman VAT Registration", reqd: 1 },
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date", reqd: 1 },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date", reqd: 1 },
	],
};
