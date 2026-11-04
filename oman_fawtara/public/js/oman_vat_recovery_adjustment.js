frappe.ui.form.on("Oman VAT Recovery Adjustment", {
	setup(frm) {
		frm.set_query("recovery_profile", () => ({ filters: { method: "Standard Apportionment" } }));
	},
	refresh(frm) {
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Compute"), () => frm.call("compute").then(() => frm.refresh_fields()));
		}
	},
});
