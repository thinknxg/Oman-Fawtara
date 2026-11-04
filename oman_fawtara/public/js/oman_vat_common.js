// thinkNXG Oman Fawtara – shared invoice helpers
frappe.provide("oman_fawtara");

oman_fawtara.status_colors = {
	Passed: "green", Warnings: "orange", Failed: "red",
	Accepted: "green", Reported: "green", Acknowledged: "green",
	Pending: "blue", Processing: "blue", Draft: "grey", Retry: "orange",
	Rejected: "red", Cancelled: "grey", "Not Required": "grey",
};

oman_fawtara.setup_invoice = function (frm) {
	if (frm.doc.oman_vat_validation_status) {
		frm.dashboard.add_indicator(
			__("Oman VAT: {0}", [__(frm.doc.oman_vat_validation_status)]),
			oman_fawtara.status_colors[frm.doc.oman_vat_validation_status] || "grey"
		);
	}
	if (frm.doc.docstatus === 1 && frm.doc.oman_fawtara_status) {
		frm.dashboard.add_indicator(
			__("Fawtara: {0}", [__(frm.doc.oman_fawtara_status)]),
			oman_fawtara.status_colors[frm.doc.oman_fawtara_status] || "grey"
		);
	}
	if (frm.doc.oman_vat_issues && frm.doc.docstatus === 0) {
		const issues = JSON.parse(frm.doc.oman_vat_issues || "[]");
		if (issues.length) {
			const html = issues
				.map((i) => `<div class="${i.severity === "Error" ? "text-danger" : "text-warning"}">• ${frappe.utils.escape_html(i.message)}</div>`)
				.join("");
			frm.dashboard.set_headline_alert(`<div><b>${__("Oman VAT")}</b>${html}</div>`, "yellow");
		}
	}

	frm.add_custom_button(__("Preview VAT"), () => {
		frappe.call({
			method: "oman_fawtara.api.preview_vat",
			args: { doc: frm.doc },
			callback(r) {
				const d = r.message;
				const rows = d.lines.map((l) => `<tr><td>${l.idx}</td><td>${frappe.utils.escape_html(l.item_code || "")}</td>
					<td>${l.treatment}</td><td>${l.rate}%</td><td class="text-right">${format_number(l.taxable, null, 3)}</td>
					<td class="text-right">${format_number(l.output_vat || l.input_vat, null, 3)}</td>
					<td class="text-right">${format_number(l.recoverable, null, 3)}</td></tr>`).join("");
				const issues = d.issues.map((i) => `<li class="${i.severity === "Error" ? "text-danger" : "text-warning"}">${frappe.utils.escape_html(i.message)}</li>`).join("");
				frappe.msgprint({
					title: __("Oman VAT – {0}", [d.status]),
					wide: true,
					message: `<table class="table table-bordered table-sm"><thead><tr><th>#</th><th>${__("Item")}</th>
						<th>${__("Treatment")}</th><th>${__("Rate")}</th><th>${__("Taxable OMR")}</th><th>${__("VAT OMR")}</th>
						<th>${__("Recoverable")}</th></tr></thead><tbody>${rows}</tbody></table>
						<p>${__("ERPNext VAT rows")}: ${format_number(d.totals.erpnext_vat_total, null, 3)} ·
						${__("Difference")}: ${format_number(d.totals.reconciliation_difference, null, 3)}</p>
						${issues ? `<ul>${issues}</ul>` : ""}`,
				});
			},
		});
	}, __("Oman VAT"));

	if (frm.doc.docstatus === 1) {
		frm.add_custom_button(__("VAT Transaction"), () =>
			frappe.set_route("List", "Oman VAT Transaction", { source_name: frm.doc.name }), __("Oman VAT"));
		frm.add_custom_button(__("Preview E-invoice XML"), () => {
			frappe.call({
				method: "oman_fawtara.api.fawtara_preview_xml",
				args: { doctype: frm.doctype, name: frm.doc.name },
				callback(r) {
					const issues = (r.message.issues || []).map((i) => `<li>[${i.code}] ${frappe.utils.escape_html(i.message)}</li>`).join("");
					frappe.msgprint({ title: __("Fawtara XML"), wide: true,
						message: `${issues ? `<ul class="text-danger">${issues}</ul>` : ""}<pre style="max-height:60vh;overflow:auto">${frappe.utils.escape_html(r.message.xml)}</pre>` });
				},
			});
		}, __("Fawtara"));
		if (frm.doc.oman_fawtara_submission) {
			frm.add_custom_button(__("Submission"), () =>
				frappe.set_route("Form", "Oman Fawtara Submission", frm.doc.oman_fawtara_submission), __("Fawtara"));
		} else if (frappe.user.has_role("Fawtara Manager") && frm.doc.oman_fawtara_status !== "Not Required") {
			frm.add_custom_button(__("Send to Fawtara"), () =>
				frappe.call({ method: "oman_fawtara.fawtara.queue.submit_document", args: { doctype: frm.doctype, name: frm.doc.name },
					callback: () => frm.reload_doc() }), __("Fawtara"));
		}
	}
};

oman_fawtara.registration_query = function (frm) {
	frm.set_query("oman_vat_registration", () => ({ filters: { company: frm.doc.company, status: "Active" } }));
	frm.set_query("oman_vat_code", "items", () => ({ filters: { disabled: 0 } }));
	frm.set_query("oman_recovery_profile", "items", () => ({ filters: { status: "Approved", disabled: 0 } }));
};
