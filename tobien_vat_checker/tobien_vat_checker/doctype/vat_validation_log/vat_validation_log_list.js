// Gruen = USt-IdNr. gueltig, Rot = ungueltig/Pruefung fehlgeschlagen.
// Ersetzt den generischen "Submitted"-Status, den jedes Log ohnehin hat.
frappe.listview_settings["VAT Validation Log"] = {
	add_fields: ["valid", "error_message"],
	get_indicator(doc) {
		if (doc.valid) {
			return [__("Gültig"), "green", "valid,=,1"];
		}
		return [__("Ungültig"), "red", "valid,=,0"];
	},
};
