# Copyright (c) 2026, Wellspring International School and contributors
# API cấu hình phòng khả dụng để đặt — doctype ERP Room Booking Config

import json

import frappe
from frappe import _
from frappe.utils import get_datetime, get_time, get_weekday

from erp.utils.api_response import (
    error_response,
    not_found_response,
    success_response,
    validation_error_response,
)

CONFIG_DOCTYPE = "ERP Room Booking Config"
AVAIL_CHILD = "ERP Room Booking Availability"

WEEKDAY_NAMES = [
	"Monday",
	"Tuesday",
	"Wednesday",
	"Thursday",
	"Friday",
	"Saturday",
	"Sunday",
]


def _active_school_year_id(explicit=None):
	"""Năm học đang bật — copy logic từ administrative_ticket để tránh circular import."""
	sy = (explicit or "").strip()
	if sy and frappe.db.exists("SIS School Year", sy):
		return sy
	return frappe.db.get_value(
		"SIS School Year",
		{"is_enable": 1},
		"name",
		order_by="start_date desc",
	)


def _parse_json_body():
	data = {}
	if frappe.request and frappe.request.data:
		try:
			raw = frappe.request.data
			if isinstance(raw, bytes):
				raw = raw.decode("utf-8")
			if raw:
				data = json.loads(raw)
		except (json.JSONDecodeError, TypeError, ValueError):
			data = dict(frappe.local.form_dict or {})
	else:
		data = dict(frappe.local.form_dict or {})
	return data


def _time_to_str(t):
	if not t:
		return ""
	if hasattr(t, "strftime"):
		return t.strftime("%H:%M:%S")
	# Frappe trả field Time dạng datetime.timedelta — str() ra "8:00:00" (thiếu zero-pad).
	# Zero-pad để FE parse đúng (input type=time cần HH:MM 2 chữ số).
	if hasattr(t, "total_seconds"):
		total = int(t.total_seconds())
		return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"
	return str(t)


def _availability_row_to_dict(row):
	return {
		"day_of_week": row.day_of_week or "",
		"is_closed": 1 if row.is_closed else 0,
		"start_time": _time_to_str(row.start_time),
		"end_time": _time_to_str(row.end_time),
	}


def _default_availability_payload():
	return [
		{
			"day_of_week": day,
			"is_closed": 0,
			"start_time": "07:00:00",
			"end_time": "18:00:00",
		}
		for day in WEEKDAY_NAMES
	]


def _normalize_availability_payload(raw_rows):
	"""Chuẩn hoá payload availability từ FE — đảm bảo đủ 7 thứ."""
	by_day = {}
	for row in raw_rows or []:
		day = (row.get("day_of_week") or "").strip()
		if not day:
			continue
		by_day[day] = {
			"day_of_week": day,
			"is_closed": 1 if row.get("is_closed") else 0,
			"start_time": (row.get("start_time") or "07:00:00").strip(),
			"end_time": (row.get("end_time") or "18:00:00").strip(),
		}
	result = []
	for day in WEEKDAY_NAMES:
		if day in by_day:
			result.append(by_day[day])
		else:
			result.append(
				{
					"day_of_week": day,
					"is_closed": 0,
					"start_time": "07:00:00",
					"end_time": "18:00:00",
				}
			)
	return result


def _config_to_dict(doc, *, include_availability=True):
	room = frappe.db.get_value(
		"ERP Administrative Room",
		doc.room_id,
		["title_vn", "title_en", "short_title", "capacity"],
		as_dict=True,
	) or {}
	building = frappe.db.get_value(
		"ERP Administrative Building",
		doc.building_id,
		["title_vn", "title_en", "short_title"],
		as_dict=True,
	) or {}
	out = {
		"name": doc.name,
		"building_id": doc.building_id or "",
		"building_title": (building.get("title_vn") or doc.building_id or "").strip(),
		"room_id": doc.room_id or "",
		"room_title": (room.get("title_vn") or room.get("short_title") or doc.room_id or "").strip(),
		"room_capacity": room.get("capacity"),
		"is_active": 1 if doc.is_active else 0,
		"availability_summary": _summarize_availability(doc),
	}
	if include_availability:
		out["availability"] = [_availability_row_to_dict(r) for r in (doc.availability or [])]
	return out


def _summarize_availability(doc):
	parts = []
	for row in doc.availability or []:
		day = row.day_of_week or ""
		if row.is_closed:
			parts.append(f"{day}: đóng")
		else:
			parts.append(f"{day}: {_time_to_str(row.start_time)[:5]}–{_time_to_str(row.end_time)[:5]}")
	return "; ".join(parts)


