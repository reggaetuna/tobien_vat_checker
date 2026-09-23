"""Core VAT/USt-IdNr. validation orchestration.

Ticket reference: "VAT - UID pruefen" (Frederic Tobien).

Scope (2026-09-23, user decision): sales side only for now - Sales Order,
Sales Invoice, Customer. Purchase Order/Purchase Invoice/Supplier are
deliberately not wired up yet (their unverified `supplier_address`
assumption is moot until that's revisited) - adding them back later is
just re-adding entries to ADDRESS_FIELD_BY_DOCTYPE/PARTY_FIELD_BY_DOCTYPE,
the hooks.py doc_events/doctype_js, and the fixtures/custom_field.json
Custom Fields; the orchestration functions below are already
doctype-agnostic.

Flow:
  1. Resolve the address relevant to the document (see ADDRESS_FIELD_BY_DOCTYPE
     below - ASSUMPTION, verify against the real site, see README).
  2. Skip entirely if that address is not in the EU (ticket: filter on
     Territory = EU; implemented via Address.country - see vies.py and the
     "EU filter" note below for why Territory itself was decided against).
  3. Call VIES with our own company VAT ID as requester, so VIES returns a
     requestIdentifier - this is the actual proof-of-check reference EU tax
     authorities recognise, together with requestDate.
  4. Persist everything (raw response included) in a submittable
     "VAT Validation Log", attach it as a PDF to itself, and link it back to
     the source document via a custom field.
  5. On before_submit of Sales Order / Sales Invoice, block submission if
     the relevant EU customer's VAT ID did not validate - unless a
     permitted role has set a logged manual override (VIES outages happen;
     see vies.VIESError).

CONFIRMED against the real site's Address "Customize Form" export
(2026-09-23): Address has a custom Data field `tax_id` for the USt-IdNr.,
and has NO Territory field at all (only `country`, `tax_category`,
`eori_no`, `incoterm`) - so the EU filter in vies.py being based on
Address.country isn't a fallback, it's the only option and is correct as
implemented.

CONFIRMED against the real Sales Order AND Sales Invoice DocType exports
(2026-09-23): both have `shipping_address_name` (Link, Address) exactly as
assumed. Also worth noting from those exports: both already have their own
`tax_id` field, but it's `fetch_from: customer.tax_id` (a standard ERPNext
Customer-level field) - a different concept from the per-address
`Address.tax_id` this app checks. Using the address-level field is still
the right call here: a customer can have several EU addresses, each
needing its own VAT ID checked, which a single customer-level field can't
represent.

EU filter, decided (2026-09-23): both Sales Order and Sales Invoice have
their own `territory` field (Link to "Territory", part of Sales Order's
`search_fields`), which is arguably closer to the ticket's literal
"Territory = EU" wording than Address.country. Decided against using it:
Territory reflects the vendor's own sales-region categorization and isn't
guaranteed to line up with actual EU membership or be consistently
maintained, whereas Address.country is a required field and a direct
statement of geographic fact - staying with the country-based filter in
vies.py keeps EU-membership determination independent of how disciplined
Territory bookkeeping happens to be.

Purchase Order/Purchase Invoice support was scoped out for now (see above)
before their `supplier_address` assumption could be confirmed - revisit
when purchase-side is back in scope.
"""

import json

import frappe
from frappe import _
from frappe.utils import now_datetime
from frappe.utils.pdf import get_pdf
from frappe.utils.file_manager import save_file

from . import vies

OVERRIDE_ROLES = {"System Manager", "Sales Manager"}

# CONFIRMED against the real Sales Order/Sales Invoice DocType exports
# (2026-09-23). Purchase Order/Purchase Invoice intentionally left out -
# sales-only scope for now, see module docstring.
ADDRESS_FIELD_BY_DOCTYPE = {
	"Sales Order": "shipping_address_name",
	"Sales Invoice": "shipping_address_name",
}

PARTY_FIELD_BY_DOCTYPE = {
	"Sales Order": ("Customer", "customer"),
	"Sales Invoice": ("Customer", "customer"),
}

# CONFIRMED against the real Address Customize Form export (2026-09-23):
# custom Data field, fieldname "tax_id".
ADDRESS_VAT_FIELDNAME = "tax_id"


