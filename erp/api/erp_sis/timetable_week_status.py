"""
API trạng thái tiết học trên lưới TKB tuần — gom điểm danh + sổ đầu bài trong 1 request.
"""
import hashlib
import json
import time

import frappe

from erp.utils.api_response import success_response, error_response
from erp.api.erp_sis.attendance import (
	_batch_attendance_has_for_cell_items,
	_cell_attendance_lookup_key,
)
from erp.api.erp_sis.class_log import _batch_lesson_log_status_for_items
from erp.api.erp_sis.utils.cache_utils import lesson_status_version_signature


def _get_json_body():
	try:
		if hasattr(frappe, "request") and getattr(frappe.request, "data", None):
			return json.loads(frappe.request.data.decode("utf-8"))
	except Exception:
		return {}
	return {}


def _derive_cell_status(has_attendance, is_complete):
	"""Suy ra todo | att | done — khớp deriveLessonPeriodStatus trên FE."""
	if not has_attendance:
		return "todo"
	if is_complete:
		return "done"
	return "att"


def _batch_week_lesson_status_for_items(items):
	"""Gom trạng thái ô TKB từ danh sách items."""
	att_map = _batch_attendance_has_for_cell_items(items)
	log_map = _batch_lesson_log_status_for_items(items)

	result = {}
	seen = set()
	for raw in items or []:
		class_id = raw.get("class_id")
		date = raw.get("date")
		period = raw.get("period")
		if not class_id or not date or not period:
			continue
		cell_key = _cell_attendance_lookup_key(date, period, class_id)
		if cell_key in seen:
			continue
		seen.add(cell_key)

		has_attendance = att_map.get(cell_key, {}).get("has_attendance", False)
		is_complete = log_map.get(cell_key, {}).get("is_complete", False)
		result[cell_key] = _derive_cell_status(has_attendance, is_complete)

	return result


@frappe.whitelist(allow_guest=False, methods=["POST"])
def batch_get_week_lesson_status():
	"""
	Trạng thái pill trên ô TKB tuần — 1 request thay cho attendance + class_log batch.

	POST body:
	{
		"items": [
			{"class_id": "CLASS-001", "date": "2025-10-10", "period": "Tiết 1"},
			...
		]
	}

	Returns:
	{
		"2025-10-10|Tiết 1|CLASS-001": "todo" | "att" | "done",
		...
	}
	"""
	try:
		body = _get_json_body() or {}
		items = body.get("items") or []

		if not items or not isinstance(items, list):
			return error_response(message="items must be a non-empty array", code="INVALID_ITEMS")

		items_hash = hashlib.md5(
			json.dumps(sorted(
				[
					f"{i.get('class_id')}|{i.get('date')}|{i.get('period')}"
					for i in items
					if i.get("class_id") and i.get("date") and i.get("period")
				]
			)).encode()
		).hexdigest()[:12]
		# Version hoá theo lớp: lưu điểm danh/sổ đầu bài của lớp nào sẽ bump version lớp đó
		# → chữ ký đổi → key này miss và tính lại (thay cho việc xoá bằng scan_iter).
		version_sig = lesson_status_version_signature(items)
		cache_key = f"week_lesson_status:{items_hash}:{version_sig}"

		try:
			cached_data = frappe.cache().get_value(cache_key)
			if cached_data is not None:
				return success_response(data=cached_data, message="Week lesson status (cached)")
		except Exception as cache_error:
			frappe.logger().warning(f"Cache read failed: {cache_error}")

		start = time.time()
		result = _batch_week_lesson_status_for_items(items)
		elapsed = (time.time() - start) * 1000
		frappe.logger().info(f"batch_get_week_lesson_status: {len(result)} cells in {elapsed:.0f}ms")

		try:
			frappe.cache().set_value(cache_key, result, expires_in_sec=300)
		except Exception as cache_error:
			frappe.logger().warning(f"Cache write failed: {cache_error}")

		return success_response(data=result, message="Week lesson status fetched successfully")
	except Exception as e:
		frappe.log_error(f"batch_get_week_lesson_status error: {str(e)}")
		return error_response(
			message=f"Failed to fetch week lesson status: {str(e)}",
			code="WEEK_LESSON_STATUS_ERROR",
		)
