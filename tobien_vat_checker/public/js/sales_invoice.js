// USt-IdNr.-Pruefung (VIES) - manueller "jetzt pruefen" Button vor dem Buchen,
// damit der harte Submit-Block (siehe validation.enforce_vat_check) niemanden
// ueberrascht. Ist VIES ueberlastet, laeuft die Pruefung im Hintergrund weiter
// (validation.retry_pending_checks), Status steht in custom_vat_status.
frappe.ui.form.on("Sales Invoice", {
	refresh(frm) {
		if (frm.doc.docstatus !== 0 || frm.is_new()) return;
		if (!frm.doc.shipping_address_name) return;

		if (frm.doc.custom_vat_status === "VIES ueberlastet - Pruefung laeuft") {
			frm.set_intro(
				__("VIES ist überlastet - die USt-IdNr. wird im Hintergrund automatisch weiter geprüft. Sobald das Ergebnis da ist, kommt eine Benachrichtigung."),
				"orange"
			);
		}

		frm.add_custom_button(__("USt-IdNr. jetzt prüfen"), () => {
			frappe.call({
				method: "tobien_vat_checker.custom_scripts.custom_python.validation.check_now",
				args: { reference_doctype: frm.doctype, reference_name: frm.doc.name },
				freeze: true,
				freeze_message: __("Prüfe USt-IdNr. via VIES..."),
				callback: (r) => {
					if (!r.message) return;
					frm.reload_doc();
					if (r.message.skipped || r.message.pending) {
						frappe.show_alert({
							message: r.message.message,
							indicator: r.message.pending ? "orange" : "blue",
						});
						return;
					}
					frappe.show_alert({
						message: r.message.valid
							? __("USt-IdNr. gültig ({0})", [r.message.log])
							: __("USt-IdNr. UNGÜLTIG ({0})", [r.message.log]),
						indicator: r.message.valid ? "green" : "red",
					});
				},
			});
		});
	},
});
