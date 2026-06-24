# Copyright (c) 2026, Wellspring International School and contributors
# API Đặt phòng — doctype ERP Room Booking là nguồn dữ liệu duy nhất cho lịch
# đặt phòng và chống trùng giờ. Trang Đặt phòng tạo booking KHÔNG kèm ticket;
# form ticket Hành chính (category sự kiện/CSVC) tạo ticket VÀ gọi helper ở đây
# để tạo/đồng bộ booking tương ứng.

import json

import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime

from erp.utils.api_response import (
    error_response,
    forbidden_response,
    not_found_response,
    success_response,
    validation_error_response,
)
from erp.api.erp_administrative.room_booking_config import validate_booking_against_config

BOOKING_DOCTYPE = "ERP Room Booking"


def _parse_json_body():
    """Đọc JSON từ request body (đồng nhất với administrative_ticket)."""
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


def _session_email():
    return (frappe.db.get_value("User", frappe.session.user, "email") or "").strip()


def _room_booking_conflicts(room_id, start_dt, end_dt, exclude_booking_id=None, exclude_ticket_id=None):
    """Booking trùng khung giờ trong cùng phòng (bỏ qua Cancelled).

    Overlap chuẩn: bắt đầu < end mới VÀ kết thúc > start mới.
    exclude_booking_id / exclude_ticket_id: bỏ qua chính booking đang sửa (hoặc
    booking gắn với ticket đang sửa) để không tự báo trùng.
    """
    if not room_id or not start_dt or not end_dt:
        return []
    filters = [
        ["room_id", "=", room_id],
        ["status", "!=", "Cancelled"],
        ["start_time", "<", end_dt],
        ["end_time", ">", start_dt],
    ]
    if exclude_booking_id:
        filters.append(["name", "!=", exclude_booking_id])
    if exclude_ticket_id:
        filters.append(["source_ticket", "!=", exclude_ticket_id])
    return frappe.get_all(BOOKING_DOCTYPE, filters=filters, fields=["name"])


def _resolve_booker_info(email):
    """Họ tên / avatar / phòng ban / mã NV của người đặt theo email (User.name)."""
    info = {"fullname": "", "avatar": "", "department": "", "employee_code": "", "user": None}
    em = (email or "").strip()
    if not em:
        return info
    uid = frappe.db.get_value("User", em, "name") or frappe.db.get_value("User", {"email": em}, "name")
    if not uid:
        info["fullname"] = em
        return info
    fields = ["full_name", "user_image"]
    if frappe.db.has_column("User", "department"):
        fields.append("department")
    if frappe.db.has_column("User", "employee_code"):
        fields.append("employee_code")
    if frappe.db.has_column("User", "username"):
        fields.append("username")
    vals = frappe.db.get_value("User", uid, fields, as_dict=True) or {}
    info["user"] = uid
    info["fullname"] = (vals.get("full_name") or em).strip()
    info["avatar"] = (vals.get("user_image") or "").strip()
    info["department"] = (vals.get("department") or "").strip()
    info["employee_code"] = (vals.get("employee_code") or vals.get("username") or "").strip()
    return info


def _validate_booking_payload(data):
    """Validate building/room/time chung cho create_room_booking. Trả (ctx, err_response)."""
    title = (data.get("title") or "").strip()
    description = (data.get("description") or "").strip()
    building_id = (data.get("building_id") or data.get("event_building_id") or "").strip()
    room_id = (data.get("room_id") or data.get("event_room_id") or "").strip()
    start_raw = data.get("start_time") or data.get("event_start_time")
    end_raw = data.get("end_time") or data.get("event_end_time")

    if not title:
        return None, validation_error_response(_("Thiếu tiêu đề"), {"title": ["required"]})
    if not building_id or not frappe.db.exists("ERP Administrative Building", building_id):
        return None, validation_error_response(
            _("Thiếu hoặc sai tòa nhà"), {"building_id": ["required"]}
        )
    if not room_id or not frappe.db.exists("ERP Administrative Room", room_id):
        return None, validation_error_response(_("Thiếu hoặc sai phòng"), {"room_id": ["required"]})
    rb = frappe.db.get_value("ERP Administrative Room", room_id, "building_id")
    if (rb or "").strip() != building_id:
        return None, validation_error_response(
            _("Phòng không thuộc tòa nhà đã chọn"), {"room_id": ["invalid"]}
        )
    if not start_raw or not end_raw:
        return None, validation_error_response(
            _("Thiếu thời gian bắt đầu / kết thúc"),
            {"start_time": ["required"], "end_time": ["required"]},
        )
    try:
        start_dt = get_datetime(start_raw)
        end_dt = get_datetime(end_raw)
    except Exception:
        return None, validation_error_response(
            _("Định dạng thời gian không hợp lệ"),
            {"start_time": ["invalid"], "end_time": ["invalid"]},
        )
    if start_dt.date() < now_datetime().date():
        return None, validation_error_response(
            _("Ngày bắt đầu không được ở ngày quá khứ"), {"start_time": ["past"]}
        )
    if end_dt <= start_dt:
        return None, validation_error_response(
            _("Thời gian kết thúc phải sau thời gian bắt đầu"), {"end_time": ["invalid"]}
        )
    ctx = {
        "title": title,
        "description": description,
        "building_id": building_id,
        "room_id": room_id,
        "start_dt": start_dt,
        "end_dt": end_dt,
    }
    return ctx, None


