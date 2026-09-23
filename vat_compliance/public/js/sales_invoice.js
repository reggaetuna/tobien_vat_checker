// USt-IdNr.-Pruefung (VIES) - manueller "jetzt pruefen" Button vor dem Buchen,
// damit der harte Submit-Block (siehe validation.enforce_vat_check) niemanden
// ueberrascht.
frappe.ui.form.on("Sales Invoice", {
	refresh(frm) {
		if (frm.doc.docstatus !== 0) return;
		if (!frm.doc.shipping_address_name) return;

		frm.add_custom_button(__("USt-IdNr. jetzt prüfen"), () => {
			frappe.call({
				method: "vat_compliance.custom_scripts.custom_python.validation.check_now",
				args: { reference_doctype: frm.doctype, reference_name: frm.doc.name },
				freeze: true,
				freeze_message: __("Prüfe USt-IdNr. via VIES..."),
				callback: (r) => {
					if (!r.message) return;
					if (r.message.skipped) {
						frappe.show_alert({ message: r.message.message, indicator: "blue" });
						return;
					}
					frm.reload_doc();
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
