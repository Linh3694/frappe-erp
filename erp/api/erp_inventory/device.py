# Copyright (c) 2026, Wellspring International School
# API thiết bị IT — parity với inventory-service Node.js

import json

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from erp.utils.search import build_search_condition

from erp.utils.api_response import (
	error_response,
	not_found_response,
	single_item_response,
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
	device_signature,
	get_user_job_title,
	normalize_device_type,
	paginated_devices_response,
	parse_request_data,
	read_api_param,
	normalize_api_param,
	resolve_room_link,
	resolve_user_link,
	sync_assigned_users,
	sync_current_holder_from_assigned,
	user_to_fe,
)
from erp.api.erp_inventory.inventory_excel_schema import STATUS_LABEL_TO_CODE


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
	device_id = normalize_api_param(device_id)
	if not device_id:
		return None
	# PK Frappe là duy nhất — tra theo name không cần lọc device_type
	if frappe.db.exists("ERP Inventory Device", device_id):
		return frappe.get_doc("ERP Inventory Device", device_id)

	name = _resolve_device_name(device_id, device_type)
	if not name:
		return None
	doc = frappe.get_doc("ERP Inventory Device", name)
	if device_type and doc.device_type != device_type:
		return None
	return doc


def _read_device_request_params(device_type=None, device_id=None, data=None):
	"""Đọc device_type / device_id từ kwargs, query string hoặc JSON body."""
	if data is None:
		data = parse_request_data()
	dt_raw = read_api_param("device_type", "deviceType", fallback=device_type)
	if not dt_raw and data:
		dt_raw = normalize_api_param(data.get("device_type") or data.get("deviceType"))
	dt = normalize_device_type(dt_raw)

	id_raw = read_api_param("device_id", "deviceId", "id", fallback=device_id)
	if not id_raw and data:
		id_raw = normalize_api_param(data.get("device_id") or data.get("deviceId") or data.get("id"))
	return dt, id_raw, data


def _search_device_names(device_type: str, search: str) -> list:
	"""Tìm theo tên/serial/manufacturer/người được giao."""
	frag, fparams = build_search_condition(
		["d.name_display", "d.serial", "d.manufacturer", "u.full_name", "u.email"],
		search,
	)
	if not frag:
		return []
	names = frappe.db.sql(
		f"""
		SELECT DISTINCT d.name
		FROM `tabERP Inventory Device` d
		LEFT JOIN `tabERP Inventory Device Assigned User` au ON au.parent = d.name
		LEFT JOIN `tabUser` u ON u.name = au.user
		WHERE d.device_type = %s
		  AND {frag}
		ORDER BY d.modified DESC
		""",
		[device_type, *fparams],
		pluck="name",
	)
	return names or []


def _filter_names_by_assigned(device_type: str, value: str) -> list:
	"""Lọc thiết bị theo tên người được giao (fullname snapshot hoặc User.full_name)."""
	frag, fparams = build_search_condition(["au.fullname_snapshot", "u.full_name"], value)
	if not frag:
		return []
	names = frappe.db.sql(
		f"""
		SELECT DISTINCT d.name
		FROM `tabERP Inventory Device` d
		INNER JOIN `tabERP Inventory Device Assigned User` au ON au.parent = d.name
		LEFT JOIN `tabUser` u ON u.name = au.user
		WHERE d.device_type = %s
		  AND {frag}
		""",
		[device_type, *fparams],
		pluck="name",
	)
	return list(set(names or []))


def _filter_names_by_room(device_type: str, value: str) -> list:
	"""Lọc thiết bị theo tên phòng (title_vn / short_title / physical_code)."""
	frag, fparams = build_search_condition(
		["r.title_vn", "r.short_title", "r.physical_code"],
		value,
	)
	if not frag:
		return []
	names = frappe.db.sql(
		f"""
		SELECT DISTINCT d.name
		FROM `tabERP Inventory Device` d
		INNER JOIN `tabERP Administrative Room` r ON r.name = d.room
		WHERE d.device_type = %s
		  AND {frag}
		""",
		[device_type, *fparams],
		pluck="name",
	)
	return list(set(names or []))


