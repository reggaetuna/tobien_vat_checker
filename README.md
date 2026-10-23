# Tobien VAT Checker

Frappe/ERPNext v15 custom app: validates EU customers' VAT IDs
automatically via the EU Commission's **VIES REST service** and keeps a
PDF-backed audit record recognized as proof by tax authorities.

## What the app does

- **When checks run:** automatically after `Submit` of Sales Order and
  Sales Invoice, in the background (`on_submit` → queued job), so the user
  can keep working — plus a manual "Check VAT ID now" button on the
  document (before submit, or to re-check a submitted document after the
  VAT ID was corrected on the address), directly on the
  **Address** (that's where `tax_id` lives — the most direct route,
  especially when a customer has several EU addresses), and additionally
  on **Customer** as a convenience entry point for initial data entry
  (shows a picker when there are multiple addresses, then runs the same
  address-level check internally).
- **Where checks run:** only when the relevant address is in the EU
  (filtered on `Address.country`, see `vies.EU_COUNTRY_CODE_BY_NAME`).
  Non-EU addresses are skipped entirely — no error, no log entry.
- **Which address:** the **shipping address** (`shipping_address_name`) of
  the Sales Order/Sales Invoice, since it reflects the actual flow of
  goods.
- **Check source:** the EU Commission's [VIES REST API](https://ec.europa.eu/taxation_customs/vies/rest-api/check-vat-number).
  The company's own VAT ID is sent as `requesterNumber` — VIES then
  returns a `requestIdentifier` (consultation number), which tax
  authorities recognize as proof of the check.
- **Audit record:** every check creates a submitted `VAT Validation Log`
  with timestamp, consultation number, the raw VIES response (JSON), and
  a name/address match — automatically attached to itself as a PDF
  (`on_submit` → standard print format → PDF attachment).
- **No submit block:** the document is always submitted. The result is
  stored in `custom_vat_status` (Pruefung laeuft / VIES ueberlastet -
  Pruefung laeuft / Gueltig / Ungueltig). The Sales Order shows it as a
  coloured indicator next to the document status (e.g. "To Deliver and
  Bill"), updated live when the background check finishes. If VIES is
  busy, a scheduler job retries every 2 minutes until there is a result.
  An invalid result sends a notification (bell) to the document's owner
  and last editor. The old override fields (`custom_vat_override` +
  reason) are hidden, existing values are kept.
- **Daily report:** every day at 07:00, all open Sales Orders (not
  Completed/Closed) and Sales Invoices (not cancelled) with an invalid VAT
  ID are mailed to the recipients set in "VAT Check Settings" — only if
  there are any.
- **Linked to the SO/SI:** a dedicated field `custom_vat_validation` (link
  to the log) is visible directly on the document.
- **Connections:** VAT Validation Logs appear in the Connections tab of
  Sales Order, Sales Invoice (both "Reference") and Customer ("Pre
  Sales"). The log list and form show the result in green (valid) / red
  (invalid).
- **On/off switch:** a dedicated settings page **"VAT Check Settings"**
  (Single doctype, reachable via the awesomebar search) with a checkbox
  "Automatic check after submit enabled" and the recipients of the daily
  report. The checkbox only disables the automatic check — the manual "Check
  VAT ID" buttons on Address/Customer/document keep working regardless.
  Default: enabled. Permitted roles: System Manager, Sales Manager.

## Data model notes

- **VAT ID field:** `tax_id` (custom field on Address).
- **Address field on Sales Order/Sales Invoice:** `shipping_address_name`.
- **EU filter:** based on `Address.country` (static country list in
  `vies.py`), not the `territory` field on Sales Order/Sales
  Invoice/Customer — Territory reflects internal sales-region
  categorization and isn't guaranteed to align with actual EU membership.
- **Own VAT ID:** read from `Company.tax_id`.
- **Northern Ireland (XI):** not handled separately, since Frappe's
  standard country list doesn't distinguish UK/NI — add dedicated handling
  if relevant.
- Also present on Address but not (yet) used: `tax_category` (link "Tax
  Category") and `eori_no` — could become relevant for a future extension
  (e.g. customs/EORI proof alongside the plain VAT ID check).

## Installation

```bash
bench get-app https://github.com/reggaetuna/tobien_vat_checker
bench --site <site> install-app tobien_vat_checker
bench --site <site> migrate
```

Always install with the full repo URL, never with the bare name
(`bench get-app tobien_vat_checker` without a URL would make bench look
the name up in the public Frappe app directory).

The custom fields (`custom_vat_status`, `custom_vat_validation`,
`custom_vat_override`, `custom_vat_override_reason` on SO/SI) ship as a fixture
(`fixtures/custom_field.json`) and are imported during `migrate`.
