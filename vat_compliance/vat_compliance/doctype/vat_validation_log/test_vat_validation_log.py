# Copyright (c) 2026, phamos.eu and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from vat_compliance.custom_scripts.custom_python import vies


class TestVATValidationLog(FrappeTestCase):
	def test_split_vat_id_with_prefix(self):
		from vat_compliance.custom_scripts.custom_python.validation import _split_vat_id

		self.assertEqual(_split_vat_id("DE123456789"), ("DE", "123456789"))
		self.assertEqual(_split_vat_id("de 123 456 789"), ("DE", "123456789"))

	def test_split_vat_id_without_prefix_uses_fallback(self):
		from vat_compliance.custom_scripts.custom_python.validation import _split_vat_id

		self.assertEqual(_split_vat_id("123456789", fallback_country_code="AT"), ("AT", "123456789"))

	def test_is_eu_country(self):
		self.assertTrue(vies.is_eu_country("Germany"))
		self.assertFalse(vies.is_eu_country("Switzerland"))
		self.assertFalse(vies.is_eu_country(None))
