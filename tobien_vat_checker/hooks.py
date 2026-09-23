app_name = "tobien_vat_checker"
app_title = "Tobien VAT Checker"
app_publisher = "phamos.eu"
app_description = "EU-USt-IdNr. Pruefung (VIES) fuer Sales-Belege"
app_email = "support@phamos.eu"
app_license = "mit"

# include js in doctype views
# Sales-only scope for now - Purchase Order/Purchase Invoice/Supplier
# deliberately not wired up yet, see
# custom_scripts/custom_python/validation.py module docstring.
doctype_js = {
	"Sales Order": "public/js/sales_order.js",
	"Sales Invoice": "public/js/sales_invoice.js",
	"Customer": "public/js/customer.js",
	"Address": "public/js/address.js",
}

# Document Events
# ---------------
doc_events = {
	"Sales Order": {
		"before_submit": "tobien_vat_checker.custom_scripts.custom_python.validation.enforce_vat_check"
	},
	"Sales Invoice": {
		"before_submit": "tobien_vat_checker.custom_scripts.custom_python.validation.enforce_vat_check"
	},
	"VAT Validation Log": {
		"on_submit": "tobien_vat_checker.custom_scripts.custom_python.validation.attach_pdf_on_submit"
	},
}

# Fixtures
# --------
# Only export the Custom Fields this app owns (prefix custom_vat*), so
# `bench --site x export-fixtures` doesn't sweep up unrelated Custom Fields
# already present on the same doctypes.
fixtures = [
	{
		"dt": "Custom Field",
		"filters": [
			["fieldname", "like", "custom_vat%"],
			["dt", "in", ["Sales Order", "Sales Invoice"]],
		],
	},
]
