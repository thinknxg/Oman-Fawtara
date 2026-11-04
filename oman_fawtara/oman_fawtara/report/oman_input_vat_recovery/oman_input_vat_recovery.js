frappe.query_reports["Oman Input VAT Recovery"] = {
	filters: [
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company", reqd: 1,
			default: frappe.defaults.get_user_default("Company") },
		{ fieldname: "vat_registration", label: __("VAT Registration"), fieldtype: "Link", options: "Oman VAT Registration",
			get_query: () => ({ filters: { company: frappe.query_report.get_filter_value("company") } }) },
		{ fieldname: "vat_period", label: __("VAT Period"), fieldtype: "Link", options: "Oman VAT Period" },
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date" },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date" },
		{ fieldname: "treatment", label: __("Treatment"), fieldtype: "Link", options: "Oman VAT Treatment" },
		{ fieldname: "only_restricted", label: __("Only Restricted Recovery"), fieldtype: "Check" }
	],
};
