"""Core VAT/USt-IdNr. validation orchestration.

Checks the USt-IdNr./VAT ID stored on an Address against the EU
Commission's VIES service, and keeps a submittable audit record of every
check. Currently wired up for the sales side only (Sales Order, Sales
Invoice, Customer); Purchase Order/Purchase Invoice/Supplier can be added
by extending ADDRESS_FIELD_BY_DOCTYPE/PARTY_FIELD_BY_DOCTYPE below, the
hooks.py doc_events/doctype_js, and the fixtures/custom_field.json Custom
Fields - the orchestration functions here are already doctype-agnostic.

Flow:
  1. Resolve the address relevant to the document (ADDRESS_FIELD_BY_DOCTYPE
     below).
  2. Skip entirely if that address is not in the EU (filter on
     Address.country, see vies.py).
  3. Call VIES with the company's own VAT ID as requester, so VIES returns
     a requestIdentifier - the proof-of-check reference EU tax authorities
     recognise, together with requestDate.
  4. Persist everything (raw response included) in a submittable
     "VAT Validation Log", attach it as a PDF to itself, and link it back
     to the source document via a custom field.
  5. On on_submit of Sales Order / Sales Invoice, the submit goes through
     and the check runs in the background (start_vat_check ->
     run_vat_check); custom_vat_status shows "Pruefung laeuft" until the
     result is there. The Sales Order form shows the status as a coloured
     indicator next to the document status. A valid result from 'jetzt
     pruefen' on the draft is reused instead of asking VIES again.
  6. If VIES is busy (vies.VIESUnavailable), nothing is logged: the
     document gets custom_vat_status = VAT_STATUS_PENDING and
     retry_pending_checks (scheduler, every 2 minutes) keeps trying until
     VIES answers. An invalid result notifies the user, and
     send_invalid_vat_report mails all open invalid documents daily.

Note on the EU filter: Sales Order/Sales Invoice each also have their own
`territory` field, but EU membership is determined from `Address.country`
instead - country is a required field and a direct statement of
geographic fact, whereas Territory reflects internal sales-region
categorization and isn't guaranteed to line up with actual EU membership.
"""

import json

import frappe
from frappe import _
from frappe.desk.doctype.notification_log.notification_log import enqueue_create_notification
from frappe.utils import escape_html, formatdate, get_link_to_form, now_datetime
from frappe.utils.pdf import get_pdf
from frappe.utils.file_manager import save_file

from . import vies

# Purchase Order/Purchase Invoice intentionally left out - sales-only
# scope for now, see module docstring.
ADDRESS_FIELD_BY_DOCTYPE = {
	"Sales Order": "shipping_address_name",
	"Sales Invoice": "shipping_address_name",
}

PARTY_FIELD_BY_DOCTYPE = {
	"Sales Order": ("Customer", "customer"),
	"Sales Invoice": ("Customer", "customer"),
}

# Custom field on Address holding the USt-IdNr./VAT ID.
ADDRESS_VAT_FIELDNAME = "tax_id"

# Options of the custom_vat_status Select field on Sales Order/Invoice.
VAT_STATUS_CHECKING = "Pruefung laeuft"
VAT_STATUS_PENDING = "VIES ueberlastet - Pruefung laeuft"
VAT_STATUS_VALID = "Gueltig"
VAT_STATUS_INVALID = "Ungueltig"
# no result yet, retry_pending_checks keeps trying
PENDING_STATUSES = (VAT_STATUS_CHECKING, VAT_STATUS_PENDING)


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
	Raises vies.VIESUnavailable if VIES is busy/down - in that case nothing
	is logged, the caller decides whether to retry later.
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
		except vies.VIESUnavailable:
			raise
		except vies.VIESError as e:
			# VIES rejected the request itself (e.g. malformed number) -
			# logged as an invalid result, retrying won't change it
			log.valid = 0
			log.error_message = str(e)
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

	_persist(log)
	return log


def _persist(log):
	log.insert(ignore_permissions=True)
	log.submit()


def _compare(vies_value, our_value):
	if not vies_value or not our_value:
		return "Nicht geprueft"
	a = "".join(vies_value.split()).lower()
	b = "".join(our_value.split()).lower()
	return "Uebereinstimmend" if a == b else "Abweichend"


