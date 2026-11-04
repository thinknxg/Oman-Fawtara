{% include "oman_fawtara/public/js/oman_vat_common.js" %}

frappe.ui.form.on("Sales Invoice", {
	setup(frm) { oman_fawtara.registration_query(frm); },
	refresh(frm) { oman_fawtara.setup_invoice(frm); },
});

frappe.ui.form.on("Sales Invoice Item", {
	oman_vat_treatment(frm, cdt, cdn) { frappe.model.set_value(cdt, cdn, "oman_vat_source", "line"); },
	oman_vat_code(frm, cdt, cdn) { frappe.model.set_value(cdt, cdn, "oman_vat_source", "line-code"); },
	item_code(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!["line", "line-code"].includes(row.oman_vat_source)) {
			frappe.model.set_value(cdt, cdn, { oman_vat_treatment: null, oman_vat_code: null, oman_vat_source: null });
		}
	},
});
