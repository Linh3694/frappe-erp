# Copyright (c) 2026, Wellspring International School and contributors
# Chốt năm học — batch theo dõi kiểm kê phòng (CSVC).

import frappe
from frappe import _

from erp.utils.api_response import (
    error_response,
    list_response,
    not_found_response,
    single_item_response,
    success_response,
    validation_error_response,
)
from erp.api.erp_administrative.administrative_ticket import _active_school_year_id_api

_TICKET_DONE = ("Closed", "Resolved", "Cancelled", "Done")


def _count_open_tickets_room(room_id):
    if not room_id:
        return 0
    return frappe.db.count(
        "ERP Administrative Ticket",
        {"room_id": room_id, "status": ["not in", _TICKET_DONE]},
    )


def _inventory_rejection_note(inventory_check_id):
    """Lý do từ chối từ bản ghi kiểm kê (Facility Handover incoming hoặc Inventory Check legacy)."""
    if not inventory_check_id or not str(inventory_check_id).strip():
        return None
    iid = str(inventory_check_id).strip()
    if frappe.db.exists("ERP Administrative Facility Handover", iid):
        return frappe.db.get_value("ERP Administrative Facility Handover", iid, "review_note") or None
    if frappe.db.exists("ERP Administrative Inventory Check", iid):
        return frappe.db.get_value("ERP Administrative Inventory Check", iid, "review_note") or None
    return None


def _school_year_display_label(school_year_id):
    """Nhãn hiển thị năm học (title_vn ưu tiên) — tránh hiện ID doc trên UI."""
    if not school_year_id:
        return ""
    row = frappe.db.get_value(
        "SIS School Year",
        school_year_id,
        ["title_vn", "title_en"],
        as_dict=True,
    )
    if not row:
        return school_year_id
    v = (row.get("title_vn") or "").strip()
    e = (row.get("title_en") or "").strip()
    return v or e or school_year_id


def _parse_json_body():
    data = {}
    if frappe.request and frappe.request.data:
        try:
            raw = frappe.request.data
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            if raw:
                import json

                data = json.loads(raw)
        except Exception:
            data = dict(frappe.local.form_dict or {})
    else:
        data = dict(frappe.local.form_dict or {})
    return data


def _closure_room_row_matches(row_room, room_id):
    """So khớp Link Room — chuẩn hóa chuỗi."""
    return (row_room or "").strip() == (room_id or "").strip()


def _closure_refresh_counts(doc):
    """Cập nhật số đếm trên header từ bảng con."""
    rooms = doc.rooms or []
    doc.total_rooms = len(rooms)
    pending = submitted = accepted = rejected = 0
    for row in rooms:
        st = (row.status or "pending").lower()
        if st == "pending":
            pending += 1
        elif st == "submitted":
            submitted += 1
        elif st == "accepted":
            accepted += 1
        elif st == "rejected":
            rejected += 1
    doc.pending_inventory = pending + submitted
    doc.accepted_inventory = accepted
    doc.rejected_inventory = rejected


def sync_closure_row_on_inventory_done(closure_id, room_id, inventory_id, outcome):
    """Cập nhật dòng closure khi duyệt kiểm kê (accept/reject)."""
    if not closure_id or not frappe.db.exists("ERP Administrative Academic Year Closure", closure_id):
        return
    doc = frappe.get_doc("ERP Administrative Academic Year Closure", closure_id)
    matched = False
    for row in doc.rooms or []:
        if not _closure_room_row_matches(row.room, room_id):
            continue
        row.inventory_check_id = inventory_id
        row.status = "accepted" if outcome == "accepted" else "rejected"
        matched = True
        break
    if not matched:
        frappe.log_error(
            f"sync_closure_row_on_inventory_done: không có dòng phòng room_id={room_id!r} closure={closure_id!r}",
            "academic_year_closure.sync_inventory_done_no_row",
        )
        return
    _closure_refresh_counts(doc)
    doc.save(ignore_permissions=True)
    frappe.db.commit()


def sync_closure_row_on_inventory_submitted(closure_id, room_id, inventory_id):
    """Đánh dấu đã gửi kiểm kê (chờ duyệt)."""
    if not closure_id or not frappe.db.exists("ERP Administrative Academic Year Closure", closure_id):
        return
    doc = frappe.get_doc("ERP Administrative Academic Year Closure", closure_id)
    matched = False
    for row in doc.rooms or []:
        if not _closure_room_row_matches(row.room, room_id):
            continue
        row.inventory_check_id = inventory_id
        row.status = "submitted"
        matched = True
        break
    if not matched:
        frappe.log_error(
            f"sync_closure_row_on_inventory_submitted: không có dòng phòng room_id={room_id!r} closure={closure_id!r}",
            "academic_year_closure.sync_inventory_submitted_no_row",
        )
        return
    _closure_refresh_counts(doc)
    doc.save(ignore_permissions=True)
    frappe.db.commit()