def auto_check_enabled():
	"""Master on/off switch, 'VAT Check Settings' (Single doctype).
	Only gates the automatic check after submit below - the manual
	'jetzt pruefen' buttons (check_now/check_address/check_customer_or_supplier)
	are explicit user actions and always work regardless of this setting.

	Defaults to enabled if the Single hasn't been saved yet at all. Don't use
	frappe.db.get_single_value here: for a Check field it casts a missing
	row to 0, which silently disabled the check on fresh installs. Loading
	the doc falls back to frappe.new_doc for an unsaved Single, which
	applies the field's JSON default ("1")."""
	return bool(frappe.get_cached_doc("VAT Check Settings").enabled)


def start_vat_check(doc, method=None):
	"""doc_events on_submit hook for Sales Order / Sales Invoice.

	Doesn't block the submit: the check runs afterwards in the background
	(run_vat_check), so the user can keep working. The result lands in
	custom_vat_status, invalid ones also in the daily
	send_invalid_vat_report."""
	if not auto_check_enabled():
		return
	address_name = doc.get(ADDRESS_FIELD_BY_DOCTYPE[doc.doctype])
	if not address_name:
		return
	if not vies.is_eu_country(frappe.db.get_value("Address", address_name, "country")):
		return
	if _reusable_valid_log(doc, address_name):
		return  # already checked via 'jetzt pruefen' before the submit
	_store_vat_status(doc, VAT_STATUS_CHECKING)
	frappe.enqueue(
		"tobien_vat_checker.custom_scripts.custom_python.validation.run_vat_check",
		doctype=doc.doctype,
		name=doc.name,
		enqueue_after_commit=True,
	)


def run_vat_check(doctype, name):
	"""Background job queued by start_vat_check."""
	doc = frappe.get_doc(doctype, name)
	if doc.docstatus == 2 or doc.get("custom_vat_status") not in PENDING_STATUSES:
		return  # cancelled meanwhile, or retry_pending_checks got there first
	_run_check(doc)


def _run_check(doc):
	"""Check one document and store the result. A busy VIES leaves it at
	VAT_STATUS_PENDING for retry_pending_checks."""
	try:
		log = _check_document(doc)
	except vies.VIESUnavailable:
		if doc.get("custom_vat_status") != VAT_STATUS_PENDING:
			_store_vat_status(doc, VAT_STATUS_PENDING)
		return

	if log is None:
		_store_vat_status(doc, None)  # address removed or no longer EU
		return
	_store_vat_status(doc, VAT_STATUS_VALID if log.valid else VAT_STATUS_INVALID, log.name)
	if not log.valid:
		_notify_invalid(doc, log)


def _reusable_valid_log(doc, address_name):
	"""The valid check already done for this draft (via 'jetzt pruefen'),
	so submit doesn't have to ask VIES again - as long as it was for the
	same address and the same VAT ID."""
	if doc.get("custom_vat_status") != VAT_STATUS_VALID or not doc.get("custom_vat_validation"):
		return None
	log = frappe.get_doc("VAT Validation Log", doc.custom_vat_validation)
	address = frappe.get_doc("Address", address_name)
	country_code, vat_number = _split_vat_id(address.get(ADDRESS_VAT_FIELDNAME), vies.eu_country_code(address.country))
	if log.valid and log.address == address_name and (log.country_code, log.vat_number) == (country_code, vat_number):
		return log
	return None


def _store_vat_status(doc, status, log_name=None):
	"""Write the status straight to the DB, without touching `modified`, so
	it doesn't cause a 'document has been modified' conflict in a form the
	user still has open (keep_vat_status covers that form's next save).
	An open Sales Order form updates its header indicator from the
	realtime event."""
	doc.custom_vat_status = status
	doc.custom_vat_validation = log_name
	frappe.db.set_value(
		doc.doctype,
		doc.name,
		{"custom_vat_status": status, "custom_vat_validation": log_name},
		update_modified=False,
	)
	frappe.publish_realtime(
		"vat_status_changed",
		{"doctype": doc.doctype, "name": doc.name, "status": status, "log": log_name},
		doctype=doc.doctype,
		docname=doc.name,
		after_commit=True,
	)


