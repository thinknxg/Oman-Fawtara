frappe.ui.form.on("Oman Fawtara Submission", {
	refresh(frm) {
		const colors = { Accepted: "green", Rejected: "red", Retry: "orange", Pending: "blue", Processing: "blue", Draft: "grey", Cancelled: "grey" };
		frm.page.set_indicator(__(frm.doc.status), colors[frm.doc.status] || "grey");
		if (frm.doc.ota_status) {
			frm.dashboard.add_indicator(__("OTA: {0}", [__(frm.doc.ota_status)]),
				{ Acknowledged: "green", Reported: "green", Failed: "red" }[frm.doc.ota_status] || "orange");
		}
		if (frm.doc.status === "Retry") {
			frm.add_custom_button(__("Retry Now"), () => frm.call("retry").then(() => frm.reload_doc()));
		}
		if (frm.doc.status === "Rejected" && !frm.doc.superseded_by && frappe.user.has_role("Fawtara Manager")) {
			frm.add_custom_button(__("Resubmit after Correction"), () =>
				frappe.prompt({ fieldname: "reason", fieldtype: "Small Text", label: __("What was corrected?"), reqd: 1 },
					(v) => frm.call("resubmit", { reason: v.reason }).then((r) => frappe.set_route("Form", frm.doctype, r.message)),
					__("Authorised resubmission"), __("Resubmit")));
		}
		if (frm.doc.provider_reference && ["Processing", "Accepted"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Refresh Status"), () => frm.call("refresh_status").then(() => frm.reload_doc()));
		}
		frm.add_custom_button(__("Error Log"), () => frappe.set_route("List", "Oman Fawtara Error Log", { submission: frm.doc.name }), __("View"));
		frm.add_custom_button(__("Attempts"), () => frappe.set_route("List", "Oman Fawtara Submission Log", { submission: frm.doc.name }), __("View"));
		if (frm.doc.receipt) {
			frm.add_custom_button(__("Receipt"), () => frappe.set_route("Form", "Oman Fawtara Receipt", frm.doc.receipt), __("View"));
		}
	},
});
