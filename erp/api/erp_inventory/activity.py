# Copyright (c) 2026, Wellspring International School
# API activity log thiết bị IT

import frappe
from frappe import _
from datetime import datetime
from frappe.utils import now_datetime

from erp.utils.api_response import error_response, not_found_response, validation_error_response
from erp.api.erp_inventory.inventory_helpers import parse_request_data, read_api_param, normalize_device_type
from erp.api.erp_inventory.device import _resolve_device_name


def _read_activity_payload(data):
	"""Đọc entity/type từ body — hỗ trợ cả camelCase và snake_case."""
	entity_type = data.get("entityType") or data.get("entity_type")
	entity_id = data.get("entityId") or data.get("entity_id")
	act_type = data.get("type")
	return entity_type, entity_id, act_type


def _datetime_to_iso(val):
	"""Chuẩn hoá datetime — frappe.get_all trả str, Document trả datetime."""
	if not val:
		return None
	if isinstance(val, datetime):
		return val.isoformat()
	return str(val)


def activity_to_fe(doc):
	"""Map ERP Inventory Activity Log doc → shape FE (Mongo-compatible)."""
	updated_by_user = doc.get("updated_by")
	updated_by_label = "Hệ thống"
	if updated_by_user and frappe.db.exists("User", updated_by_user):
		updated_by_label = frappe.db.get_value("User", updated_by_user, "full_name") or updated_by_user

	return {
		"_id": doc.get("name"),
		"entityType": doc.get("entity_type"),
		"entityId": doc.get("entity"),
		"type": doc.get("type"),
		"description": doc.get("description"),
		"details": doc.get("details") or "",
		"date": _datetime_to_iso(doc.get("date")),
		"updatedBy": updated_by_label,
		"createdAt": _datetime_to_iso(doc.get("creation")),
		"updatedAt": _datetime_to_iso(doc.get("modified")),
	}


@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def get_activities(entity_type=None, entity_id=None):
	"""Lấy lịch sử hoạt động của 1 thiết bị cụ thể.

	BẮT BUỘC phải có entity_id để tránh leak activity của thiết bị khác.
	"""
	try:
		entity_type = read_api_param("entity_type", "entityType", fallback=entity_type)
		entity_id = read_api_param("entity_id", "entityId", fallback=entity_id)

		if not entity_id:
			return []

		resolved_entity = _resolve_device_name(entity_id, normalize_device_type(entity_type) or None)
		if not resolved_entity:
			return []

		# Chỉ lọc theo entity (Link Device) — entity_type là metadata, dễ lệch sau migrate
		rows = frappe.get_all(
			"ERP Inventory Activity Log",
			filters={"entity": resolved_entity},
			fields=[
				"name",
				"entity_type",
				"entity",
				"type",
				"description",
				"details",
				"date",
				"updated_by",
				"creation",
				"modified",
			],
			order_by="date desc",
			limit_page_length=0,
		)
		return [activity_to_fe(r) for r in rows]
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "erp_inventory.activity.get_activities")
		return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def add_activity():
	try:
		data = parse_request_data()
		entity_type, entity_id, act_type = _read_activity_payload(data)
		entity_type = normalize_device_type(entity_type)
		description = (data.get("description") or "").strip()
		if not entity_type or not entity_id:
			return validation_error_response(_("entityType và entityId là bắt buộc"), {})
		resolved_entity = _resolve_device_name(entity_id, entity_type)
		if not resolved_entity:
			return validation_error_response(_("Không tìm thấy thiết bị"), {"entityId": ["not_found"]})
		if act_type not in ("repair", "update"):
			return validation_error_response(_("type phải là repair hoặc update"), {})
		if not description:
			return validation_error_response(_("description là bắt buộc"), {})

		# updated_by là Link User — luôn dùng session user, không nhận full_name từ FE
		doc = frappe.get_doc(
			{
				"doctype": "ERP Inventory Activity Log",
				"entity_type": entity_type,
				"entity": resolved_entity,
				"type": act_type,
				"description": description,
				"details": (data.get("details") or "").strip(),
				"date": data.get("date") or now_datetime(),
				"updated_by": frappe.session.user,
			}
		)
		doc.insert(ignore_permissions=False)
		frappe.db.commit()
		return activity_to_fe(doc)
	except Exception as e:
		frappe.db.rollback()
		return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def update_activity(activity_id=None):
	try:
		data = parse_request_data()
		activity_id = activity_id or data.get("activity_id")
		if not frappe.db.exists("ERP Inventory Activity Log", activity_id):
			return not_found_response(_("Activity not found"))
		doc = frappe.get_doc("ERP Inventory Activity Log", activity_id)
		if "description" in data:
			doc.description = data.get("description")
		if "details" in data:
			doc.details = data.get("details")
		if "date" in data:
			doc.date = data.get("date")
		doc.save(ignore_permissions=False)
		frappe.db.commit()
		return activity_to_fe(doc)
	except Exception as e:
		frappe.db.rollback()
		return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def delete_activity(activity_id=None):
	try:
		activity_id = activity_id or frappe.form_dict.get("activity_id")
		if not frappe.db.exists("ERP Inventory Activity Log", activity_id):
			return not_found_response(_("Activity not found"))
		frappe.delete_doc("ERP Inventory Activity Log", activity_id, ignore_permissions=False)
		frappe.db.commit()
		return {"message": "Xóa hoạt động thành công"}
	except Exception as e:
		frappe.db.rollback()
		return error_response(str(e))