def keep_vat_status(doc, method=None):
	"""doc_events validate / before_update_after_submit hook for Sales
	Order / Sales Invoice.

	custom_vat_status/custom_vat_validation are written behind the form's
	back (_store_vat_status), so a form opened earlier still carries the
	old values - take them from the DB instead. A changed address on a
	draft invalidates the earlier result."""
	if doc.is_new():
		return
	before = doc.get_doc_before_save()
	if not before:
		return
	address_field = ADDRESS_FIELD_BY_DOCTYPE.get(doc.doctype)
	if before.docstatus == 0 and address_field and doc.get(address_field) != before.get(address_field):
		doc.custom_vat_status = None
		doc.custom_vat_validation = None
	else:
		doc.custom_vat_status = before.get("custom_vat_status")
		doc.custom_vat_validation = before.get("custom_vat_validation")


def _check_document(doc):
	"""validate_address_vat for the address/party of a Sales Order/Invoice.
	Returns None if there is no address or it's outside the EU."""
	address_name = doc.get(ADDRESS_FIELD_BY_DOCTYPE[doc.doctype])
	if not address_name:
		return None
	party_type, party_field = PARTY_FIELD_BY_DOCTYPE[doc.doctype]
	return validate_address_vat(address_name, party_type, doc.get(party_field), doc.doctype, doc.name)


def retry_pending_checks():
	"""Scheduler job (hooks.py, every 2 minutes): re-check every document
	left at VAT_STATUS_PENDING by a busy VIES, until VIES answers. Also
	picks up VAT_STATUS_CHECKING, in case run_vat_check never ran (e.g.
	background workers down)."""
	for doctype in ADDRESS_FIELD_BY_DOCTYPE:
		names = frappe.get_all(
			doctype,
			filters={"docstatus": ["<", 2], "custom_vat_status": ["in", PENDING_STATUSES]},
			pluck="name",
			order_by="modified asc",
		)
		for name in names:
			try:
				_run_check(frappe.get_doc(doctype, name))
			except Exception:
				frappe.db.rollback()
				frappe.log_error(title=f"VAT retry failed for {doctype} {name}")
				continue
			frappe.db.commit()  # nosemgrep - one document at a time


def _notify_invalid(doc, log):
	enqueue_create_notification(
		list({doc.owner, doc.modified_by}),
		{
			"type": "Alert",
			"document_type": doc.doctype,
			"document_name": doc.name,
			"subject": _("USt-IdNr. fuer {0} {1} ist laut VIES UNGUELTIG.").format(_(doc.doctype), doc.name),
			"from_user": "Administrator",
		},
	)


def send_invalid_vat_report():
	"""Scheduler job (hooks.py, daily 07:00): mail all open documents with
	an invalid VAT ID to the recipients in VAT Check Settings. Nothing is
	sent if there are none. Closed/completed Sales Orders are left out, a
	Sales Invoice stays in until it's cancelled or re-checked as valid."""
	recipients = [
		e.strip()
		for e in (frappe.get_cached_doc("VAT Check Settings").report_recipients or "").replace(",", "\n").splitlines()
		if e.strip()
	]
	if not recipients:
		return

	rows = []
	for doctype, date_field in (("Sales Order", "transaction_date"), ("Sales Invoice", "posting_date")):
		filters = {"docstatus": ["<", 2], "custom_vat_status": VAT_STATUS_INVALID}
		if doctype == "Sales Order":
			filters["status"] = ["not in", ["Completed", "Closed"]]
		for d in frappe.get_all(
			doctype,
			filters=filters,
			fields=["name", "customer_name", f"{date_field} as date", "status", "custom_vat_validation"],
			order_by=f"{date_field} asc",
		):
			log_link = get_link_to_form("VAT Validation Log", d.custom_vat_validation) if d.custom_vat_validation else ""
			rows.append(
				f"<tr><td>{_(doctype)}</td><td>{get_link_to_form(doctype, d.name)}</td>"
				f"<td>{escape_html(d.customer_name or '')}</td><td>{formatdate(d.date)}</td>"
				f"<td>{_(d.status)}</td><td>{_('Ungueltig')}</td><td>{log_link}</td></tr>"
			)
	if not rows:
		return

	header = "".join(
		f"<th style='text-align:left'>{h}</th>"
		for h in (_("Belegart"), _("Beleg"), _("Kunde"), _("Datum"), _("Beleg-Status"), _("VAT-Status"), _("Pruefprotokoll"))
	)
	frappe.sendmail(
		recipients=recipients,
		subject=_("VAT-Report: {0} Beleg(e) mit ungueltiger USt-IdNr.").format(len(rows)),
		message=(
			f"<p>{_('Folgende Belege haben laut VIES eine ungueltige USt-IdNr.:')}</p>"
			"<table border='1' cellpadding='4' style='border-collapse:collapse'>"
			f"<tr>{header}</tr>{''.join(rows)}</table>"
		),
	)