def _notify_closure_room_stub(closure_id, room_id, kind):
    """Hook gửi email/portal sau này — hiện chỉ log."""
    frappe.logger().info(
        f"notify_closure_room_stub closure={closure_id} room={room_id} kind={kind}"
    )


@frappe.whitelist(allow_guest=False)
def start_closure():
    """
    Bắt đầu đợt chốt năm: school_year_id, campus_id.
    Tạo bản ghi Closure + một dòng room cho mỗi Yearly Assignment active của campus trong năm đó.
    """
    try:
        data = _parse_json_body()
        school_year_id = (data.get("school_year_id") or "").strip()
        campus_id = (data.get("campus_id") or "").strip()
        school_year_id = _active_school_year_id_api(school_year_id)
        if not school_year_id:
            return validation_error_response(_("Thiếu năm học"), {"school_year_id": ["required"]})
        if not campus_id or not frappe.db.exists("SIS Campus", campus_id):
            return validation_error_response(_("Campus không hợp lệ"), {"campus_id": ["invalid"]})

        dup = frappe.db.exists(
            "ERP Administrative Academic Year Closure",
            {"school_year_id": school_year_id, "campus_id": campus_id, "status": ["in", ["draft", "in_progress"]]},
        )
        if dup:
            return validation_error_response(_("Đã có đợt chốt đang mở cho năm/campus này."), {"duplicate": [dup]})

        ya_rows = frappe.db.sql(
            """
            SELECT ya.name AS ya_name, ya.room, ya.status AS ya_status
            FROM `tabERP Administrative Room Yearly Assignment` ya
            INNER JOIN `tabERP Administrative Room` r ON r.name = ya.room
            WHERE ya.school_year_id = %(sy)s
              AND r.campus_id = %(campus)s
              AND ya.status = 'active'
            """,
            {"sy": school_year_id, "campus": campus_id},
            as_dict=True,
        )

        doc = frappe.get_doc(
            {
                "doctype": "ERP Administrative Academic Year Closure",
                "school_year_id": school_year_id,
                "campus_id": campus_id,
                "status": "in_progress",
                "started_on": frappe.utils.now(),
                "started_by": frappe.session.user,
            }
        )
        for row in ya_rows:
            doc.append(
                "rooms",
                {
                    "room": row.room,
                    "yearly_assignment_id": row.ya_name,
                    "status": "pending",
                },
            )
        _closure_refresh_counts(doc)
        doc.insert()
        frappe.db.commit()

        for row in doc.rooms:
            _notify_closure_room_stub(doc.name, row.room, "started")

        return single_item_response({"name": doc.name, "status": doc.status}, _("Đã tạo đợt kiểm kê cuối năm"))
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "academic_year_closure.start_closure")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def get_closure_dashboard():
    """Chi tiết đợt chốt: closure_id."""
    try:
        data = _parse_json_body()
        closure_id = (data.get("closure_id") or data.get("name") or "").strip()
        if not closure_id or not frappe.db.exists("ERP Administrative Academic Year Closure", closure_id):
            return not_found_response(_("Không tìm thấy"))

        doc = frappe.get_doc("ERP Administrative Academic Year Closure", closure_id)
        rooms_out = []
        for row in doc.rooms or []:
            physical = frappe.db.get_value("ERP Administrative Room", row.room, "physical_code")
            ya_title = None
            if row.yearly_assignment_id:
                ya_title = frappe.db.get_value(
                    "ERP Administrative Room Yearly Assignment",
                    row.yearly_assignment_id,
                    "display_title_vn",
                )
            open_tc = _count_open_tickets_room(row.room)
            st = (row.status or "pending").lower()
            rej_note = None
            if st == "rejected" and row.inventory_check_id:
                rej_note = _inventory_rejection_note(row.inventory_check_id)
            rooms_out.append(
                {
                    "room": row.room,
                    "physical_code": physical,
                    "yearly_assignment_id": row.yearly_assignment_id,
                    "display_title_vn": ya_title,
                    "row_status": row.status,
                    "inventory_check_id": row.inventory_check_id,
                    "inventory_rejection_note": rej_note,
                    "last_reminder_sent_on": row.last_reminder_sent_on,
                    "open_ticket_count": open_tc,
                }
            )

        sy_title = _school_year_display_label(doc.school_year_id)
        return single_item_response(
            {
                "name": doc.name,
                "school_year_id": doc.school_year_id,
                "school_year_title": sy_title,
                "campus_id": doc.campus_id,
                "status": doc.status,
                "total_rooms": doc.total_rooms,
                "pending_inventory": doc.pending_inventory,
                "accepted_inventory": doc.accepted_inventory,
                "rejected_inventory": doc.rejected_inventory,
                "rooms": rooms_out,
            },
            "OK",
        )
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "academic_year_closure.get_closure_dashboard")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def send_reminder():
    """Nhắc nhở theo phòng: closure_id, room_ids (optional — mặc định tất cả pending)."""
    try:
        data = _parse_json_body()
        closure_id = (data.get("closure_id") or "").strip()
        room_ids = data.get("room_ids") or []
        if not closure_id or not frappe.db.exists("ERP Administrative Academic Year Closure", closure_id):
            return not_found_response(_("Không tìm thấy"))

        doc = frappe.get_doc("ERP Administrative Academic Year Closure", closure_id)
        now = frappe.utils.now()
        for row in doc.rooms or []:
            if room_ids and row.room not in room_ids:
                continue
            if (row.status or "") == "pending":
                row.last_reminder_sent_on = now
                _notify_closure_room_stub(closure_id, row.room, "reminder")
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        return success_response({"ok": True}, _("Đã ghi nhận nhắc (stub)"))
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "academic_year_closure.send_reminder")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def link_inventory_to_closure_row():
    """Gọi nội bộ hoặc từ submit_inventory: gắn inventory/handover vào dòng closure."""
    data = _parse_json_body()
    closure_id = (data.get("closure_id") or "").strip()
    room_id = (data.get("room_id") or "").strip()
    inventory_id = (data.get("inventory_check_id") or data.get("check_id") or "").strip()
    if not closure_id or not room_id or not inventory_id:
        return validation_error_response(_("Thiếu tham số"), {})

    doc = frappe.get_doc("ERP Administrative Academic Year Closure", closure_id)
    matched = False
    for row in doc.rooms or []:
        if _closure_room_row_matches(row.room, room_id):
            row.inventory_check_id = inventory_id
            row.status = "submitted"
            matched = True
            break
    if not matched:
        return validation_error_response(_("Không tìm thấy dòng phòng trong đợt"), {"room_id": ["no_row"]})
    _closure_refresh_counts(doc)
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return success_response({"ok": True}, "OK")


