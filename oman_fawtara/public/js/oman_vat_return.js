frappe.ui.form.on("Oman VAT Return", {
	setup(frm) {
		frm.set_query("vat_period", () => ({ filters: { vat_registration: frm.doc.vat_registration } }));
		frm.set_query("vat_registration", () => ({ filters: { company: frm.doc.company } }));
	},
	refresh(frm) {
		const colors = { Open: "blue", Validation: "orange", Reviewed: "purple", Finalized: "green", Filed: "green", Locked: "darkgrey" };
		frm.page.set_indicator(__(frm.doc.status), colors[frm.doc.status] || "grey");
		if (frm.is_new()) return;
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Collect Transactions"), () => frm.call("collect_transactions").then(() => frm.reload_doc()), __("Workflow"));
			frm.add_custom_button(__("Run Validation"), () =>
				frm.call("run_validation").then((r) => {
					frm.reload_doc();
					const issues = r.message || [];
					if (!issues.length) return frappe.show_alert({ message: __("No exceptions"), indicator: "green" });
					frappe.msgprint({
						title: __("Return exceptions ({0})", [issues.length]), wide: true,
						message: "<ul>" + issues.map((i) => `<li class="${i.severity === "Error" ? "text-danger" : "text-warning"}">
							<b>${i.code}</b> ${frappe.utils.escape_html(i.message)}</li>`).join("") + "</ul>",
					});
				}), __("Workflow"));
			if (frm.doc.status === "Validation") {
				frm.add_custom_button(__("Mark Reviewed"), () => frm.call("mark_reviewed").then(() => frm.reload_doc()), __("Workflow"));
			}
		}
		if (frm.doc.docstatus === 1) {
			frm.add_custom_button(__("Verify Snapshot"), () =>
				frm.call("verify_snapshot").then((r) => {
					const ok = r.message.reproducible;
					frappe.msgprint({ title: __("Snapshot verification"), indicator: ok ? "green" : "red",
						message: ok ? __("Hash valid and ledger unchanged – the return is reproducible.")
							: __("Hash valid: {0}. Ledger drift: {1}", [r.message.hash_valid, (r.message.ledger_drift || []).join(", ") || "—"]) });
				}));
			if (!frm.doc.filing_record) {
				frm.add_custom_button(__("Record Filing"), () => {
					frappe.new_doc("Oman VAT Filing Record", { vat_return: frm.doc.name });
				}, __("Workflow"));
			}
			if (frm.doc.status === "Filed") {
				frm.add_custom_button(__("Lock Period"), () =>
					frappe.prompt({ fieldname: "note", fieldtype: "Small Text", label: __("Lock note"), reqd: 1 },
						(v) => frm.call("lock_period", { note: v.note }).then(() => frm.reload_doc()),
						__("Lock VAT period"), __("Lock")), __("Workflow"));
			}
		}
	},
});
