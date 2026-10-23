// USt-IdNr.-Pruefung (VIES) - laeuft nach dem Buchen im Hintergrund
// (validation.start_vat_check), Ergebnis steht in custom_vat_status und
// wird oben neben dem Belegstatus (z. B. "To Deliver and Bill") als
// farbiger Status angezeigt. "jetzt pruefen" geht vor dem Buchen und zum
// erneuten Pruefen, wenn die USt-IdNr. auf der Adresse korrigiert wurde.
frappe.ui.form.on("Sales Order", {
	setup(frm) {
		// status changes from the background check, see validation._store_vat_status
		frappe.realtime.on("vat_status_changed", (data) => {
			if (data.doctype !== frm.doctype || data.name !== frm.doc.name) return;
			frm.doc.custom_vat_status = data.status;
			frm.doc.custom_vat_validation = data.log;
			frm.refresh_fields(["custom_vat_status", "custom_vat_validation"]);
			show_vat_indicator(frm);
		});
	},

	refresh(frm) {
		show_vat_indicator(frm);

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

function show_vat_indicator(frm) {
	frm.page.wrapper.find(".vat-status-indicator").remove();
	const indicator = {
		"Pruefung laeuft": ["orange", __("VAT: Prüfung läuft")],
		"VIES ueberlastet - Pruefung laeuft": ["orange", __("VAT: VIES überlastet")],
		Gueltig: ["green", __("VAT gültig")],
		Ungueltig: ["red", __("VAT ungültig")],
	}[frm.doc.custom_vat_status];
	if (!indicator) return;

	$(`<span class="indicator-pill whitespace-nowrap vat-status-indicator ${indicator[0]}"
			style="margin-left: var(--margin-sm)"></span>`)
		.append($("<span>").text(indicator[1]))
		.insertAfter(frm.page.indicator);
}