def _filter_names_by_phone_spec(device_type: str, imei1=None, imei2=None, phone_number=None) -> list:
	"""Lọc phone theo IMEI/số điện thoại trong bảng specs_phone."""
	if device_type != "phone":
		return None
	clauses = ["d.device_type = %(dt)s"]
	params = {"dt": device_type}
	if imei1:
		clauses.append("sp.imei1 LIKE %(imei1)s")
		params["imei1"] = f"%{imei1}%"
	if imei2:
		clauses.append("sp.imei2 LIKE %(imei2)s")
		params["imei2"] = f"%{imei2}%"
	if phone_number:
		clauses.append("sp.phone_number LIKE %(pn)s")
		params["pn"] = f"%{phone_number}%"
	if len(clauses) == 1:
		return None
	names = frappe.db.sql(
		f"""
		SELECT DISTINCT d.name
		FROM `tabERP Inventory Device` d
		INNER JOIN `tabERP Inventory Specs Phone` sp ON sp.parent = d.name
		WHERE {" AND ".join(clauses)}
		""",
		params,
		pluck="name",
	)
	return list(set(names or []))


@frappe.whitelist(allow_guest=False)
def get_devices(
	device_type=None,
	page=1,
	limit=20,
	search=None,
	status=None,
	manufacturer=None,
	type=None,
	releaseYear=None,
	assigned=None,
	room=None,
	imei1=None,
	imei2=None,
	phoneNumber=None,
):
	"""Danh sách thiết bị có phân trang — tương đương GET /api/inventory/{type}s.

	Hỗ trợ server-side filter để FE phân trang đúng tổng số bản ghi sau filter.

	LƯU Ý: `page` là tên reserved của Frappe (dùng cho desk routing) — kwarg có thể
	bị nuốt mất khi gọi qua HTTP. Phải đọc explicit từ form_dict/query args để chắc chắn.
	"""
	try:
		dt = normalize_device_type(device_type)
		# Đọc TẤT CẢ param từ form_dict TRƯỚC (chứa giá trị thực từ query string),
		# fallback về kwarg nếu form_dict không có. Một số tên (page, search, type, ...)
		# là reserved trong Frappe → kwarg có thể bị nuốt khi route qua HTTP →
		# bắt buộc phải lấy từ form_dict cho an toàn.
		def _read_from_form(key: str, default):
			val = None
			if frappe.form_dict:
				val = frappe.form_dict.get(key)
			if val is None and getattr(frappe, "request", None) and getattr(frappe.request, "args", None):
				val = frappe.request.args.get(key)
			return val if val is not None else default

		page_raw = _read_from_form("page", page)
		limit_raw = _read_from_form("limit", limit)
		page = max(1, cint(page_raw) or 1)
		limit = max(1, cint(limit_raw) or 20)

		# Đọc lại các filter từ form_dict — đề phòng Frappe nuốt tên kwarg
		search = _read_from_form("search", search)
		status = _read_from_form("status", status)
		manufacturer = _read_from_form("manufacturer", manufacturer)
		type = _read_from_form("type", type)
		releaseYear = _read_from_form("releaseYear", releaseYear)
		assigned = _read_from_form("assigned", assigned)
		room = _read_from_form("room", room)
		imei1 = _read_from_form("imei1", imei1)
		imei2 = _read_from_form("imei2", imei2)
		phoneNumber = _read_from_form("phoneNumber", phoneNumber)

		params = {
			"search": search,
			"status": status,
			"manufacturer": manufacturer,
			"type": type,
			"releaseYear": releaseYear,
		}
		filters, search_term = build_device_filters(dt, params)

		# Lọc thêm theo child-table (assigned/room/imei/phone) — giao tập kết quả
		extra_name_sets = []
		if assigned:
			extra_name_sets.append(set(_filter_names_by_assigned(dt, assigned)))
		if room:
			extra_name_sets.append(set(_filter_names_by_room(dt, room)))
		phone_names = _filter_names_by_phone_spec(dt, imei1=imei1, imei2=imei2, phone_number=phoneNumber)
		if phone_names is not None:
			extra_name_sets.append(set(phone_names))

		# Lấy danh sách name thoả mãn filter cơ bản (status/manufacturer/...) + search
		if search_term:
			base_names = _search_device_names(dt, search_term)
			# Áp dụng filter cơ bản trên kết quả search
			if base_names and len(filters) > 1:
				keep = set(
					frappe.get_all(
						"ERP Inventory Device",
						filters=filters + [["name", "in", base_names]],
						pluck="name",
						limit_page_length=0,
					)
				)
				base_names = [n for n in base_names if n in keep]
		else:
			base_names = frappe.get_all(
				"ERP Inventory Device",
				filters=filters,
				order_by="modified desc",
				pluck="name",
				limit_page_length=0,
			)

		# Giao với các extra filter (assigned/room/phone)
		if extra_name_sets:
			final_set = set(base_names) if extra_name_sets else None
			if final_set is None:
				final_set = set(base_names)
			for s in extra_name_sets:
				final_set &= s
			final_names = [n for n in base_names if n in final_set]
		else:
			final_names = base_names

		total = len(final_names)
		start = (page - 1) * limit
		page_names = final_names[start : start + limit]

		devices = []
		for name in page_names:
			doc = frappe.get_doc("ERP Inventory Device", name)
			devices.append(device_doc_to_fe(doc))

		return paginated_devices_response(dt, devices, page, limit, total)
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "erp_inventory.get_devices")
		return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def get_device_by_id(device_type=None, device_id=None):
	try:
		resolved_type = read_api_param("device_type", fallback=device_type)
		dt = normalize_device_type(resolved_type)
		resolved_id = read_api_param("device_id", "id", fallback=device_id)
		if not resolved_id:
			return validation_error_response(
				_("Thiếu device_id"),
				{"device_id": ["required"]},
			)
		doc = _get_device_doc(resolved_id, dt)
		if not doc:
			return not_found_response(_("Không tìm thấy thiết bị"))
		return single_item_response(device_doc_to_fe(doc))
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

		# Sparkline 30 ngày — 1 query GROUP BY thay vì 30 lần count
		today = frappe.utils.getdate()
		start_date = frappe.utils.add_days(today, -29)
		additions_rows = frappe.db.sql(
			"""
			SELECT DATE(creation) AS day, COUNT(*) AS cnt
			FROM `tabERP Inventory Device`
			WHERE device_type = %s AND DATE(creation) >= %s
			GROUP BY DATE(creation)
			ORDER BY day ASC
			""",
			(dt, start_date),
			as_dict=True,
		)
		count_by_day = {str(r.day): int(r.cnt) for r in additions_rows}
		additions_30d = []
		for i in range(29, -1, -1):
			d = frappe.utils.add_days(today, -i)
			key = str(d)
			additions_30d.append({"date": key, "value": count_by_day.get(key, 0)})

		# Tuổi thiết bị cũ nhất — ưu tiên release_year, fallback creation
		oldest_row = frappe.db.sql(
			"""
			SELECT MIN(release_year) AS yr, MIN(creation) AS first_at
			FROM `tabERP Inventory Device`
			WHERE device_type = %s
			""",
			dt,
			as_dict=True,
		)
		oldest_age_years = None
		if oldest_row and oldest_row[0]:
			yr = oldest_row[0].yr
			if yr:
				oldest_age_years = round(today.year - int(yr), 1)
			elif oldest_row[0].first_at:
				first = frappe.utils.getdate(oldest_row[0].first_at)
				oldest_age_years = round((today - first).days / 365.25, 1)

		return {
			"total": total,
			"active": active,
			"standby": standby,
			"broken": broken,
			"pendingDocumentation": pending,
			"additions_30d": additions_30d,
			"oldest_device_age_years": oldest_age_years,
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


@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def update_device(device_type=None, device_id=None):
	try:
		dt, device_id, data = _read_device_request_params(device_type, device_id)
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


@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def assign_device(device_type=None, device_id=None):
	try:
		dt, device_id, data = _read_device_request_params(device_type, device_id)
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
		job_title = get_user_job_title(new_user) or "Không xác định"

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


@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def revoke_device(device_type=None, device_id=None):
	try:
		dt, device_id, data = _read_device_request_params(device_type, device_id)
		reasons = data.get("reasons") or []
		# FE cũ có thể gửi reason (string) thay vì reasons (array)
		if not reasons and data.get("reason"):
			reasons = [data.get("reason")]
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


@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def update_device_status(device_type=None, device_id=None):
	try:
		dt, device_id, data = _read_device_request_params(device_type, device_id)
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
		warnings = []
		valid_count = 0
		updated_count = 0
		unchanged_count = 0
		for item in items:
			try:
				serial = (item.get("serial") or "").strip()
				name = (item.get("name") or "").strip()
				if not serial or not name:
					errors.append({"serial": serial or "?", "message": "Thiếu name hoặc serial"})
					continue
				# Trạng thái có thể là nhãn tiếng Việt ("Thiếu biên bản"...) → đổi về mã chuẩn
				status_raw = item.get("status") or ""
				status = STATUS_LABEL_TO_CODE.get(status_raw, status_raw) or "Standby"
				if status not in VALID_STATUSES:
					status = "Standby"
				# Nếu serial đã tồn tại → cập nhật thiết bị, ngược lại tạo mới
				existing_name = frappe.db.get_value(
					"ERP Inventory Device", {"serial": serial, "device_type": dt}, "name"
				)
				is_update = bool(existing_name)
				if is_update:
					doc = frappe.get_doc("ERP Inventory Device", existing_name)
				else:
					doc = frappe.get_doc(
						{
							"doctype": "ERP Inventory Device",
							"device_type": dt,
							"serial": serial,
						}
					)
				# Chụp chữ ký trước khi áp dữ liệu để phân biệt "cập nhật" với "không đổi"
				sig_before = device_signature(doc) if is_update else None

				doc.device_subtype = item.get("type") or ""
				doc.name_display = name
				doc.manufacturer = item.get("manufacturer") or ""
				doc.release_year = item.get("releaseYear")
				doc.status = status
				apply_specs_to_doc(doc, dt, item.get("specs") or {})
				room = (item.get("room") or "").strip()
				if room:
					resolved_room = resolve_room_link(room)
					if resolved_room:
						doc.room = resolved_room
					elif is_update:
						# Không tìm thấy phòng → giữ nguyên phòng cũ, báo cảnh báo
						warnings.append({"serial": serial, "message": f"Phòng '{room}' không tồn tại, giữ nguyên phòng cũ"})
					else:
						warnings.append({"serial": serial, "message": f"Phòng '{room}' không tồn tại, bỏ qua"})
				# Match người dùng theo email (cột "Người sử dụng" chỉ để hiển thị)
				email = (item.get("email") or item.get("assignedEmail") or "").strip()
				if email:
					holder_user = resolve_user_link(email)
					if holder_user:
						sync_assigned_users(doc, [holder_user])
						sync_current_holder_from_assigned(doc)
						if doc.status == "Standby":
							doc.status = "PendingDocumentation"
					else:
						warnings.append({"serial": serial, "message": f"Email '{email}' không khớp người dùng nào, bỏ qua"})
				if is_update:
					if device_signature(doc) == sig_before:
						unchanged_count += 1
					else:
						doc.save(ignore_permissions=True)
						updated_count += 1
				else:
					doc.insert(ignore_permissions=True)
					valid_count += 1
			except Exception as row_err:
				errors.append({"serial": item.get("serial", "?"), "message": str(row_err)})

		frappe.db.commit()
		added_key = f"added{dt.capitalize()}s"
		msg_parts = [f"Thêm mới {valid_count}", f"cập nhật {updated_count}", f"không đổi {unchanged_count}"]
		return {
			"message": ", ".join(msg_parts) + " thiết bị thành công!",
			added_key: valid_count,
			"addedLaptops": valid_count if dt == "laptop" else None,
			"updated": updated_count,
			"unchanged": unchanged_count,
			"errors": errors,
			"warnings": warnings,
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
