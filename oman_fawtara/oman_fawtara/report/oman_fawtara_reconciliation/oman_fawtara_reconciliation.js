frappe.query_reports["Oman Fawtara Reconciliation"] = {
	filters: [
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company", reqd: 1,
			default: frappe.defaults.get_user_default("Company") },
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date", reqd: 1, default: frappe.datetime.month_start() },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date", reqd: 1, default: frappe.datetime.get_today() },
		{ fieldname: "only_exceptions", label: __("Only Exceptions"), fieldtype: "Check", default: 1 },
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "exception" && data && data.exception) {
			value = `<span style="color: var(--red-600)">${value}</span>`;
		}
		return value;
	},
};