def _own_company_vat(company):
	if not company:
		return None, None
	tax_id = frappe.get_value("Company", company, "tax_id")
	if not tax_id:
		return None, None
	tax_id = tax_id.strip().upper().replace(" ", "")
	country_code = tax_id[:2] if tax_id[:2].isalpha() else None
	number = tax_id[2:] if country_code else tax_id
	return country_code, number


def _split_vat_id(raw_vat_id, fallback_country_code=None):
	raw = (raw_vat_id or "").strip().upper().replace(" ", "").replace("-", "")
	if raw[:2].isalpha():
		return raw[:2], raw[2:]
	# no country prefix on the stored value - fall back to the address's
	# own country, since VIES requires the prefix split out separately
	return fallback_country_code, raw


def validate_address_vat(address_name, party_type, party_name, reference_doctype=None, reference_name=None):
	"""Run a VIES check for one address and persist the result.

	Returns the inserted & submitted "VAT Validation Log" doc, or None if
	the address is outside the EU (nothing to check, not an error).
	Raises vies.VIESError if the EU-address VAT ID could not be validated
	because the service call itself failed (caller decides whether that
	blocks anything).
	"""
	address = frappe.get_doc("Address", address_name)

	if not vies.is_eu_country(address.country):
		return None

	raw_vat_id = address.get(ADDRESS_VAT_FIELDNAME)
	fallback_cc = vies.eu_country_code(address.country)
	country_code, vat_number = _split_vat_id(raw_vat_id, fallback_cc)

	company = None
	if reference_doctype and reference_name:
		company = frappe.get_cached_value(reference_doctype, reference_name, "company")
	company = company or frappe.defaults.get_user_default("Company")
	requester_cc, requester_number = _own_company_vat(company)

	log = frappe.new_doc("VAT Validation Log")
	log.reference_doctype = reference_doctype
	log.reference_name = reference_name
	log.party_type = party_type
	log.party = party_name
	log.address = address_name
	log.country_code = country_code
	log.vat_number = vat_number
	log.own_vat_number = f"{requester_cc}{requester_number}" if requester_cc else None
	log.request_date = now_datetime()

	if not raw_vat_id:
		log.valid = 0
		log.error_message = _("Keine USt-IdNr. auf der Adresse {0} hinterlegt.").format(address_name)
	else:
		try:
			result = vies.check_vat_number(country_code, vat_number, requester_cc, requester_number)
		except vies.VIESError as e:
			log.valid = 0
			log.error_message = str(e)
			log.raw_response = None
			log.insert(ignore_permissions=True)
			log.submit()
			raise
		else:
			log.valid = 1 if result.get("valid") else 0
			log.request_identifier = result.get("requestIdentifier") or None
			log.vies_name = result.get("name") or None
			log.vies_address = result.get("address") or None
			log.raw_response = json.dumps(result, indent=2, ensure_ascii=False)
			display_name_field = "customer_name" if party_type == "Customer" else "supplier_name"
			party_display_name = frappe.get_cached_value(party_type, party_name, display_name_field)
			log.name_match = _compare(log.vies_name, party_display_name)
			log.address_match = "Nicht geprueft"
			if not result.get("valid"):
				log.error_message = _("Die USt-IdNr. {0}{1} ist laut VIES nicht (mehr) gueltig.").format(
					country_code, vat_number
				)

	log.insert(ignore_permissions=True)
	log.submit()
	return log


def _compare(vies_value, our_value):
	if not vies_value or not our_value:
		return "Nicht geprueft"
	a = "".join(vies_value.split()).lower()
	b = "".join(our_value.split()).lower()
	return "Uebereinstimmend" if a == b else "Abweichend"