def _insert_booking(ctx, *, email, source, source_ticket=None):
    """Tạo bản ghi ERP Room Booking (ignore_permissions vì Teacher cũng được đặt)."""
    booker = _resolve_booker_info(email)
    campus_id = frappe.db.get_value("ERP Administrative Room", ctx["room_id"], "campus_id")
    row = {
        "doctype": BOOKING_DOCTYPE,
        "title": ctx["title"],
        "description": ctx.get("description") or "",
        "building_id": ctx["building_id"],
        "room_id": ctx["room_id"],
        "start_time": ctx["start_dt"],
        "end_time": ctx["end_dt"],
        "status": "Booked",
        "booked_by": booker["user"],
        "booked_by_email": email or "",
        "booked_by_fullname": booker["fullname"],
        "booked_by_avatar": booker["avatar"],
        "booked_by_department": booker["department"],
        "source": source,
        "source_ticket": source_ticket or None,
    }
    if campus_id:
        row["campus_id"] = campus_id
    doc = frappe.get_doc(row)
    doc.insert(ignore_permissions=True)
    return doc


@frappe.whitelist(allow_guest=False)
def create_room_booking():
    """Đặt phòng từ trang Đặt phòng — CHỈ tạo ERP Room Booking, không tạo ticket,
    không gửi mail / thông báo."""
    try:
        data = _parse_json_body()
        ctx, err = _validate_booking_payload(data)
        if err:
            return err
        ok_cfg, err_cfg = validate_booking_against_config(
            ctx["room_id"], ctx["start_dt"], ctx["end_dt"]
        )
        if not ok_cfg:
            return err_cfg
        if _room_booking_conflicts(ctx["room_id"], ctx["start_dt"], ctx["end_dt"]):
            return validation_error_response(
                _("Khung giờ này đã có người đặt phòng. Vui lòng chọn thời gian khác."),
                {"end_time": ["conflict"]},
            )
        email = _session_email()
        doc = _insert_booking(ctx, email=email, source="room_booking_page")
        frappe.db.commit()
        return success_response(_booking_to_dict(doc), "OK")
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "room_booking.create_room_booking")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def cancel_room_booking():
    """Huỷ một lượt đặt phòng — CHỈ người đặt mới được huỷ (qua tiện ích đặt phòng).

    Booking gắn với ticket (source admin_ticket) phải huỷ ở ticket tương ứng để
    không lệch trạng thái ticket ↔ booking.
    """
    try:
        data = _parse_json_body()
        booking_id = (data.get("booking_id") or data.get("name") or "").strip()
        if not booking_id or not frappe.db.exists(BOOKING_DOCTYPE, booking_id):
            return not_found_response(_("Không tìm thấy lượt đặt phòng"))
        doc = frappe.get_doc(BOOKING_DOCTYPE, booking_id)

        email = _session_email()
        if (doc.booked_by_email or "").strip().lower() != (email or "").strip().lower():
            return forbidden_response(_("Chỉ người đặt phòng mới được huỷ lượt đặt này"))

        if (doc.source or "") == "admin_ticket" or doc.source_ticket:
            return validation_error_response(
                _("Lượt đặt này gắn với ticket — vui lòng huỷ ở ticket tương ứng."),
                {"source": ["ticket"]},
            )

        if doc.status != "Cancelled":
            doc.status = "Cancelled"
            doc.save(ignore_permissions=True)
            frappe.db.commit()
        return success_response(_booking_to_dict(doc), "OK")
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "room_booking.cancel_room_booking")
        return error_response(str(e))