@frappe.whitelist(allow_guest=False)
def close_closure():
    """Đóng đợt chốt nếu mọi phòng đã accepted và không còn ticket mở (theo phòng trong đợt)."""
    try:
        data = _parse_json_body()
        closure_id = (data.get("closure_id") or "").strip()
        if not closure_id or not frappe.db.exists("ERP Administrative Academic Year Closure", closure_id):
            return not_found_response(_("Không tìm thấy"))

        doc = frappe.get_doc("ERP Administrative Academic Year Closure", closure_id)
        if doc.status == "closed":
            return single_item_response({"name": doc.name, "status": doc.status}, _("Đã đóng trước đó"))

        for row in doc.rooms or []:
            st = (row.status or "").lower()
            if st not in ("accepted", "closed"):
                return validation_error_response(
                    _("Còn phòng chưa hoàn tất kiểm kê."),
                    {"room": [row.room], "status": [st]},
                )
            if _count_open_tickets_room(row.room) > 0:
                return validation_error_response(
                    _("Còn ticket mở cho phòng {0}.").format(row.room),
                    {"room": [row.room], "tickets": ["open"]},
                )

        doc.status = "closed"
        doc.closed_on = frappe.utils.now()
        doc.closed_by = frappe.session.user
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        return single_item_response({"name": doc.name, "status": doc.status}, _("Đã đóng đợt chốt năm"))
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "academic_year_closure.close_closure")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def list_closures():
    """Danh sách đợt chốt (optional campus_id)."""
    try:
        data = _parse_json_body()
        campus_id = (data.get("campus_id") or "").strip()
        filters = {}
        if campus_id:
            filters["campus_id"] = campus_id
        rows = frappe.get_all(
            "ERP Administrative Academic Year Closure",
            filters=filters,
            fields=[
                "name",
                "school_year_id",
                "campus_id",
                "status",
                "total_rooms",
                "pending_inventory",
                "accepted_inventory",
                "started_on",
                "closed_on",
            ],
            order_by="creation desc",
            limit=50,
        )
        for row in rows:
            row["school_year_title"] = _school_year_display_label(row.get("school_year_id"))
        return list_response(rows, message="OK")
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "academic_year_closure.list_closures")
        return error_response(str(e))
