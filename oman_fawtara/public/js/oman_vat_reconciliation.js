frappe.ui.form.on("Oman VAT Reconciliation", {
	refresh(frm) {
		frm.add_custom_button(__("Recompute"), () => frm.call("compute").then(() => frm.save()));
	},
	vat_period(frm) {
		if (frm.doc.vat_period) {
			frappe.db.get_value("Oman VAT Period", frm.doc.vat_period, ["from_date", "to_date", "vat_registration"]).then((r) => {
				frm.set_value(r.message);
			});
		}
	},
});