def _get_config_doc_for_room(room_id, *, active_only=False):
	"""Lấy config theo room_id. Trả None nếu không có."""
	if not room_id:
		return None
	filters = {"room_id": room_id}
	if active_only:
		filters["is_active"] = 1
	name = frappe.db.get_value(CONFIG_DOCTYPE, filters, "name")
	if not name:
		return None
	return frappe.get_doc(CONFIG_DOCTYPE, name)


def _get_availability_for_datetime(room_id, dt):
	"""Lấy dòng availability của thứ tương ứng với datetime."""
	config = _get_config_doc_for_room(room_id, active_only=True)
	if not config:
		return None, None
	# frappe.utils.get_weekday trả về tên thứ ("Monday", …) — không phải số
	day_name = get_weekday(dt)
	for row in config.availability or []:
		if (row.day_of_week or "").strip() == day_name:
			return config, row
	return config, None


def validate_booking_against_config(room_id, start_dt, end_dt):
	"""Kiểm tra phòng + khung giờ theo cấu hình. Trả (ok, err_response)."""
	if not room_id or not start_dt or not end_dt:
		return False, validation_error_response(_("Thiếu thông tin phòng hoặc thời gian"))

	config = _get_config_doc_for_room(room_id, active_only=True)
	if not config:
		return False, validation_error_response(
			_("Phòng chưa được mở để đặt. Vui lòng liên hệ quản trị viên."),
			{"room_id": ["not_bookable"]},
		)

	if start_dt.date() != end_dt.date():
		return False, validation_error_response(
			_("Khung giờ đặt phòng phải nằm trong cùng một ngày"),
			{"end_time": ["cross_day"]},
		)

	config_start, row = _get_availability_for_datetime(room_id, start_dt)
	if not config_start or not row:
		return False, validation_error_response(
			_("Không tìm thấy cấu hình khung giờ cho ngày này"),
			{"start_time": ["no_config"]},
		)

	if row.is_closed:
		return False, validation_error_response(
			_("Ngày này phòng đóng cửa, không thể đặt"),
			{"start_time": ["closed"]},
		)

	open_start = get_time(row.start_time)
	open_end = get_time(row.end_time)
	booking_start = get_time(start_dt.time())
	booking_end = get_time(end_dt.time())

	if not open_start or not open_end:
		return False, validation_error_response(
			_("Cấu hình khung giờ không hợp lệ"),
			{"start_time": ["invalid_config"]},
		)

	if booking_start < open_start or booking_end > open_end:
		label = f"{_time_to_str(open_start)[:5]}–{_time_to_str(open_end)[:5]}"
		return False, validation_error_response(
			_("Ngoài khung giờ khả dụng ({0})").format(label),
			{"start_time": ["outside_hours"], "end_time": ["outside_hours"]},
		)

	return True, None


def _enrich_rooms_with_yearly_assignment(rooms, school_year_id=None):
	sy = (school_year_id or "").strip() or _active_school_year_id()
	if sy and rooms:
		rnames = [r["name"] for r in rooms]
		ya_rows = frappe.get_all(
			"ERP Administrative Room Yearly Assignment",
			filters={"room": ["in", rnames], "school_year_id": sy},
			fields=["room", "display_title_vn", "display_title_en"],
		)
		ya_map = {y["room"]: y for y in ya_rows}
		for room in rooms:
			y = ya_map.get(room["name"])
			room["yearly_assignment_display"] = y.get("display_title_vn") if y else None
			room["yearly_assignment_display_en"] = y.get("display_title_en") if y else None
	else:
		for room in rooms:
			room["yearly_assignment_display"] = None
			room["yearly_assignment_display_en"] = None
	return rooms


