# Tobien VAT Checker

Frappe/ERPNext v15 Custom-App: prüft USt-IdNr. (VAT ID) von EU-Kunden
automatisiert über den **VIES REST-Dienst** der EU-Kommission und hinterlegt
einen für das Finanzamt nachweisbaren, PDF-gestützten Prüfbeleg.

Gebaut für das Ticket **"VAT - UID prüfen"** (Frederic Tobien, erstellt vor
ca. 1 Monat) — daher der App-Name. Ursprünglich `vat_compliance` genannt,
aber umbenannt, weil dieser Name bereits von einem echten, unabhängigen
Frappe-App ("Bangladesh VAT Compliance" von Invento Software) belegt ist —
`bench get-app vat_compliance` hätte sonst versehentlich das falsche,
fremde App installiert statt dieses hier.

Entstanden als eigenständige Schwester-App zu
[`edevis`](https://github.com/edevis/edevis), das bereits einen
BZSt-basierten VAT-Checker für Customer/Supplier hat — hier bewusst neu
konzipiert, weil Scope, Trigger-Zeitpunkt und Prüfquelle abweichen (siehe
Tabelle unten).

**Scope (Stand 2026-09-23, Entscheidung des Nutzers): erstmal nur Verkauf.**
Sales Order, Sales Invoice und Customer. Purchase Order, Purchase Invoice
und Supplier sind bewusst noch nicht angebunden — die Kernlogik
(`custom_scripts/custom_python/validation.py`) ist doctype-agnostisch
gebaut, sodass der Einkauf später einfach durch Ergänzen von Einträgen in
`ADDRESS_FIELD_BY_DOCTYPE`/`PARTY_FIELD_BY_DOCTYPE`, den `hooks.py`
`doc_events`/`doctype_js` und den Custom Fields in
`fixtures/custom_field.json` nachgezogen werden kann.

## Was die App macht

- **Wann geprüft wird:** automatisch bei `Submit` von Sales Order und Sales
  Invoice — plus manueller "USt-IdNr. jetzt prüfen"-Button auf dem Beleg
  (damit der Sachbearbeiter nicht erst beim harten Submit-Block überrascht
  wird), direkt auf der **Address** (dort steht `tax_id` ja tatsächlich —
  der direkteste Weg, v.a. wenn ein Kunde mehrere EU-Adressen hat) sowie
  zusätzlich auf **Customer** als Komfort-Zugang für die Ersterfassung
  (wählt bei mehreren Adressen eine per Dialog aus, ruft intern dieselbe
  Adress-Prüfung auf).
- **Wo geprüft wird:** nur wenn die relevante Adresse in der EU liegt (Filter
  über `Address.country`, siehe `vies.EU_COUNTRY_CODE_BY_NAME`). Nicht-EU-
  Adressen werden komplett übersprungen (kein Fehler, kein Log-Eintrag).
- **Welche Adresse:** die **Lieferadresse** (`shipping_address_name`) —
  genau wie im Ticket gefordert, weil sie den Warenfluss abbildet.
- **Prüfquelle:** [VIES REST-API](https://ec.europa.eu/taxation_customs/vies/rest-api/check-vat-number)
  (Nachfolger des alten SOAP-`checkVatService`, den `edevis` nutzt). Eigene
  USt-IdNr. wird als `requesterNumber` mitgeschickt — dadurch liefert VIES
  eine `requestIdentifier` (Consultation Number) zurück, die von den
  Finanzbehörden als Nachweis der Prüfung anerkannt wird.
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
  funktionieren davon unabhängig immer. Standard: aktiv. Nützlich zum
  Testen/Rollout, ohne die App deinstallieren oder Felder entfernen zu
  müssen. Berechtigt: System Manager, Sales Manager.

## Unterschiede zum edevis-Checker (zur Einordnung)

| | edevis (`checkvat.py`) | diese App |
|---|---|---|
| Trigger | manueller Button auf Customer/Supplier | automatisch bei Submit von SO/SI + manuelle Buttons überall |
| Prüfquelle | BZSt (`evatr.bff-online.de`) primär, VIES SOAP Fallback | nur VIES REST |
| Adresse | Customer-Primäradresse | Lieferadresse |
| Territory-Filter | keiner | nur EU-Adressen |
| Submit-Block | keiner | ja, hart |
| Scope | Customer/Supplier | SO, SI, + Customer-Ersterfassung (erstmal nur Verkauf) |

## ⚠️ Vor der Installation prüfen (ASSUMPTIONS)

Diese App wurde zunächst ohne Zugriff auf den echten Kunden-Bench gebaut.
Die Kernannahmen für den aktuellen (Verkaufs-)Scope sind inzwischen anhand
echter Customize-Form-/DocType-Exports **bestätigt**:

1. ✅ **VAT-ID-Feld auf Address — bestätigt:** `tax_id` (Data, Custom Field,
   `Address-tax_id`) existiert exakt so auf der echten Adresse.
   `ADDRESS_VAT_FIELDNAME = "tax_id"` in `validation.py` ist korrekt.
2. ✅ **Adressfeld Sales Order/Sales Invoice — bestätigt:**
   `shipping_address_name` existiert 1:1 auf beiden echten DocTypes.
3. ✅ **Territory-Filter — geklärt:** der echte `Address`-Export zeigt **kein**
   Territory-Feld (nur `country`, `tax_category`, `eori_no`, `incoterm`,
   `branch_gln`, EDI-Sektion). Der implementierte Filter über
   `Address.country` gegen `vies.EU_COUNTRY_CODE_BY_NAME` ist damit nicht
   nur ein Fallback, sondern die einzig mögliche und korrekte Umsetzung des
   im Ticket geforderten "Territory = EU"-Filters.
4. **Eigene USt-IdNr.:** wird aus `Company.tax_id` gelesen (Standard-Feld,
   unverändert plausibel, aber noch nicht am echten System geprüft).
5. **Northern Ireland (XI):** nicht separat behandelt, da Frappes
   Standard-Country-Liste UK/NI nicht trennt — falls relevant, eigenes
   Handling ergänzen.
6. **EU-Filter — Entscheidung getroffen (2026-09-23):** Sales Order und
   Sales Invoice haben zwar beide ein eigenes `territory`-Feld (Link auf
   "Territory", bei SO Teil der `search_fields`), das wörtlich näher am
   Ticket-Text "Territory = EU" liegt als `Address.country`. Bewusst
   dagegen entschieden: Territory bildet die eigene Vertriebsregion-
   Einteilung ab und ist nicht garantiert deckungsgleich mit tatsächlicher
   EU-Mitgliedschaft oder konsequent gepflegt, während `Address.country`
   ein Pflichtfeld und geografisch eindeutig ist. Der Country-basierte
   Filter bleibt daher die alleinige Prüfgrundlage — Territory wird
   aktuell gar nicht ausgewertet. (Nebenbefund: Beide Belege haben
   außerdem ein eigenes `tax_id`-Feld, das aber `customer.tax_id` zieht
   [Standard-Kundenfeld] — ein anderes Konzept als das hier genutzte
   `Address.tax_id`.)

Zusätzlich am echten `Address`-Export sichtbar, aber (noch) nicht genutzt:
ein eigenes `tax_category`-Feld (Link "Tax Category") und `eori_no` — beide
könnten für eine spätere Erweiterung relevant sein (z. B. Zollbezug/EORI-
Nachweis neben der reinen USt-IdNr.-Prüfung), aktuell aber außerhalb des
Ticket-Scopes.

## Installation (auf einem echten Bench)

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
  außen vor ("erstmal nur Verkauf"). Bei Bedarf nachziehen — Annahme für
  später: `supplier_address` als Adressfeld (die Lieferanten-eigene
  Adresse, nicht die eigene Empfangsadresse `shipping_address`), noch nicht
  gegen die echten Purchase-Doctypes verifiziert.
- Eigenes Print Format für `VAT Validation Log` statt Standard-Layout, falls
  ein bestimmtes Finanzamt-taugliches Layout gewünscht ist.
- Wiederholungsprüfung: aktuell wird nur einmal je Submit geprüft — kein
  automatischer Re-Check bei Änderung der Lieferadresse nach Submit oder
  turnusmäßige Re-Validierung bestehender Kunden.
