# Copyright (c) 2026, Wellspring International School
# Script đối chiếu count sau migration (P4 dry-run)

import frappe
from frappe import _

from erp.utils.api_response import success_response, error_response


DEVICE_TYPES = ("laptop", "monitor", "printer", "projector", "phone", "tool")


@frappe.whitelist(allow_guest=False)
def reconcile_migration_counts(expected_counts=None):
	"""
	Đối chiếu số lượng bản ghi sau import.
	expected_counts: JSON {"laptop": 10, "monitor": 5, ..., "handover": 100, "inspection": 20, "activity": 30}
	"""
	try:
		import json

		data = expected_counts
		if isinstance(data, str):
			data = json.loads(data) if data else {}
		if not data and frappe.form_dict.get("expected_counts"):
			raw = frappe.form_dict.get("expected_counts")
			data = json.loads(raw) if isinstance(raw, str) else raw

		actual = {}
		for dt in DEVICE_TYPES:
			actual[dt] = frappe.db.count("ERP Inventory Device", {"device_type": dt})
		actual["handover"] = frappe.db.count("ERP Inventory Handover Log")
		actual["inspection"] = frappe.db.count("ERP Inventory Inspection")
		actual["activity"] = frappe.db.count("ERP Inventory Activity Log")

		diff = {}
		for key, exp in (data or {}).items():
			act = actual.get(key, 0)
			if cint_safe(exp) != act:
				diff[key] = {"expected": cint_safe(exp), "actual": act, "delta": act - cint_safe(exp)}

		return success_response(
			data={"actual": actual, "expected": data or {}, "diff": diff, "ok": len(diff) == 0},
			message=_("Đối chiếu migration"),
		)
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "erp_inventory.reconcile_migration_counts")
		return error_response(str(e))


def cint_safe(v):
	try:
		return int(v)
	except Exception:
		return 0
