"""Adds "VAT Validation Log" to the Connections tab of Sales Order and
Customer (hooks.py override_doctype_dashboards).

The log links back via Dynamic Links (reference_name / party), so the
dashboard needs a non_standard_fieldname instead of the doctype's default
link fieldname. The log is placed into the existing group that contains
ANCHOR_ITEM rather than matched by group label, since labels are
translated."""

LOG_DOCTYPE = "VAT Validation Log"


def _add_log(data, fieldname, anchor_item):
	data.setdefault("non_standard_fieldnames", {})[LOG_DOCTYPE] = fieldname
	transactions = data.setdefault("transactions", [])

	for group in transactions:
		items = group.get("items") or []
		if LOG_DOCTYPE in items:
			return data
		if anchor_item in items:
			items.append(LOG_DOCTYPE)
			return data

	transactions.append({"label": "USt-IdNr.", "items": [LOG_DOCTYPE]})
	return data


def sales_order(data):
	# "Reference" group (Quotation, Auto Repeat, ...)
	return _add_log(data, "reference_name", "Auto Repeat")


def customer(data):
	# "Pre Sales" group (Opportunity, Quotation)
	return _add_log(data, "party", "Quotation")
