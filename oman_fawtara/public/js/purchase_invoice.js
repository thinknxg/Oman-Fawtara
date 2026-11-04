{% include "oman_fawtara/public/js/oman_vat_common.js" %}

frappe.ui.form.on("Purchase Invoice", {
	setup(frm) {
		oman_fawtara.registration_query(frm);
		frm.set_query("oman_import_declaration", () => ({ filters: { company: frm.doc.company, docstatus: 1 } }));
	},
	refresh(frm) {
		oman_fawtara.setup_invoice(frm);
		if (frm.doc.docstatus === 1 && frm.doc.oman_reverse_charge_entry) {
			frm.add_custom_button(__("Reverse Charge Entry"), () =>
				frappe.set_route("Form", "Oman Reverse Charge Entry", frm.doc.oman_reverse_charge_entry), __("Oman VAT"));
		}
		if (frm.doc.docstatus === 1 && frm.doc.oman_recovery_allocation) {
			frm.add_custom_button(__("Recovery Allocation"), () =>
				frappe.set_route("Form", "Oman VAT Recovery Allocation", frm.doc.oman_recovery_allocation), __("Oman VAT"));
		}
	},
});

frappe.ui.form.on("Purchase Invoice Item", {
	oman_recovery_override(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (row.oman_recovery_override && !frappe.user.has_role("Oman VAT Approver")) {
			frappe.msgprint(__("Only an Oman VAT Approver can override recovery. The override will be rejected on save."));
		}
	},
});

frappe.ui.form.on("Purchase Invoice Item", {
	oman_vat_treatment(frm, cdt, cdn) { frappe.model.set_value(cdt, cdn, "oman_vat_source", "line"); },
	oman_vat_code(frm, cdt, cdn) { frappe.model.set_value(cdt, cdn, "oman_vat_source", "line-code"); },
	item_code(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!["line", "line-code"].includes(row.oman_vat_source)) {
			frappe.model.set_value(cdt, cdn, { oman_vat_treatment: null, oman_vat_code: null, oman_vat_source: null });
		}
	},
});
