frappe.ui.form.on("Oman VAT Registration", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("Generate Periods"), () => frm.call("generate_periods", { count: 4 }).then(() =>
			frappe.set_route("List", "Oman VAT Period", { vat_registration: frm.doc.name })));
		frm.add_custom_button(__("Compute Annual Supplies"), () =>
			frappe.call({ method: "oman_fawtara.fawtara.applicability.compute_annual_supplies", args: { registration: frm.doc.name },
				callback: (r) => { frappe.msgprint(__("Computed supplies: {0} OMR. Mandate date: {1}",
					[format_number(r.message.computed, null, 3), r.message.mandate_date])); frm.reload_doc(); } }), __("Fawtara"));
	},
});
