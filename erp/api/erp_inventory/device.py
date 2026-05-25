# Copyright (c) 2026, Wellspring International School
# API thiết bị IT — parity với inventory-service Node.js

import json

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from erp.utils.api_response import (
	error_response,
	not_found_response,
	success_response,
	validation_error_response,
)
from erp.api.erp_inventory.inventory_helpers import (
	DEVICE_TYPES,
	POPULATED_KEY,
	VALID_STATUSES,
	apply_specs_to_doc,
	build_device_filters,
	device_doc_to_fe,
	normalize_device_type,
	paginated_devices_response,
	parse_request_data,
	resolve_room_link,
	resolve_user_link,
	sync_assigned_users,
	sync_current_holder_from_assigned,
	user_to_fe,
)


def _resolve_device_name(device_id: str, device_type: str = None):
	"""Map name / legacy_mongo_id / serial → ERP Inventory Device.name."""
	key = (device_id or "").strip()
	if not key:
		return None
	if frappe.db.exists("ERP Inventory Device", key):
		return key
	name = frappe.db.get_value("ERP Inventory Device", {"legacy_mongo_id": key}, "name")
	if name:
		return name
	if device_type:
		name = frappe.db.get_value(
			"ERP Inventory Device",
			{"serial": key, "device_type": device_type},
			"name",
		)
		if name:
			return name
	return frappe.db.get_value("ERP Inventory Device", {"serial": key}, "name")


def _get_device_doc(device_id: str, device_type: str = None):
	if not device_id:
		return None
	key = str(device_id).strip()
	# PK Frappe là duy nhất — tra theo name không cần lọc device_type
	if frappe.db.exists("ERP Inventory Device", key):
		return frappe.get_doc("ERP Inventory Device", key)

	name = _resolve_device_name(key, device_type)
	if not name:
		return None
	doc = frappe.get_doc("ERP Inventory Device", name)
	if device_type and doc.device_type != device_type:
		return None
	return doc


def _search_device_names(device_type: str, search: str) -> list:
	"""Tìm theo tên/serial/manufacturer/người được giao."""
	like = f"%{search}%"
	names = frappe.db.sql(
		"""
		SELECT DISTINCT d.name
		FROM `tabERP Inventory Device` d
		LEFT JOIN `tabERP Inventory Device Assigned User` au ON au.parent = d.name
		LEFT JOIN `tabUser` u ON u.name = au.user
		WHERE d.device_type = %(dt)s
		  AND (
			d.name_display LIKE %(like)s
			OR d.serial LIKE %(like)s
			OR d.manufacturer LIKE %(like)s
			OR u.full_name LIKE %(like)s
			OR u.email LIKE %(like)s
		  )
		ORDER BY d.modified DESC
		""",
		{"dt": device_type, "like": like},
		pluck="name",
	)
	return names or []


