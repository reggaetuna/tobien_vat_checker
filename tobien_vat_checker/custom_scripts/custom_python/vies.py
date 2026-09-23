"""Thin client for the VIES VAT-number validation REST API.

Endpoint and field names verified against the EU Commission's published
VIES REST API (successor to the old SOAP `checkVatService`) as of 2026-09.
See https://ec.europa.eu/taxation_customs/vies/ for the interactive form
this mirrors.
"""

import frappe
import requests

VIES_REST_URL = "https://ec.europa.eu/taxation_customs/vies/rest-api/check-vat-number"

# Country codes VIES accepts, keyed by the exact Frappe "Country" doctype
# name used in this instance's Address records. This IS the EU/Territory
# filter the ticket asks for - confirmed 2026-09-23 via the real site's
# Address "Customize Form" export that Address has no Territory field at
# all (only country, tax_category, eori_no, incoterm), so country-name
# matching is the correct mechanism here, not a fallback.
# Northern Ireland (XI) can't be distinguished from "United Kingdom" via the
# standard Frappe country list, so it's intentionally left out here - add it
# if this instance tracks NI addresses separately.
EU_COUNTRY_CODE_BY_NAME = {
	"Austria": "AT",
	"Belgium": "BE",
	"Bulgaria": "BG",
	"Croatia": "HR",
	"Cyprus": "CY",
	"Czech Republic": "CZ",
	"Czechia": "CZ",
	"Denmark": "DK",
	"Estonia": "EE",
	"Finland": "FI",
	"France": "FR",
	"Germany": "DE",
	"Greece": "EL",
	"Hungary": "HU",
	"Ireland": "IE",
	"Italy": "IT",
	"Latvia": "LV",
	"Lithuania": "LT",
	"Luxembourg": "LU",
	"Malta": "MT",
	"Netherlands": "NL",
	"Poland": "PL",
	"Portugal": "PT",
	"Romania": "RO",
	"Slovakia": "SK",
	"Slovenia": "SI",
	"Spain": "ES",
	"Sweden": "SE",
}


class VIESError(Exception):
	"""Raised when the VIES service itself could not be reached / errored.

	Distinct from a normal "not valid" result, which is a successful call
	that simply reports valid=False.
	"""


def is_eu_country(country_name):
	return (country_name or "") in EU_COUNTRY_CODE_BY_NAME


def eu_country_code(country_name):
	return EU_COUNTRY_CODE_BY_NAME.get(country_name)


def check_vat_number(country_code, vat_number, requester_country_code=None, requester_vat_number=None, timeout=15):
	"""Call the VIES REST API.

	Returns the parsed JSON response dict on a completed call (which may
	still report valid=False for a genuinely invalid VAT ID). Raises
	VIESError if the service could not be reached or returned a service-level
	error (e.g. MS_MAX_CONCURRENT_REQ, MS_UNAVAILABLE, INVALID_INPUT).
	"""
	payload = {
		"countryCode": country_code,
		"vatNumber": vat_number,
	}
	if requester_country_code and requester_vat_number:
		payload["requesterMemberStateCode"] = requester_country_code
		payload["requesterNumber"] = requester_vat_number

	try:
		response = requests.post(VIES_REST_URL, json=payload, timeout=timeout)
	except requests.RequestException as e:
		frappe.log_error(title="VIES request failed", message=str(e))
		raise VIESError(frappe._("VIES-Dienst nicht erreichbar: {0}").format(e))

	if response.status_code != 200:
		frappe.log_error(
			title="VIES non-200 response",
			message=f"status={response.status_code} body={response.text[:2000]}",
		)
		raise VIESError(
			frappe._("VIES antwortete mit Fehler ({0}): {1}").format(response.status_code, response.text[:300])
		)

	data = response.json()

	# The REST API reports service-level problems (bad input, member state
	# database down, rate limiting) inside a 200 response via an
	# "errorWrappers"/"actionSucceed" style payload rather than an HTTP
	# error in some deployments; be defensive about both shapes.
	if data.get("actionSucceed") is False or data.get("errorWrappers"):
		errors = data.get("errorWrappers") or [{"error": data.get("error", "unknown")}]
		message = "; ".join(str(e.get("error", e)) for e in errors)
		raise VIESError(frappe._("VIES konnte die Anfrage nicht verarbeiten: {0}").format(message))

	return data
