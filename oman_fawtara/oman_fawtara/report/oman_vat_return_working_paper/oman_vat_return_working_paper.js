frappe.query_reports["Oman VAT Return Working Paper"] = {
	filters: [
		{ fieldname: "vat_period", label: __("VAT Period"), fieldtype: "Link", options: "Oman VAT Period", reqd: 1 },
	],
};