def _manual_check(*args):
	"""validate_address_vat for the Address/Customer buttons: a busy VIES is
	shown as a normal message dialog instead of a raw traceback."""
	try:
		return validate_address_vat(*args)
	except vies.VIESUnavailable as e:
		frappe.throw(
			_("{0}<br>Bitte in ein paar Minuten erneut versuchen.").format(e),
			title=_("VIES ueberlastet"),
		)


@frappe.whitelist()
def check_now(reference_doctype, reference_name):
	"""Manual 'jetzt pruefen' button target: on a draft before the submit,
	or on a submitted document to re-check after the customer's VAT ID was
	corrected on the address. If VIES is busy, the document is handed to
	retry_pending_checks."""
	if reference_doctype not in ADDRESS_FIELD_BY_DOCTYPE:
		frappe.throw(_("VAT-Pruefung ist fuer {0} nicht konfiguriert.").format(reference_doctype))
	doc = frappe.get_doc(reference_doctype, reference_name)
	if doc.docstatus == 2:
		frappe.throw(_("Stornierte Belege werden nicht geprueft."))
	address_field = ADDRESS_FIELD_BY_DOCTYPE[reference_doctype]
	if not doc.get(address_field):
		frappe.throw(_("Kein Wert in Feld '{0}' auf diesem Beleg.").format(address_field))

	try:
		log = _check_document(doc)
	except vies.VIESUnavailable:
		_store_vat_status(doc, VAT_STATUS_PENDING)
		return {
			"pending": True,
			"message": _("VIES ist ueberlastet - die Pruefung laeuft im Hintergrund weiter."),
		}

	if log is None:
		_store_vat_status(doc, None)
		return {"skipped": True, "message": _("Adresse liegt ausserhalb der EU - keine Pruefung noetig.")}
	_store_vat_status(doc, VAT_STATUS_VALID if log.valid else VAT_STATUS_INVALID, log.name)
	return {"skipped": False, "log": log.name, "valid": bool(log.valid)}


@frappe.whitelist()
def check_customer_or_supplier(party_type, party_name, address_name):
	"""Used by the 'USt-IdNr. pruefen' button on Customer/Supplier forms for
	initial validation at data entry time."""
	log = _manual_check(address_name, party_type, party_name)
	if log is None:
		return {"skipped": True, "message": _("Adresse liegt ausserhalb der EU - keine Pruefung noetig.")}
	return {"skipped": False, "log": log.name, "valid": bool(log.valid)}


@frappe.whitelist()
def check_address(address_name):
	"""'USt-IdNr. pruefen' button directly on the Address form - the more
	direct entry point than the Customer-level button, since Address.tax_id
	is literally what's being checked (a customer can have several EU
	addresses, each needing its own check). Resolves the linked Customer
	purely to fill in the VAT Validation Log's party fields."""
	link = frappe.get_all(
		"Dynamic Link",
		filters={"parenttype": "Address", "parent": address_name, "link_doctype": "Customer"},
		fields=["link_name"],
		limit=1,
	)
	if not link:
		frappe.throw(_("Diese Adresse ist mit keinem Customer verknuepft."))

	log = _manual_check(address_name, "Customer", link[0].link_name)
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
	proof file."""
	html = frappe.get_print(doc.doctype, doc.name, print_format=None, doc=doc)
	pdf_content = get_pdf(html)
	save_file(
		fname=f"{doc.name}.pdf",
		content=pdf_content,
		dt=doc.doctype,
		dn=doc.name,
		is_private=1,
	)
