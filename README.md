# Tobien VAT Checker

Frappe/ERPNext v15 Custom-App: prüft USt-IdNr. (VAT ID) von EU-Kunden
automatisiert über den **VIES REST-Dienst** der EU-Kommission und hinterlegt
einen für das Finanzamt nachweisbaren, PDF-gestützten Prüfbeleg.

**Scope: erstmal nur Verkauf.** Sales Order, Sales Invoice und Customer.
Purchase Order, Purchase Invoice und Supplier sind bewusst noch nicht
angebunden — die Kernlogik (`custom_scripts/custom_python/validation.py`)
ist doctype-agnostisch gebaut, sodass der Einkauf später einfach durch
Ergänzen von Einträgen in `ADDRESS_FIELD_BY_DOCTYPE`/`PARTY_FIELD_BY_DOCTYPE`,
den `hooks.py` `doc_events`/`doctype_js` und den Custom Fields in
`fixtures/custom_field.json` nachgezogen werden kann.

## Was die App macht

- **Wann geprüft wird:** automatisch bei `Submit` von Sales Order und Sales
  Invoice — plus manueller "USt-IdNr. jetzt prüfen"-Button auf dem Beleg
  (damit der Sachbearbeiter nicht erst beim harten Submit-Block überrascht
  wird), direkt auf der **Address** (dort steht `tax_id` — der direkteste
  Weg, v. a. wenn ein Kunde mehrere EU-Adressen hat) sowie zusätzlich auf
  **Customer** als Komfort-Zugang für die Ersterfassung (wählt bei
  mehreren Adressen eine per Dialog aus, ruft intern dieselbe
  Adress-Prüfung auf).
- **Wo geprüft wird:** nur wenn die relevante Adresse in der EU liegt (Filter
  über `Address.country`, siehe `vies.EU_COUNTRY_CODE_BY_NAME`). Nicht-EU-
  Adressen werden komplett übersprungen (kein Fehler, kein Log-Eintrag).
- **Welche Adresse:** die **Lieferadresse** (`shipping_address_name`) der
  Sales Order/Sales Invoice, da sie den tatsächlichen Warenfluss abbildet.
- **Prüfquelle:** [VIES REST-API](https://ec.europa.eu/taxation_customs/vies/rest-api/check-vat-number)
  der EU-Kommission. Die eigene USt-IdNr. wird als `requesterNumber`
  mitgeschickt — dadurch liefert VIES eine `requestIdentifier`
  (Consultation Number) zurück, die von den Finanzbehörden als Nachweis
  der Prüfung anerkannt wird.
- **Nachweis:** jede Prüfung erzeugt einen submitteten `VAT Validation Log`
  mit Zeitstempel, Consultation Number, VIES-Rohantwort (JSON) und
  Namens-/Adressabgleich — und wird automatisch als PDF an sich selbst
  angehängt (`on_submit` → Standard-Print-Format → PDF-Attachment).
- **Submit-Block:** ungültige/fehlende USt-IdNr. auf einer EU-Adresse
  verhindert das Buchen des Belegs (`before_submit`, `frappe.throw`). Ein
  Override-Feld (`custom_vat_override` + Begründung) erlaubt System-/Sales
  Manager, bei nachweislichem VIES-Ausfall trotzdem zu buchen — die
  Übersteuerung wird als Alert protokolliert.
- **Verlinkung zur SO/SI:** eigenes Feld `custom_vat_validation` (Link auf
  den Log) direkt auf dem Beleg sichtbar.
- **Ein-/Ausschalten:** eigene Settingsseite **"VAT Check Settings"**
  (Single-DocType, per Awesomebar-Suche erreichbar) mit einem Häkchen
  "Automatische Prüfung beim Buchen aktiv". Schaltet ausschließlich den
  automatischen `before_submit`-Check (inkl. hartem Block) ab — die
  manuellen "USt-IdNr. prüfen"-Buttons auf Address/Customer/Beleg
  funktionieren davon unabhängig immer. Standard: aktiv. Berechtigt:
  System Manager, Sales Manager.

## Hinweise zum Datenmodell

- **VAT-ID-Feld:** `tax_id` (Custom Field auf Address).
- **Adressfeld Sales Order/Sales Invoice:** `shipping_address_name`.
- **EU-Filter:** läuft über `Address.country` (statische Länderliste in
  `vies.py`), nicht über das `territory`-Feld auf Sales Order/Sales
  Invoice/Customer — Territory bildet die interne Vertriebsregion-
  Einteilung ab und ist nicht garantiert deckungsgleich mit tatsächlicher
  EU-Mitgliedschaft.
- **Eigene USt-IdNr.:** wird aus `Company.tax_id` gelesen.
- **Northern Ireland (XI):** nicht separat behandelt, da Frappes
  Standard-Country-Liste UK/NI nicht trennt — falls relevant, eigenes
  Handling ergänzen.
- Auf Address zusätzlich vorhanden, aber (noch) nicht genutzt:
  `tax_category` (Link "Tax Category") und `eori_no` — könnten für eine
  spätere Erweiterung relevant sein (z. B. Zollbezug/EORI-Nachweis neben
  der reinen USt-IdNr.-Prüfung).

## Installation

```bash
bench get-app https://github.com/reggaetuna/tobien_vat_checker
bench --site <site> install-app tobien_vat_checker
bench --site <site> migrate
```

Immer mit der vollen Repo-URL installieren, nie nur mit dem bloßen Namen
(`bench get-app tobien_vat_checker` ohne URL würde bench veranlassen, den
Namen im öffentlichen Frappe-App-Verzeichnis nachzuschlagen).

Die Custom Fields (`custom_vat_validation`, `custom_vat_override`,
`custom_vat_override_reason` auf SO/SI) kommen als Fixture
(`fixtures/custom_field.json`) mit und werden bei `migrate` importiert.

## Offene Punkte / mögliche Erweiterungen

- **Einkauf (Purchase Order/Purchase Invoice/Supplier):** aktuell bewusst
  außen vor. Bei Bedarf nachziehen — voraussichtliches Adressfeld:
  `supplier_address` (die Lieferanten-eigene Adresse, nicht die eigene
  Empfangsadresse `shipping_address`), noch nicht gegen die echten
  Purchase-Doctypes verifiziert.
- Eigenes Print Format für `VAT Validation Log` statt Standard-Layout, falls
  ein bestimmtes Finanzamt-taugliches Layout gewünscht ist.
- Wiederholungsprüfung: aktuell wird nur einmal je Submit geprüft — kein
  automatischer Re-Check bei Änderung der Lieferadresse nach Submit oder
  turnusmäßige Re-Validierung bestehender Kunden.
