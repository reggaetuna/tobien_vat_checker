// Copyright (c) 2026, phamos.eu and contributors
// For license information, please see license.txt

frappe.ui.form.on("VAT Validation Log", {
	refresh(frm) {
		if (frm.doc.reference_doctype && frm.doc.reference_name) {
			frm.add_custom_button(__("Beleg öffnen"), () => {
				frappe.set_route("Form", frm.doc.reference_doctype, frm.doc.reference_name);
			});
		}

		// Ergebnis gross oben im Formular, nicht nur als Checkbox "Gültig"
		if (frm.is_new()) return;
		const vat_id = `${frm.doc.country_code || ""}${frm.doc.vat_number || ""}`;
		if (frm.doc.valid) {
			frm.dashboard.set_headline_alert(
				__("USt-IdNr. {0} ist laut VIES gültig.", [vat_id]),
				"green"
			);
		} else {
			frm.dashboard.set_headline_alert(
				__("USt-IdNr. {0} ungültig: {1}", [
					vat_id || "-",
					frappe.utils.escape_html(frm.doc.error_message || ""),
				]),
				"red"
			);
		}
	},
});
