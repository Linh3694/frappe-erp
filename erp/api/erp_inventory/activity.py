# Copyright (c) 2026, Wellspring International School
# API activity log thiết bị IT

import frappe
from frappe import _
from frappe.utils import now_datetime

from erp.utils.api_response import error_response, not_found_response, validation_error_response
from erp.api.erp_inventory.inventory_helpers import parse_request_data


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
		"date": doc.get("date").isoformat() if doc.get("date") else None,
		"updatedBy": updated_by_label,
		"createdAt": doc.get("creation").isoformat() if doc.get("creation") else None,
		"updatedAt": doc.get("modified").isoformat() if doc.get("modified") else None,
	}


@frappe.whitelist(allow_guest=False)
def get_activities(entity_type=None, entity_id=None):
	"""Lấy lịch sử hoạt động của 1 thiết bị cụ thể.

	BẮT BUỘC phải có entity_id để tránh leak activity của thiết bị khác.
	"""
	try:
		entity_type = (entity_type or frappe.form_dict.get("entity_type") or "").strip()
		entity_id = (entity_id or frappe.form_dict.get("entity_id") or "").strip()

		# Guard: nếu thiếu entity_id, trả về list rỗng thay vì leak toàn bộ activities
		if not entity_id:
			return []

		filters = {"entity": entity_id}
		if entity_type:
			filters["entity_type"] = entity_type

		# limit_page_length=0 → bỏ giới hạn mặc định 20 record của Frappe
		rows = frappe.get_all(
			"ERP Inventory Activity Log",
			filters=filters,
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


@frappe.whitelist(allow_guest=False)
def add_activity():
	try:
		data = parse_request_data()
		entity_type = data.get("entityType")
		entity_id = data.get("entityId")
		act_type = data.get("type")
		description = (data.get("description") or "").strip()
		if not entity_type or not entity_id:
			return validation_error_response(_("entityType và entityId là bắt buộc"), {})
		if act_type not in ("repair", "update"):
			return validation_error_response(_("type phải là repair hoặc update"), {})
		if not description:
			return validation_error_response(_("description là bắt buộc"), {})

		# updated_by là Link User — luôn dùng session user, không nhận full_name từ FE
		doc = frappe.get_doc(
			{
				"doctype": "ERP Inventory Activity Log",
				"entity_type": entity_type,
				"entity": entity_id,
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