def _booking_to_dict(doc):
    """Bản ghi chi tiết booking trả về cho FE sau khi tạo."""
    return {
        "name": doc.name,
        "title": doc.title or "",
        "description": doc.description or "",
        "building_id": doc.building_id,
        "room_id": doc.room_id,
        "start_time": str(doc.start_time) if doc.start_time else "",
        "end_time": str(doc.end_time) if doc.end_time else "",
        "status": doc.status or "",
        "booked_by_email": doc.booked_by_email or "",
        "booked_by_fullname": doc.booked_by_fullname or "",
        "source": doc.source or "",
        "source_ticket": doc.source_ticket or "",
    }


@frappe.whitelist(allow_guest=False)
def get_room_bookings(room_id=None, range_start=None, range_end=None, exclude_ticket_id=None, exclude_booking_id=None):
    """Lịch đặt phòng theo phòng — dùng chung cho trang Đặt phòng và lịch trên
    form ticket. Trả thời gian + thông tin người đặt; loại trừ Cancelled.

    Giữ tên field event_start_time / event_end_time để tương thích calendar FE.
    exclude_ticket_id: bỏ booking gắn với ticket đang sửa (tránh tự báo trùng).
    """
    try:
        data = _parse_json_body()
        room_id = (room_id or data.get("room_id") or "").strip()
        range_start = range_start or data.get("range_start")
        range_end = range_end or data.get("range_end")
        exclude_ticket_id = (exclude_ticket_id or data.get("exclude_ticket_id") or "").strip() or None
        exclude_booking_id = (exclude_booking_id or data.get("exclude_booking_id") or "").strip() or None

        if not room_id:
            return validation_error_response(_("Thiếu room_id"), {"room_id": ["required"]})
        if not frappe.db.exists("ERP Administrative Room", room_id):
            return not_found_response(_("Không tìm thấy phòng"))

        filters = [
            ["room_id", "=", room_id],
            ["status", "!=", "Cancelled"],
        ]
        if range_start and range_end:
            try:
                rs = get_datetime(range_start)
                re_ = get_datetime(range_end)
            except Exception:
                return validation_error_response(
                    _("Khoảng thời gian không hợp lệ"),
                    {"range_start": ["invalid"], "range_end": ["invalid"]},
                )
            filters.append(["start_time", "<", re_])
            filters.append(["end_time", ">", rs])
        if exclude_booking_id:
            filters.append(["name", "!=", exclude_booking_id])
        if exclude_ticket_id:
            filters.append(["source_ticket", "!=", exclude_ticket_id])

        rows = frappe.get_all(
            BOOKING_DOCTYPE,
            filters=filters,
            fields=[
                "name",
                "title",
                "booked_by_email",
                "booked_by_fullname",
                "booked_by_department",
                "start_time",
                "end_time",
                "status",
                "source",
                "source_ticket",
            ],
            order_by="start_time asc",
        )

        emails = list({(r.booked_by_email or "").strip() for r in rows if (r.booked_by_email or "").strip()})
        profile_map = {}
        if emails:
            user_fields = ["name", "email"]
            if frappe.db.has_column("User", "employee_code"):
                user_fields.append("employee_code")
            if frappe.db.has_column("User", "username"):
                user_fields.append("username")
            if frappe.db.has_column("User", "department"):
                user_fields.append("department")
            users = frappe.get_all(
                "User",
                filters={"name": ["in", emails]},
                fields=user_fields,
                limit_page_length=0,
            )
            for u in users:
                uid = (u.get("name") or "").strip()
                if not uid:
                    continue
                profile_map[uid] = {
                    "employee_code": (u.get("employee_code") or u.get("username") or "").strip(),
                    "department": (u.get("department") or "").strip(),
                }

        bookings = []
        for r in rows:
            em = (r.booked_by_email or "").strip()
            prof = profile_map.get(em, {})
            bookings.append(
                {
                    "name": r.name,
                    "title": r.title or "",
                    "booked_by": (r.booked_by_fullname or em).strip(),
                    "booked_by_email": em,
                    "booked_by_department": (r.booked_by_department or "").strip()
                    or prof.get("department", ""),
                    "booked_by_employee_code": prof.get("employee_code", ""),
                    "event_start_time": str(r.start_time) if r.start_time else "",
                    "event_end_time": str(r.end_time) if r.end_time else "",
                    "status": r.status or "",
                    "source": r.source or "",
                    "source_ticket": r.source_ticket or "",
                }
            )
        return success_response({"bookings": bookings}, "OK")
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "room_booking.get_room_bookings")
        return error_response(str(e))


