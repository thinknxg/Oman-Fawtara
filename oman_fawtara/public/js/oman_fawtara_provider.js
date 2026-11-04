frappe.ui.form.on("Oman Fawtara Provider", {
	onload(frm) {
		frappe.call("oman_fawtara.fawtara.providers.get_adapter_names").then((r) => {
			frm.set_df_property("adapter", "description", __("Available: {0}", [(r.message || []).join(", ")]));
		});
	},
	refresh(frm) {
		if (!frm.is_new()) {
			frm.add_custom_button(__("Test Connection"), () => frm.call("test_connection").then((r) =>
				frappe.show_alert({ message: r.message.message, indicator: r.message.ok ? "green" : "red" })));
		}
	},
});