@frappe.whitelist(allow_guest=False)
def get_room_booking_configs():
	"""Danh sách cấu hình đặt phòng cho trang quản trị."""
	try:
		rows = frappe.get_all(
			CONFIG_DOCTYPE,
			fields=["name"],
			order_by="modified desc",
			limit_page_length=0,
		)
		configs = []
		for r in rows:
			doc = frappe.get_doc(CONFIG_DOCTYPE, r.name)
			configs.append(_config_to_dict(doc))
		return success_response({"configs": configs}, "OK")
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "room_booking_config.get_room_booking_configs")
		return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def create_room_booking_config():
	"""Tạo cấu hình phòng khả dụng để đặt."""
	try:
		data = _parse_json_body()
		building_id = (data.get("building_id") or "").strip()
		room_id = (data.get("room_id") or "").strip()
		is_active = 1 if data.get("is_active") in (1, True, "1", "true") else 0
		availability = _normalize_availability_payload(data.get("availability"))

		if not building_id or not frappe.db.exists("ERP Administrative Building", building_id):
			return validation_error_response(_("Thiếu hoặc sai tòa nhà"), {"building_id": ["required"]})
		if not room_id or not frappe.db.exists("ERP Administrative Room", room_id):
			return validation_error_response(_("Thiếu hoặc sai phòng"), {"room_id": ["required"]})
		rb = frappe.db.get_value("ERP Administrative Room", room_id, "building_id")
		if (rb or "").strip() != building_id:
			return validation_error_response(_("Phòng không thuộc tòa nhà đã chọn"), {"room_id": ["invalid"]})
		if frappe.db.exists(CONFIG_DOCTYPE, {"room_id": room_id}):
			return validation_error_response(_("Phòng này đã có cấu hình"), {"room_id": ["duplicate"]})

		doc = frappe.get_doc(
			{
				"doctype": CONFIG_DOCTYPE,
				"building_id": building_id,
				"room_id": room_id,
				"is_active": is_active,
				"availability": availability,
			}
		)
		doc.insert()
		frappe.db.commit()
		return success_response(_config_to_dict(doc), "OK")
	except frappe.ValidationError as e:
		return validation_error_response(str(e))
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "room_booking_config.create_room_booking_config")
		return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def update_room_booking_config():
	"""Cập nhật cấu hình đặt phòng."""
	try:
		data = _parse_json_body()
		name = (data.get("name") or "").strip()
		if not name or not frappe.db.exists(CONFIG_DOCTYPE, name):
			return not_found_response(_("Không tìm thấy cấu hình"))

		doc = frappe.get_doc(CONFIG_DOCTYPE, name)
		building_id = (data.get("building_id") or doc.building_id or "").strip()
		room_id = (data.get("room_id") or doc.room_id or "").strip()

		if building_id:
			doc.building_id = building_id
		if room_id:
			if room_id != doc.room_id and frappe.db.exists(CONFIG_DOCTYPE, {"room_id": room_id}):
				return validation_error_response(_("Phòng này đã có cấu hình"), {"room_id": ["duplicate"]})
			doc.room_id = room_id
		if "is_active" in data:
			doc.is_active = 1 if data.get("is_active") in (1, True, "1", "true") else 0
		if data.get("availability") is not None:
			doc.set("availability", [])
			for row in _normalize_availability_payload(data.get("availability")):
				doc.append("availability", row)

		rb = frappe.db.get_value("ERP Administrative Room", doc.room_id, "building_id")
		if (rb or "").strip() != (doc.building_id or "").strip():
			return validation_error_response(_("Phòng không thuộc tòa nhà đã chọn"), {"room_id": ["invalid"]})

		doc.save()
		frappe.db.commit()
		return success_response(_config_to_dict(doc), "OK")
	except frappe.ValidationError as e:
		return validation_error_response(str(e))
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "room_booking_config.update_room_booking_config")
		return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def delete_room_booking_config():
	"""Xoá cấu hình đặt phòng."""
	try:
		data = _parse_json_body()
		name = (data.get("name") or "").strip()
		if not name or not frappe.db.exists(CONFIG_DOCTYPE, name):
			return not_found_response(_("Không tìm thấy cấu hình"))
		frappe.delete_doc(CONFIG_DOCTYPE, name)
		frappe.db.commit()
		return success_response({"name": name}, "OK")
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "room_booking_config.delete_room_booking_config")
		return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def get_bookable_rooms():
	"""Danh sách phòng đang mở đặt phòng — dùng cho trang Ứng dụng."""
	try:
		data = _parse_json_body()
		school_year_id = (data.get("school_year_id") or "").strip() or None

		config_names = frappe.get_all(
			CONFIG_DOCTYPE,
			filters={"is_active": 1},
			fields=["name"],
			limit_page_length=0,
		)
		rooms = []
		for cn in config_names:
			doc = frappe.get_doc(CONFIG_DOCTYPE, cn.name)
			room = frappe.db.get_value(
				"ERP Administrative Room",
				doc.room_id,
				["name", "title_vn", "title_en", "short_title", "room_type", "capacity", "building_id"],
				as_dict=True,
			)
			if not room:
				continue
			building = frappe.db.get_value(
				"ERP Administrative Building",
				doc.building_id,
				["title_vn", "title_en", "short_title"],
				as_dict=True,
			) or {}
			rooms.append(
				{
					"name": room.name,
					"title_vn": room.title_vn or "",
					"title_en": room.title_en or "",
					"short_title": room.short_title or "",
					"room_type": room.room_type or "",
					"capacity": room.capacity,
					"building_id": doc.building_id or room.building_id or "",
					"building_title_vn": (building.get("title_vn") or "").strip(),
					"building_title_en": (building.get("title_en") or "").strip(),
					"config_name": doc.name,
					"availability": [_availability_row_to_dict(r) for r in (doc.availability or [])],
				}
			)

		_enrich_rooms_with_yearly_assignment(rooms, school_year_id)
		return success_response({"rooms": rooms}, "OK")
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "room_booking_config.get_bookable_rooms")
		return error_response(str(e))
