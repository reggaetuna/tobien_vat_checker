app_name = "tobien_vat_checker"
app_title = "Tobien VAT Checker"
app_publisher = "phamos.eu"
app_description = "EU-USt-IdNr. Pruefung (VIES) fuer Sales-Belege"
app_email = "support@phamos.eu"
app_license = "mit"

# include js in doctype views
# Sales Order only - Sales Invoice and the purchase side deliberately
# not wired up, see
# custom_scripts/custom_python/validation.py module docstring.
doctype_js = {
	"Sales Order": "public/js/sales_order.js",
	"Customer": "public/js/customer.js",
	"Address": "public/js/address.js",
}

# Connections tab: link VAT Validation Logs on the documents/customer
override_doctype_dashboards = {
	"Sales Order": "tobien_vat_checker.custom_scripts.custom_python.dashboards.sales_order",
	"Customer": "tobien_vat_checker.custom_scripts.custom_python.dashboards.customer",
}

# Document Events
# ---------------
doc_events = {
	"Sales Order": {
		"validate": "tobien_vat_checker.custom_scripts.custom_python.validation.keep_vat_status",
		"before_update_after_submit": "tobien_vat_checker.custom_scripts.custom_python.validation.keep_vat_status",
		"on_submit": "tobien_vat_checker.custom_scripts.custom_python.validation.start_vat_check",
	},
	"VAT Validation Log": {
		"on_submit": "tobien_vat_checker.custom_scripts.custom_python.validation.attach_pdf_on_submit"
	},
}

# Scheduled Tasks
# ---------------
# retry_pending_checks: keeps retrying documents whose check hit a busy
# VIES. send_invalid_vat_report: daily mail of all open documents with an
# invalid VAT ID.
scheduler_events = {
	"cron": {
		"*/2 * * * *": ["tobien_vat_checker.custom_scripts.custom_python.validation.retry_pending_checks"],
		"0 7 * * *": ["tobien_vat_checker.custom_scripts.custom_python.validation.send_invalid_vat_report"],
	},
}

# Fixtures
# --------
# Only export the Custom Fields this app owns (prefix custom_vat*), so
# `bench --site x export-fixtures` doesn't sweep up unrelated Custom Fields
# already present on the same doctypes. The Sales Invoice fields stay in
# hidden, so their values from before Sales Invoice was dropped are kept.
fixtures = [
	{
		"dt": "Custom Field",
		"filters": [
			["fieldname", "like", "custom_vat%"],
			["dt", "in", ["Sales Order", "Sales Invoice"]],
		],
	},
]
