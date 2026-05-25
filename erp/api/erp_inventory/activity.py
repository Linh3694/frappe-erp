# Copyright (c) 2026, Wellspring International School
# API activity log thiết bị IT

import frappe
from frappe import _
from frappe.utils import now_datetime

from erp.utils.api_response import error_response, not_found_response, validation_error_response
from erp.api.erp_inventory.inventory_helpers import parse_request_data


def activity_to_fe(doc):
	return {
		"_id": doc.name,
		"entityType": doc.entity_type,
		"entityId": doc.entity,
		"type": doc.type,
		"description": doc.description,
		"details": doc.details or "",
		"date": doc.date.isoformat() if doc.date else None,
		"updatedBy": doc.updated_by or "Hệ thống",
		"createdAt": doc.creation.isoformat() if doc.creation else None,
		"updatedAt": doc.modified.isoformat() if doc.modified else None,
	}


@frappe.whitelist(allow_guest=False)
def get_activities(entity_type=None, entity_id=None):
	try:
		entity_type = entity_type or frappe.form_dict.get("entity_type")
		entity_id = entity_id or frappe.form_dict.get("entity_id")
		filters = {}
		if entity_type:
			filters["entity_type"] = entity_type
		if entity_id:
			filters["entity"] = entity_id
		names = frappe.get_all(
			"ERP Inventory Activity Log",
			filters=filters,
			pluck="name",
			order_by="date desc",
		)
		return [activity_to_fe(frappe.get_doc("ERP Inventory Activity Log", n)) for n in names]
	except Exception as e:
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

		doc = frappe.get_doc(
			{
				"doctype": "ERP Inventory Activity Log",
				"entity_type": entity_type,
				"entity": entity_id,
				"type": act_type,
				"description": description,
				"details": (data.get("details") or "").strip(),
				"date": data.get("date") or now_datetime(),
				"updated_by": data.get("updatedBy") or frappe.session.user,
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