@frappe.whitelist(allow_guest=False)
def get_devices(device_type=None, page=1, limit=20, search=None, status=None, manufacturer=None, type=None, releaseYear=None):
	"""Danh sách thiết bị có phân trang — tương đương GET /api/inventory/{type}s."""
	try:
		dt = normalize_device_type(device_type)
		page = max(1, cint(page) or 1)
		limit = max(1, cint(limit) or 20)
		params = {
			"search": search,
			"status": status,
			"manufacturer": manufacturer,
			"type": type,
			"releaseYear": releaseYear,
		}
		filters, search_term = build_device_filters(dt, params)

		if search_term:
			name_list = _search_device_names(dt, search_term)
			total = len(name_list)
			start = (page - 1) * limit
			page_names = name_list[start : start + limit]
		else:
			total = frappe.db.count("ERP Inventory Device", filters=filters)
			page_names = frappe.get_all(
				"ERP Inventory Device",
				filters=filters,
				fields=["name"],
				order_by="modified desc",
				start=(page - 1) * limit,
				page_length=limit,
				pluck="name",
			)

		devices = []
		for name in page_names:
			doc = frappe.get_doc("ERP Inventory Device", name)
			devices.append(device_doc_to_fe(doc))

		return paginated_devices_response(dt, devices, page, limit, total)
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "erp_inventory.get_devices")
		return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def get_device_by_id(device_type=None, device_id=None):
	try:
		dt = normalize_device_type(device_type)
		device_id = device_id or frappe.form_dict.get("device_id")
		doc = _get_device_doc(device_id, dt)
		if not doc:
			return not_found_response(_("Không tìm thấy thiết bị"))
		return device_doc_to_fe(doc)
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "erp_inventory.get_device_by_id")
		return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def get_device_filters(device_type=None):
	try:
		dt = normalize_device_type(device_type)
		statuses = frappe.db.sql_list(
			"SELECT DISTINCT status FROM `tabERP Inventory Device` WHERE device_type=%s AND status IS NOT NULL AND status != ''",
			dt,
		)
		types = frappe.db.sql_list(
			"SELECT DISTINCT device_subtype FROM `tabERP Inventory Device` WHERE device_type=%s AND device_subtype IS NOT NULL AND device_subtype != ''",
			dt,
		)
		manufacturers = frappe.db.sql_list(
			"SELECT DISTINCT manufacturer FROM `tabERP Inventory Device` WHERE device_type=%s AND manufacturer IS NOT NULL AND manufacturer != ''",
			dt,
		)
		year_stats = frappe.db.sql(
			"""
			SELECT MIN(release_year) AS min_year, MAX(release_year) AS max_year
			FROM `tabERP Inventory Device`
			WHERE device_type=%s AND release_year IS NOT NULL
			""",
			dt,
			as_dict=True,
		)
		year_range = [2015, 2024]
		if year_stats and year_stats[0].min_year and year_stats[0].max_year:
			year_range = [year_stats[0].min_year, year_stats[0].max_year]

		departments = frappe.db.sql_list(
			"""
			SELECT DISTINCT u.department
			FROM `tabERP Inventory Device Assigned User` au
			INNER JOIN `tabERP Inventory Device` d ON d.name = au.parent
			INNER JOIN `tabUser` u ON u.name = au.user
			WHERE d.device_type = %s AND u.department IS NOT NULL AND u.department != ''
			""",
			dt,
		)
		return {
			"statuses": statuses,
			"types": types,
			"manufacturers": manufacturers,
			"departments": departments,
			"yearRange": year_range,
		}
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "erp_inventory.get_device_filters")
		return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def get_device_statistics(device_type=None):
	try:
		dt = normalize_device_type(device_type)
		total = frappe.db.count("ERP Inventory Device", {"device_type": dt})
		active = frappe.db.count("ERP Inventory Device", {"device_type": dt, "status": "Active"})
		standby = frappe.db.count("ERP Inventory Device", {"device_type": dt, "status": "Standby"})
		broken = frappe.db.count("ERP Inventory Device", {"device_type": dt, "status": "Broken"})
		pending = frappe.db.count("ERP Inventory Device", {"device_type": dt, "status": "PendingDocumentation"})
		return {
			"total": total,
			"active": active,
			"standby": standby,
			"broken": broken,
			"pendingDocumentation": pending,
		}
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "erp_inventory.get_device_statistics")
		return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def create_device(device_type=None):
	try:
		dt = normalize_device_type(device_type)
		data = parse_request_data()
		name = (data.get("name") or "").strip()
		serial = (data.get("serial") or "").strip()
		specs = data.get("specs") or {}
		if not name or not serial:
			return validation_error_response(_("Thiếu name hoặc serial"), {"name": ["required"], "serial": ["required"]})
		if not isinstance(specs, dict):
			return validation_error_response(_("Specs không hợp lệ"), {"specs": ["invalid"]})

		status = data.get("status") or "Standby"
		if status not in VALID_STATUSES:
			status = "Standby"
		assigned = data.get("assigned") or []
		if assigned and status == "Standby":
			status = "PendingDocumentation"

		room = data.get("room")
		room_id = resolve_room_link(room) if room else None

		doc = frappe.get_doc(
			{
				"doctype": "ERP Inventory Device",
				"device_type": dt,
				"device_subtype": data.get("type") or "",
				"name_display": name,
				"manufacturer": data.get("manufacturer") or "",
				"serial": serial,
				"release_year": data.get("releaseYear"),
				"room": room_id,
				"status": status,
				"broken_reason": data.get("brokenReason") or data.get("reason"),
			}
		)
		apply_specs_to_doc(doc, dt, specs)
		if assigned:
			user_ids = []
			for a in assigned:
				resolved = resolve_user_link(a) if isinstance(a, str) else resolve_user_link(a.get("email") if isinstance(a, dict) else None)
				if resolved:
					user_ids.append(resolved)
			sync_assigned_users(doc, user_ids)
			sync_current_holder_from_assigned(doc)
		doc.insert(ignore_permissions=False)
		frappe.db.commit()
		return device_doc_to_fe(doc)
	except frappe.ValidationError as e:
		return validation_error_response(str(e), {})
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error(frappe.get_traceback(), "erp_inventory.create_device")
		return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def update_device(device_type=None, device_id=None):
	try:
		dt = normalize_device_type(device_type)
		data = parse_request_data()
		device_id = device_id or data.get("device_id") or data.get("id")
		doc = _get_device_doc(device_id, dt)
		if not doc:
			return not_found_response(_("Không tìm thấy thiết bị"))

		if "name" in data:
			doc.name_display = data.get("name")
		if "manufacturer" in data:
			doc.manufacturer = data.get("manufacturer")
		if "serial" in data:
			doc.serial = data.get("serial")
		if "releaseYear" in data:
			doc.release_year = data.get("releaseYear")
		if "type" in data:
			doc.device_subtype = data.get("type")
		if "specs" in data:
			apply_specs_to_doc(doc, dt, data.get("specs"))
		if "room" in data:
			room_val = data.get("room")
			doc.room = resolve_room_link(room_val) if room_val else None
		if "assigned" in data:
			assigned = data.get("assigned") or []
			user_ids = []
			for a in assigned:
				resolved = resolve_user_link(a) if isinstance(a, str) else None
				if resolved:
					user_ids.append(resolved)
			sync_assigned_users(doc, user_ids)
			sync_current_holder_from_assigned(doc)
		if "status" in data and data.get("status") in VALID_STATUSES:
			doc.status = data.get("status")
		if data.get("status") == "Broken":
			doc.broken_reason = data.get("brokenReason") or data.get("reason") or doc.broken_reason
			doc.broken_description = data.get("brokenDescription") or doc.broken_description

		doc.save(ignore_permissions=False)
		frappe.db.commit()
		return device_doc_to_fe(doc)
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error(frappe.get_traceback(), "erp_inventory.update_device")
		return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def delete_device(device_type=None, device_id=None):
	try:
		dt = normalize_device_type(device_type)
		data = parse_request_data()
		device_id = device_id or data.get("device_id") or frappe.form_dict.get("device_id")
		doc = _get_device_doc(device_id, dt)
		if not doc:
			return not_found_response(_("Không tìm thấy thiết bị"))
		frappe.delete_doc("ERP Inventory Device", doc.name, ignore_permissions=False)
		frappe.db.commit()
		return {"message": f"{dt.capitalize()} deleted"}
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error(frappe.get_traceback(), "erp_inventory.delete_device")
		return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def assign_device(device_type=None, device_id=None):
	try:
		dt = normalize_device_type(device_type)
		data = parse_request_data()
		device_id = device_id or data.get("device_id")
		assigned_to = data.get("assignedTo") or data.get("assigned_to")
		reason = data.get("reason") or ""
		doc = _get_device_doc(device_id, dt)
		if not doc:
			return not_found_response(_("Không tìm thấy thiết bị"))

		new_user = resolve_user_link(assigned_to)
		if not new_user:
			return not_found_response(_("Không tìm thấy user mới"))

		# Đóng handover log đang mở
		open_logs = frappe.get_all(
			"ERP Inventory Handover Log",
			filters={"device": doc.name, "end_date": ["is", "not set"]},
			pluck="name",
		)
		for log_name in open_logs:
			log_doc = frappe.get_doc("ERP Inventory Handover Log", log_name)
			log_doc.end_date = now_datetime()
			log_doc.revoked_by = frappe.session.user
			log_doc.action = "revoked"
			log_doc.save(ignore_permissions=True)

		fullname = frappe.db.get_value("User", new_user, "full_name") or new_user
		job_title = frappe.db.get_value("User", new_user, "job_title") or frappe.db.get_value("User", new_user, "designation") or "Không xác định"

		frappe.get_doc(
			{
				"doctype": "ERP Inventory Handover Log",
				"device": doc.name,
				"action": "assigned",
				"user": new_user,
				"fullname_snapshot": fullname,
				"job_title_snapshot": job_title,
				"start_date": now_datetime(),
				"notes": reason,
				"assigned_by": frappe.session.user,
			}
		).insert(ignore_permissions=True)

		sync_assigned_users(doc, [new_user])
		doc.current_holder_user = new_user
		doc.current_holder_fullname = fullname
		doc.current_holder_jobtitle = job_title
		doc.current_holder_department = frappe.db.get_value("User", new_user, "department") or ""
		doc.status = "PendingDocumentation"
		doc.save(ignore_permissions=False)
		frappe.db.commit()
		return device_doc_to_fe(doc)
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error(frappe.get_traceback(), "erp_inventory.assign_device")
		return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def revoke_device(device_type=None, device_id=None):
	try:
		dt = normalize_device_type(device_type)
		data = parse_request_data()
		device_id = device_id or data.get("device_id")
		reasons = data.get("reasons") or []
		status = data.get("status") or "Standby"
		doc = _get_device_doc(device_id, dt)
		if not doc:
			return not_found_response(_("Không tìm thấy thiết bị"))

		open_logs = frappe.get_all(
			"ERP Inventory Handover Log",
			filters={"device": doc.name, "end_date": ["is", "not set"]},
			pluck="name",
		)
		for log_name in open_logs:
			log_doc = frappe.get_doc("ERP Inventory Handover Log", log_name)
			log_doc.end_date = now_datetime()
			log_doc.revoked_by = frappe.session.user
			log_doc.revoked_reasons = json.dumps(reasons if isinstance(reasons, list) else [reasons])
			log_doc.action = "revoked"
			log_doc.save(ignore_permissions=True)

		doc.assigned_users = []
		doc.current_holder_user = None
		doc.current_holder_fullname = None
		doc.current_holder_jobtitle = None
		doc.current_holder_department = None
		doc.status = status if status in VALID_STATUSES else "Standby"
		doc.save(ignore_permissions=False)
		frappe.db.commit()
		return {"message": "Thu hồi thành công", "laptop": device_doc_to_fe(doc), "device": device_doc_to_fe(doc)}
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error(frappe.get_traceback(), "erp_inventory.revoke_device")
		return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def update_device_status(device_type=None, device_id=None):
	try:
		dt = normalize_device_type(device_type)
		data = parse_request_data()
		device_id = device_id or data.get("device_id")
		status = data.get("status")
		if status not in VALID_STATUSES:
			return validation_error_response(_("Trạng thái không hợp lệ"), {"status": ["invalid"]})
		if status == "Broken" and not data.get("brokenReason"):
			return validation_error_response(_("Lý do báo hỏng là bắt buộc"), {"brokenReason": ["required"]})

		doc = _get_device_doc(device_id, dt)
		if not doc:
			return not_found_response(_("Không tìm thấy thiết bị"))
		doc.status = status
		if status == "Broken":
			doc.broken_reason = data.get("brokenReason") or "Không xác định"
			doc.broken_description = data.get("brokenDescription")
		doc.save(ignore_permissions=False)
		frappe.db.commit()
		return device_doc_to_fe(doc)
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error(frappe.get_traceback(), "erp_inventory.update_device_status")
		return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def update_device_specs(device_type=None, device_id=None):
	try:
		dt = normalize_device_type(device_type)
		data = parse_request_data()
		device_id = device_id or data.get("device_id")
		doc = _get_device_doc(device_id, dt)
		if not doc:
			return not_found_response(_("Không tìm thấy thiết bị"))
		specs = data.get("specs") or {}
		if "releaseYear" in data:
			doc.release_year = data.get("releaseYear")
		if "manufacturer" in data:
			doc.manufacturer = data.get("manufacturer")
		if "type" in data:
			doc.device_subtype = data.get("type")
		apply_specs_to_doc(doc, dt, specs)
		doc.save(ignore_permissions=False)
		frappe.db.commit()
		return device_doc_to_fe(doc)
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error(frappe.get_traceback(), "erp_inventory.update_device_status")
		return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def bulk_upload_devices(device_type=None):
	try:
		dt = normalize_device_type(device_type)
		data = parse_request_data()
		key = f"{dt}s"
		items = data.get(key) or data.get("devices") or []
		if not isinstance(items, list) or not items:
			return validation_error_response(_("Không có dữ liệu hợp lệ"), {key: ["empty"]})

		errors = []
		valid_count = 0
		for item in items:
			try:
				serial = (item.get("serial") or "").strip()
				name = (item.get("name") or "").strip()
				if not serial or not name:
					errors.append({"serial": serial or "?", "message": "Thiếu name hoặc serial"})
					continue
				if frappe.db.exists("ERP Inventory Device", {"serial": serial, "device_type": dt}):
					errors.append({"serial": serial, "name": name, "message": f"Serial {serial} đã tồn tại."})
					continue
				status = item.get("status") or "Standby"
				if status not in VALID_STATUSES:
					status = "Standby"
				doc = frappe.get_doc(
					{
						"doctype": "ERP Inventory Device",
						"device_type": dt,
						"device_subtype": item.get("type") or "",
						"name_display": name,
						"manufacturer": item.get("manufacturer") or "",
						"serial": serial,
						"release_year": item.get("releaseYear"),
						"status": status,
					}
				)
				apply_specs_to_doc(doc, dt, item.get("specs") or {})
				room = item.get("room")
				if room:
					doc.room = resolve_room_link(room)
				assigned = item.get("assigned") or []
				user_ids = []
				for a in assigned:
					if isinstance(a, str):
						u = resolve_user_link(a)
						if not u:
							# thử match fullname
							u = frappe.db.get_value("User", {"full_name": a.strip()}, "name")
						if u:
							user_ids.append(u)
				if user_ids:
					sync_assigned_users(doc, user_ids)
					sync_current_holder_from_assigned(doc)
					if doc.status == "Standby":
						doc.status = "PendingDocumentation"
				doc.insert(ignore_permissions=True)
				valid_count += 1
			except Exception as row_err:
				errors.append({"serial": item.get("serial", "?"), "message": str(row_err)})

		frappe.db.commit()
		added_key = f"added{dt.capitalize()}s"
		return {
			"message": "Thêm mới hàng loạt thành công!",
			added_key: valid_count,
			"addedLaptops": valid_count if dt == "laptop" else None,
			"errors": errors,
		}
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error(frappe.get_traceback(), "erp_inventory.bulk_upload_devices")
		return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def get_devices_in_room(room_id=None, skip=0, limit=100):
	"""Thiết bị trong phòng — thay roomController.getDevicesInRoom."""
	try:
		data = parse_request_data()
		room_id = room_id or data.get("roomId") or data.get("room_id")
		room_name = resolve_room_link(room_id) or room_id
		if not room_name or not frappe.db.exists("ERP Administrative Room", room_name):
			return {"devices": [], "total": 0}

		skip = cint(skip)
		limit = cint(limit) or 100
		names = frappe.get_all(
			"ERP Inventory Device",
			filters={"room": room_name},
			fields=["name"],
			order_by="modified desc",
			start=skip,
			page_length=limit,
			pluck="name",
		)
		total = frappe.db.count("ERP Inventory Device", {"room": room_name})
		devices = []
		for name in names:
			doc = frappe.get_doc("ERP Inventory Device", name)
			devices.append(device_doc_to_fe(doc, include_history=False))
		return {"devices": devices, "total": total, "roomId": room_name}
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "erp_inventory.get_devices_in_room")
		return error_response(str(e))
