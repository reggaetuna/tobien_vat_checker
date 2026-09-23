// USt-IdNr.-Pruefung direkt auf der Adresse - der eigentliche Ort, wo
// Address.tax_id gepflegt wird, daher hier der direkteste Weg zum Pruefen
// (siehe auch customer.js fuer den Komfort-Zugang bei der Kunden-Ersterfassung).
frappe.ui.form.on("Address", {
	refresh(frm) {
		if (frm.is_new()) return;
		if (!frm.doc.tax_id) return;

		frm.add_custom_button(__("USt-IdNr. prüfen"), () => {
			frappe.call({
				method: "tobien_vat_checker.custom_scripts.custom_python.validation.check_address",
				args: { address_name: frm.doc.name },
				freeze: true,
				freeze_message: __("Prüfe USt-IdNr. via VIES..."),
				callback: (r) => {
					if (!r.message) return;
					if (r.message.skipped) {
						frappe.show_alert({ message: r.message.message, indicator: "blue" });
						return;
					}
					frappe.show_alert({
						message: r.message.valid
							? __("USt-IdNr. gültig ({0})", [r.message.log])
							: __("USt-IdNr. UNGÜLTIG ({0})", [r.message.log]),
						indicator: r.message.valid ? "green" : "red",
					});
					frappe.set_route("Form", "VAT Validation Log", r.message.log);
				},
			});
		});
	},
});
