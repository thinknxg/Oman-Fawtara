app_name = "oman_fawtara"
app_title = "thinkNXG Oman Fawtara"
app_publisher = "thinkNXG"
app_description = "Oman VAT compliance, VAT returns and Fawtara e-invoicing for thinkNXG ERP (ERPNext v16)"
app_email = "kreataothinkcadd@gmail.com"
app_license = "MIT"
required_apps = ["frappe", "erpnext"]
app_home = "/desk/oman-fawtara"

add_to_apps_screen = [
	{
		"name": app_name,
		"logo": "/assets/oman_fawtara/images/oman_fawtara.svg",
		"title": "Oman Fawtara",
		"route": app_home,
		"has_permission": "oman_fawtara.install.has_app_permission",
	}
]

app_include_css = []

doctype_js = {
	"Sales Invoice": "public/js/sales_invoice.js",
	"Purchase Invoice": "public/js/purchase_invoice.js",
	"Oman VAT Return": "public/js/oman_vat_return.js",
	"Oman Fawtara Submission": "public/js/oman_fawtara_submission.js",
	"Oman VAT Registration": "public/js/oman_vat_registration.js",
	"Oman Fawtara Provider": "public/js/oman_fawtara_provider.js",
	"Oman VAT Reconciliation": "public/js/oman_vat_reconciliation.js",
	"Oman VAT Recovery Adjustment": "public/js/oman_vat_recovery_adjustment.js",
}

after_install = "oman_fawtara.install.after_install"
after_migrate = "oman_fawtara.install.after_migrate"
before_uninstall = "oman_fawtara.install.before_uninstall"

_invoice_events = {
	"before_validate": "oman_fawtara.events.invoice.before_validate",
	"validate": "oman_fawtara.events.invoice.validate",
	"before_submit": "oman_fawtara.events.invoice.before_submit",
	"on_submit": "oman_fawtara.events.invoice.on_submit",
	"before_cancel": "oman_fawtara.events.invoice.before_cancel",
	"on_cancel": "oman_fawtara.events.invoice.on_cancel",
	"before_update_after_submit": "oman_fawtara.events.invoice.before_update_after_submit",
}

doc_events = {
	"Sales Invoice": _invoice_events,
	"Purchase Invoice": _invoice_events,
	"Journal Entry": {
		"before_submit": "oman_fawtara.events.invoice.journal_before_submit",
		"before_cancel": "oman_fawtara.events.invoice.journal_before_cancel",
	},
	"Customer": {"validate": "oman_fawtara.events.invoice.party_validate"},
	"Supplier": {"validate": "oman_fawtara.events.invoice.party_validate"},
}

scheduler_events = {
	"cron": {
		"*/5 * * * *": ["oman_fawtara.fawtara.queue.process_due"],
		"*/15 * * * *": ["oman_fawtara.fawtara.queue.poll_status"],
	},
	"hourly": ["oman_fawtara.fawtara.queue.check_providers"],
	"daily": [
		"oman_fawtara.vat.period.ensure_future_periods",
		"oman_fawtara.oman_fawtara.doctype.oman_fawtara_certificate.oman_fawtara_certificate.check_expiry",
	],
}

# Other apps can register accredited-provider adapters:
# oman_fawtara_provider_adapters = {"Provider Label": "dotted.path.AdapterClass"}

fixtures = []

# Documents ignored when cancelling linked documents
ignore_links_on_delete = [
	"Oman VAT Transaction",
	"Oman VAT Validation Log",
	"Oman Compliance Audit Log",
	"Oman Fawtara Submission",
	"Oman Fawtara Submission Log",
	"Oman Fawtara Error Log",
]

export_python_type_annotations = False
