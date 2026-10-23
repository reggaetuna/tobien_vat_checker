// USt-IdNr.-Pruefung (VIES) - laeuft nach dem Buchen im Hintergrund
// (validation.start_vat_check), Ergebnis steht in custom_vat_status.
// "jetzt pruefen" geht vor dem Buchen und zum erneuten Pruefen, wenn die
// USt-IdNr. auf der Adresse korrigiert wurde.
frappe.ui.form.on("Sales Invoice", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.docstatus === 2) return;
		if (!frm.doc.shipping_address_name) return;
		if (frm.doc.docstatus === 1 && frm.doc.custom_vat_status === "Gueltig") return;

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
