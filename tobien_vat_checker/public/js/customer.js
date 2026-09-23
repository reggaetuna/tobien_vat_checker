// USt-IdNr. bei der Kunden-Ersterfassung oder jederzeit manuell pruefen.
// Bei mehreren Adressen zeigt ein Dialog die Auswahl an.
frappe.ui.form.on("Customer", {
	refresh(frm) {
		if (frm.is_new()) return;

		frm.add_custom_button(__("USt-IdNr. prüfen"), () => {
			frappe.call({
				method: "tobien_vat_checker.custom_scripts.custom_python.validation.get_party_addresses",
				args: { party_type: "Customer", party_name: frm.doc.name },
				callback: (r) => {
					const addresses = r.message || [];
					if (!addresses.length) {
						frappe.msgprint(__("Keine Adresse für diesen Kunden hinterlegt."));
						return;
					}
					if (addresses.length === 1) {
						run_check(frm, "Customer", addresses[0].name);
						return;
					}
					const dialog = new frappe.ui.Dialog({
						title: __("Adresse für USt-IdNr.-Prüfung wählen"),
						fields: [
							{
								fieldname: "address",
								fieldtype: "Select",
								label: __("Adresse"),
								options: addresses.map(
									(a) => `${a.name}::${a.address_line1 || ""}, ${a.city || ""} (${a.country || ""})`
								),
								reqd: 1,
							},
						],
						primary_action_label: __("Prüfen"),
						primary_action: (values) => {
							dialog.hide();
							run_check(frm, "Customer", values.address.split("::")[0]);
						},
					});
					dialog.show();
				},
			});
		});
	},
});

function run_check(frm, party_type, address_name) {
	frappe.call({
		method: "tobien_vat_checker.custom_scripts.custom_python.validation.check_customer_or_supplier",
		args: { party_type: party_type, party_name: frm.doc.name, address_name: address_name },
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
}
