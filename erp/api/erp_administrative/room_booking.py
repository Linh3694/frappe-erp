# Copyright (c) 2026, Wellspring International School and contributors
# API Đặt phòng — doctype ERP Room Booking là nguồn dữ liệu duy nhất cho lịch
# đặt phòng và chống trùng giờ. Trang Đặt phòng tạo booking KHÔNG kèm ticket;
# form ticket Hành chính (category sự kiện/CSVC) tạo ticket VÀ gọi helper ở đây
# để tạo/đồng bộ booking tương ứng.

import json

import frappe
from frappe import _
from frappe.utils import cint, get_datetime, now_datetime

from erp.utils.api_response import (
    error_response,
    forbidden_response,
    not_found_response,
    success_response,
    validation_error_response,
)
from erp.api.erp_administrative.room_booking_config import validate_booking_against_config
from erp.api.erp_administrative.room_booking_ics import (
    bump_calendar_sequence,
    ensure_calendar_uid,
    send_booking_invites,
)

BOOKING_DOCTYPE = "ERP Room Booking"
ATTENDEE_DOCTYPE = "ERP Room Booking Attendee"


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
    """Booking trùng khung giờ trong cùng phòng (bỏ qua Cancelled)."""
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


def _resolve_attendee_info(email):
    """Thông tin người tham dự từ email User nội bộ."""
    em = (email or "").strip()
    if not em:
        return None
    uid = frappe.db.get_value("User", em, "name") or frappe.db.get_value("User", {"email": em}, "name")
    if not uid:
        return None
    enabled = cint(frappe.db.get_value("User", uid, "enabled"))
    if not enabled:
        return None
    fields = ["full_name"]
    if frappe.db.has_column("User", "department"):
        fields.append("department")
    vals = frappe.db.get_value("User", uid, fields, as_dict=True) or {}
    return {
        "user": uid,
        "email": em,
        "full_name": (vals.get("full_name") or em).strip(),
        "department": (vals.get("department") or "").strip(),
    }


def _normalize_attendee_emails(raw, booker_email=None):
    """Chuẩn hoá danh sách email người tham dự — loại trùng và loại người đặt."""
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError, ValueError):
            raw = [raw]
    if not isinstance(raw, (list, tuple)):
        return []
    booker_key = (booker_email or "").strip().lower()
    seen = set()
    result = []
    for item in raw:
        em = (item if isinstance(item, str) else (item.get("email") if isinstance(item, dict) else "")).strip()
        key = em.lower()
        if not em or key in seen or (booker_key and key == booker_key):
            continue
        seen.add(key)
        result.append(em)
    return result


def _validate_attendees(raw_attendees, booker_email):
    """Validate người tham dự — chỉ User nội bộ enabled. Trả (rows, err_response)."""
    emails = _normalize_attendee_emails(raw_attendees, booker_email=booker_email)
    rows = []
    invalid = []
    for em in emails:
        info = _resolve_attendee_info(em)
        if not info:
            invalid.append(em)
            continue
        rows.append(info)
    if invalid:
        return None, validation_error_response(
            _("Người tham dự không hợp lệ hoặc đã bị vô hiệu hoá: {0}").format(", ".join(invalid)),
            {"attendees": ["invalid"]},
        )
    return rows, None


def _attendees_to_dict_list(doc):
    """Child attendees → list dict cho API."""
    return [
        {
            "user": row.user or "",
            "email": row.email or "",
            "full_name": row.full_name or "",
            "department": row.department or "",
        }
        for row in (doc.get("attendees") or [])
    ]


def _load_attendees_map(booking_names):
    """Batch load attendees theo parent booking."""
    if not booking_names:
        return {}
    children = frappe.get_all(
        ATTENDEE_DOCTYPE,
        filters={"parent": ["in", booking_names], "parenttype": BOOKING_DOCTYPE},
        fields=["parent", "user", "email", "full_name", "department"],
        order_by="idx asc",
    )
    result = {}
    for c in children:
        result.setdefault(c.parent, []).append(
            {
                "user": c.user or "",
                "email": c.email or "",
                "full_name": c.full_name or "",
                "department": c.department or "",
            }
        )
    return result


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


def _insert_booking(ctx, *, email, source, source_ticket=None, attendee_rows=None, send_ics=True):
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
        "calendar_sequence": 0,
        "attendees": [],
    }
    if campus_id:
        row["campus_id"] = campus_id
    for att in attendee_rows or []:
        row["attendees"].append(
            {
                "doctype": ATTENDEE_DOCTYPE,
                "user": att["user"],
                "email": att["email"],
                "full_name": att["full_name"],
                "department": att.get("department") or "",
            }
        )
    doc = frappe.get_doc(row)
    doc.insert(ignore_permissions=True)
    ensure_calendar_uid(doc)
    if send_ics:
        send_booking_invites(doc, method="REQUEST")
    return doc


