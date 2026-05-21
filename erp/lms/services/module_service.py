"""CRUD module, module item, reorder — Module Builder."""

import json

import frappe

from erp.lms.utils.permissions import require_lms_staff

# Map item_type → DocType content_ref
ITEM_CONTENT_DOCTYPE = {
	"page": "LMS Page",
	"video": "LMS Video Asset",
	"assignment": "LMS Assignment",
	"quiz": "LMS Quiz",
	"file": "LMS File",
	"discussion": "LMS Discussion",
}

# Loại không cần content_ref và không chặn sequential
NON_BLOCKING_ITEM_TYPES = frozenset({"subheader", "text"})


def _next_position(doctype: str, filters: dict) -> int:
	"""Vị trí kế tiếp trong module/course."""
	conditions = " AND ".join(f"`{k}` = %s" for k in filters)
	values = list(filters.values())
	row = frappe.db.sql(
		f"SELECT COALESCE(MAX(position), -1) FROM `tab{doctype}` WHERE {conditions}",
		values,
	)[0][0]
	return int(row) + 1


def _normalize_item_payload(data: dict) -> dict:
	"""Chuẩn hóa payload create/update module item."""
	payload = dict(data)
	payload.pop("cmd", None)

	# Alias content_ref → content_ref_name
	if payload.get("content_ref") and not payload.get("content_ref_name"):
		payload["content_ref_name"] = payload.pop("content_ref")
	elif "content_ref" in payload:
		payload.pop("content_ref")

	item_type = payload.get("item_type")
	if item_type in ITEM_CONTENT_DOCTYPE and payload.get("content_ref_name"):
		payload["content_ref_doctype"] = ITEM_CONTENT_DOCTYPE[item_type]

	if payload.get("module") and payload.get("position") is None:
		payload["position"] = _next_position("LMS Module Item", {"module": payload["module"]})

	return payload


def create_module(data: dict) -> dict:
	require_lms_staff()
	course = data.get("course") or data.get("course_id")
	if not course:
		frappe.throw("course hoặc course_id bắt buộc")
	payload = {k: v for k, v in data.items() if k not in ("course_id", "cmd")}
	payload["course"] = course
	if payload.get("position") is None:
		payload["position"] = _next_position("LMS Module", {"course": course})
	doc = frappe.get_doc({"doctype": "LMS Module", **payload})
	doc.insert()
	return doc.as_dict()


def update_module(module_id: str, data: dict) -> dict:
	require_lms_staff()
	doc = frappe.get_doc("LMS Module", module_id)
	payload = {
		k: v
		for k, v in data.items()
		if k not in ("module_id", "name", "cmd", "course", "course_id")
	}
	doc.update(payload)
	doc.save()
	return doc.as_dict()


def delete_module(module_id: str) -> dict:
	require_lms_staff()
	item_names = frappe.get_all("LMS Module Item", filters={"module": module_id}, pluck="name")
	for item_id in item_names:
		_delete_item_progress(item_id)
		frappe.delete_doc("LMS Module Item", item_id, ignore_permissions=True)
	frappe.delete_doc("LMS Module", module_id, ignore_permissions=True)
	return {"deleted": module_id, "items_deleted": len(item_names)}


def create_module_item(data: dict) -> dict:
	require_lms_staff()
	payload = _normalize_item_payload(data)
	doc = frappe.get_doc({"doctype": "LMS Module Item", **payload})
	doc.insert()
	return doc.as_dict()


def update_module_item(item_id: str, data: dict) -> dict:
	require_lms_staff()
	payload = _normalize_item_payload({**data, "name": item_id})
	doc = frappe.get_doc("LMS Module Item", item_id)
	update_fields = {
		k: v
		for k, v in payload.items()
		if k not in ("name", "item_id", "cmd")
	}
	doc.update(update_fields)
	doc.save()
	return doc.as_dict()


def delete_module_item(item_id: str) -> dict:
	require_lms_staff()
	_delete_item_progress(item_id)
	frappe.delete_doc("LMS Module Item", item_id, ignore_permissions=True)
	return {"deleted": item_id}


def move_module_item(item_id: str, target_module: str, position: int | None = None) -> dict:
	"""Di chuyển item sang module khác (drag cross-module)."""
	require_lms_staff()
	if not frappe.db.exists("LMS Module", target_module):
		frappe.throw("Module đích không tồn tại")
	doc = frappe.get_doc("LMS Module Item", item_id)
	source_course = frappe.db.get_value("LMS Module", doc.module, "course")
	target_course = frappe.db.get_value("LMS Module", target_module, "course")
	if source_course != target_course:
		frappe.throw("Không thể di chuyển item sang module khác course")

	doc.module = target_module
	if position is None:
		doc.position = _next_position("LMS Module Item", {"module": target_module})
	else:
		doc.position = position
	doc.save()
	return doc.as_dict()


def reorder_modules(course: str, order: list) -> list:
	require_lms_staff()
	if isinstance(order, str):
		order = json.loads(order)
	if not course or not order:
		frappe.throw("course và order bắt buộc")

	for item in order:
		mod_id = item.get("name") or item.get("module")
		position = item.get("position")
		if mod_id is None or position is None:
			continue
		frappe.db.set_value("LMS Module", mod_id, "position", position)

	return frappe.get_all(
		"LMS Module",
		filters={"course": course},
		fields=["name", "title", "position", "unlock_at", "require_sequential_progress"],
		order_by="position asc",
	)


def reorder_module_items(module: str, order: list) -> list:
	require_lms_staff()
	if isinstance(order, str):
		order = json.loads(order)
	if not module or not order:
		frappe.throw("module và order bắt buộc")

	for item in order:
		item_id = item.get("name") or item.get("item_id")
		position = item.get("position")
		if item_id is None or position is None:
			continue
		frappe.db.set_value("LMS Module Item", item_id, "position", position)

	return frappe.get_all(
		"LMS Module Item",
		filters={"module": module},
		fields=[
			"name", "title", "position", "item_type", "published",
			"video_asset", "external_url", "content_ref_name",
		],
		order_by="position asc",
	)


def _delete_item_progress(item_id: str):
	"""Xóa progress liên quan khi xóa module item."""
	frappe.db.delete("LMS Content Progress", {"module_item": item_id})