def enforce_vat_check(doc, method=None):
	"""doc_events before_submit hook for Sales Order / Sales Invoice /
	Purchase Order / Purchase Invoice.

	Blocks submission if the relevant EU party's VAT ID is missing/invalid,
	unless a permitted role has ticked the manual override with a reason.
	"""
	address_field = ADDRESS_FIELD_BY_DOCTYPE.get(doc.doctype)
	party_type, party_field = PARTY_FIELD_BY_DOCTYPE.get(doc.doctype, (None, None))
	if not address_field:
		return

	address_name = doc.get(address_field)
	if not address_name:
		# No delivery/supplier address set at all - nothing to check against,
		# leave to existing mandatory-field validation elsewhere.
		return

	party_name = doc.get(party_field)

	if doc.get("custom_vat_override") and doc.get("custom_vat_override_reason"):
		if frappe.session.user != "Administrator" and not (set(frappe.get_roles()) & OVERRIDE_ROLES):
			frappe.throw(_("Nur {0} duerfen die USt-IdNr.-Pruefung manuell uebersteuern.").format(
				", ".join(OVERRIDE_ROLES)
			))
		frappe.msgprint(
			_("USt-IdNr.-Pruefung manuell uebersteuert von {0}: {1}").format(
				frappe.session.user, doc.custom_vat_override_reason
			),
			alert=True,
		)
		return

	try:
		log = validate_address_vat(address_name, party_type, party_name, doc.doctype, doc.name)
	except vies.VIESError as e:
		frappe.throw(
			_("USt-IdNr.-Pruefung (VIES) fehlgeschlagen, Beleg kann nicht gebucht werden: {0}"
				"<br>Falls der Dienst nachweislich down ist, kann ein berechtigter Nutzer "
				"(Sales/Purchase Manager) die Pruefung im Feld 'VAT Override' mit Begruendung "
				"manuell uebersteuern.").format(e)
		)

	if log is None:
		return  # not an EU address, nothing to enforce

	doc.custom_vat_validation = log.name

	if not log.valid:
		frappe.throw(
			_("USt-IdNr. der Adresse {0} ist laut VIES ungueltig ({1}). Beleg kann nicht gebucht "
				"werden. Pruefdetails: {2}").format(address_name, log.get("vat_number"), log.name)
		)


@frappe.whitelist()
def check_now(reference_doctype, reference_name):
	"""Manual 'jetzt pruefen' button target, callable before submit so the
	user isn't surprised by a hard block at submit time."""
	doc = frappe.get_doc(reference_doctype, reference_name)
	address_field = ADDRESS_FIELD_BY_DOCTYPE.get(reference_doctype)
	party_type, party_field = PARTY_FIELD_BY_DOCTYPE.get(reference_doctype, (None, None))
	if not address_field:
		frappe.throw(_("VAT-Pruefung ist fuer {0} nicht konfiguriert.").format(reference_doctype))

	address_name = doc.get(address_field)
	if not address_name:
		frappe.throw(_("Kein Wert in Feld '{0}' auf diesem Beleg.").format(address_field))

	log = validate_address_vat(address_name, party_type, doc.get(party_field), reference_doctype, reference_name)
	if log is None:
		return {"skipped": True, "message": _("Adresse liegt ausserhalb der EU - keine Pruefung noetig.")}
	return {"skipped": False, "log": log.name, "valid": bool(log.valid)}


@frappe.whitelist()
def check_customer_or_supplier(party_type, party_name, address_name):
	"""Used by the 'USt-IdNr. pruefen' button on Customer/Supplier forms for
	initial validation at data entry time."""
	log = validate_address_vat(address_name, party_type, party_name)
	if log is None:
		return {"skipped": True, "message": _("Adresse liegt ausserhalb der EU - keine Pruefung noetig.")}
	return {"skipped": False, "log": log.name, "valid": bool(log.valid)}


@frappe.whitelist()
def get_party_addresses(party_type, party_name):
	"""Addresses linked to a Customer/Supplier, for the 'welche Adresse pruefen'
	picker on the Customer/Supplier form button."""
	rows = frappe.get_all(
		"Dynamic Link",
		filters={"link_doctype": party_type, "link_name": party_name, "parenttype": "Address"},
		fields=["parent"],
	)
	names = [r.parent for r in rows]
	if not names:
		return []
	return frappe.get_all(
		"Address",
		filters={"name": ["in", names]},
		fields=["name", "country", "address_line1", "city", ADDRESS_VAT_FIELDNAME],
	)


def attach_pdf_on_submit(doc, method=None):
	"""doc_events on_submit for VAT Validation Log - renders the log itself
	to PDF via the standard print format and attaches it as the auditable
	proof file (ticket: 'Bestaetigung ... (PDF etc.)')."""
	html = frappe.get_print(doc.doctype, doc.name, print_format=None, doc=doc)
	pdf_content = get_pdf(html)
	save_file(
		fname=f"{doc.name}.pdf",
		content=pdf_content,
		dt=doc.doctype,
		dn=doc.name,
		is_private=1,
	)