def _apply_attendees_to_doc(doc, attendee_rows):
    """Cập nhật child attendees trên booking đã tồn tại."""
    doc.set("attendees", [])
    for att in attendee_rows or []:
        doc.append(
            "attendees",
            {
                "user": att["user"],
                "email": att["email"],
                "full_name": att["full_name"],
                "department": att.get("department") or "",
            },
        )


@frappe.whitelist(allow_guest=False)
def create_room_booking():
    """Đặt phòng từ trang Đặt phòng — tạo ERP Room Booking, gửi lời mời .ics nếu cấu hình mail."""
    try:
        data = _parse_json_body()
        ctx, err = _validate_booking_payload(data)
        if err:
            return err
        email = _session_email()
        attendee_rows, err_att = _validate_attendees(data.get("attendees"), booker_email=email)
        if err_att:
            return err_att
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
        doc = _insert_booking(
            ctx,
            email=email,
            source="room_booking_page",
            attendee_rows=attendee_rows,
        )
        frappe.db.commit()
        return success_response(_booking_to_dict(doc), "OK")
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "room_booking.create_room_booking")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def cancel_room_booking():
    """Huỷ một lượt đặt phòng — CHỈ người đặt mới được huỷ (qua tiện ích đặt phòng)."""
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
            bump_calendar_sequence(doc)
            doc.save(ignore_permissions=True)
            send_booking_invites(doc, method="CANCEL")
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
        "attendees": _attendees_to_dict_list(doc),
    }


@frappe.whitelist(allow_guest=False)
def get_room_bookings(room_id=None, range_start=None, range_end=None, exclude_ticket_id=None, exclude_booking_id=None):
    """Lịch đặt phòng theo phòng — dùng chung cho trang Đặt phòng và lịch trên form ticket."""
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

        attendee_map = _load_attendees_map([r.name for r in rows])

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
                    "attendees": attendee_map.get(r.name, []),
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


def create_booking_for_ticket(ticket, attendee_rows=None):
    """Tạo ERP Room Booking gắn với ticket sự kiện/CSVC (idempotent theo source_ticket)."""
    try:
        ctx = _ticket_booking_ctx(ticket)
        if not ctx["room_id"] or not ctx["start_dt"] or not ctx["end_dt"]:
            return None
        existing = frappe.db.get_value(BOOKING_DOCTYPE, {"source_ticket": ticket.name}, "name")
        if existing:
            return sync_booking_for_ticket(ticket, attendee_rows=attendee_rows)
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
            attendee_rows=attendee_rows,
        )
    except Exception:
        frappe.log_error(frappe.get_traceback(), "room_booking.create_booking_for_ticket")
        return None


def sync_booking_for_ticket(ticket, attendee_rows=None):
    """Đồng bộ booking gắn với ticket: cập nhật phòng/giờ/attendees, hoặc Cancelled khi ticket huỷ."""
    try:
        name = frappe.db.get_value(BOOKING_DOCTYPE, {"source_ticket": ticket.name}, "name")
        ticket_cancelled = (getattr(ticket, "status", None) or "") == "Cancelled"
        ctx = _ticket_booking_ctx(ticket)
        if not name:
            if not ticket_cancelled and ctx["room_id"] and ctx["start_dt"] and ctx["end_dt"]:
                return create_booking_for_ticket(ticket, attendee_rows=attendee_rows)
            return None
        doc = frappe.get_doc(BOOKING_DOCTYPE, name)
        if ticket_cancelled:
            if doc.status != "Cancelled":
                doc.status = "Cancelled"
                bump_calendar_sequence(doc)
                doc.save(ignore_permissions=True)
                send_booking_invites(doc, method="CANCEL")
            return doc

        changed = False
        for field, val in (
            ("title", ctx["title"]),
            ("description", ctx["description"]),
            ("building_id", ctx["building_id"]),
            ("room_id", ctx["room_id"]),
            ("start_time", ctx["start_dt"]),
            ("end_time", ctx["end_dt"]),
        ):
            if val and getattr(doc, field) != val:
                setattr(doc, field, val)
                changed = True

        if attendee_rows is not None:
            _apply_attendees_to_doc(doc, attendee_rows)
            changed = True

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
        if changed:
            bump_calendar_sequence(doc)
        doc.save(ignore_permissions=True)
        if changed:
            send_booking_invites(doc, method="REQUEST")
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
                doc = frappe.get_doc(BOOKING_DOCTYPE, n)
                bump_calendar_sequence(doc)
                send_booking_invites(doc, method="CANCEL")
                frappe.delete_doc(BOOKING_DOCTYPE, n, ignore_permissions=True, force=True)
            else:
                doc = frappe.get_doc(BOOKING_DOCTYPE, n)
                if doc.status != "Cancelled":
                    doc.status = "Cancelled"
                    bump_calendar_sequence(doc)
                    doc.save(ignore_permissions=True)
                    send_booking_invites(doc, method="CANCEL")
    except Exception:
        frappe.log_error(frappe.get_traceback(), "room_booking.remove_booking_for_ticket")