# ---------------------------------------------------------------------------
# Helper gọi từ administrative_ticket (form ticket sự kiện/CSVC)
# ---------------------------------------------------------------------------

def _ticket_booking_ctx(ticket):
    """Lấy building/room/time/title từ ticket sự kiện."""
    return {
        "title": (getattr(ticket, "title", None) or "").strip() or ticket.name,
        "description": (getattr(ticket, "description", None) or "").strip(),
        "building_id": (getattr(ticket, "event_building_id", None) or "").strip(),
        "room_id": (getattr(ticket, "event_room_id", None) or "").strip(),
        "start_dt": getattr(ticket, "event_start_time", None),
        "end_dt": getattr(ticket, "event_end_time", None),
    }


def create_booking_for_ticket(ticket):
    """Tạo ERP Room Booking gắn với ticket sự kiện/CSVC (idempotent theo source_ticket)."""
    try:
        ctx = _ticket_booking_ctx(ticket)
        if not ctx["room_id"] or not ctx["start_dt"] or not ctx["end_dt"]:
            return None
        existing = frappe.db.get_value(BOOKING_DOCTYPE, {"source_ticket": ticket.name}, "name")
        if existing:
            return sync_booking_for_ticket(ticket)
        ok_cfg, err_cfg = validate_booking_against_config(
            ctx["room_id"], ctx["start_dt"], ctx["end_dt"]
        )
        if not ok_cfg:
            msg = (
                (err_cfg or {}).get("message")
                if isinstance(err_cfg, dict)
                else str(err_cfg)
            ) or _("Không thể đặt phòng theo cấu hình hiện tại")
            frappe.throw(msg)
        return _insert_booking(
            ctx,
            email=(getattr(ticket, "creator_email", None) or "").strip(),
            source="admin_ticket",
            source_ticket=ticket.name,
        )
    except Exception:
        frappe.log_error(frappe.get_traceback(), "room_booking.create_booking_for_ticket")
        return None


def sync_booking_for_ticket(ticket):
    """Đồng bộ booking gắn với ticket: cập nhật phòng/giờ, hoặc Cancelled khi ticket bị huỷ."""
    try:
        name = frappe.db.get_value(BOOKING_DOCTYPE, {"source_ticket": ticket.name}, "name")
        ticket_cancelled = (getattr(ticket, "status", None) or "") == "Cancelled"
        ctx = _ticket_booking_ctx(ticket)
        if not name:
            # Chưa có booking và ticket còn hiệu lực → tạo mới
            if not ticket_cancelled and ctx["room_id"] and ctx["start_dt"] and ctx["end_dt"]:
                return create_booking_for_ticket(ticket)
            return None
        doc = frappe.get_doc(BOOKING_DOCTYPE, name)
        if ticket_cancelled:
            doc.status = "Cancelled"
            doc.save(ignore_permissions=True)
            return doc
        doc.title = ctx["title"]
        doc.description = ctx["description"]
        if ctx["building_id"]:
            doc.building_id = ctx["building_id"]
        if ctx["room_id"]:
            doc.room_id = ctx["room_id"]
        if ctx["start_dt"]:
            doc.start_time = ctx["start_dt"]
        if ctx["end_dt"]:
            doc.end_time = ctx["end_dt"]
        ok_cfg, err_cfg = validate_booking_against_config(
            doc.room_id, doc.start_time, doc.end_time
        )
        if not ok_cfg:
            msg = (
                (err_cfg or {}).get("message")
                if isinstance(err_cfg, dict)
                else str(err_cfg)
            ) or _("Không thể đặt phòng theo cấu hình hiện tại")
            frappe.throw(msg)
        doc.status = "Booked"
        doc.save(ignore_permissions=True)
        return doc
    except Exception:
        frappe.log_error(frappe.get_traceback(), "room_booking.sync_booking_for_ticket")
        return None


def remove_booking_for_ticket(ticket_name, hard_delete=False):
    """Huỷ (hoặc xoá) booking gắn với ticket khi ticket bị huỷ/xoá."""
    try:
        names = frappe.get_all(
            BOOKING_DOCTYPE, filters={"source_ticket": ticket_name}, pluck="name"
        )
        for n in names:
            if hard_delete:
                frappe.delete_doc(BOOKING_DOCTYPE, n, ignore_permissions=True, force=True)
            else:
                frappe.db.set_value(BOOKING_DOCTYPE, n, "status", "Cancelled")
    except Exception:
        frappe.log_error(frappe.get_traceback(), "room_booking.remove_booking_for_ticket")
