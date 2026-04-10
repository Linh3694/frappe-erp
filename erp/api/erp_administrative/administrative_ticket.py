# Copyright (c) 2026, Wellspring International School and contributors
# API: Ticket Hành chính (Frappe DocType ERP Administrative Ticket)

import json

import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime

from erp.utils.api_response import (
    error_response,
    forbidden_response,
    list_response,
    not_found_response,
    single_item_response,
    success_response,
    validation_error_response,
)

DOCTYPE = "ERP Administrative Ticket"
COMMENT_DOCTYPE = "ERP Administrative Ticket Comment"
SUBTASK_DOCTYPE = "ERP Administrative Ticket Sub Task"
HISTORY_DOCTYPE = "ERP Administrative Ticket History"

_STAFF_ROLES = ("System Manager", "SIS Administrative", "SIS BOD")


def _parse_json_body():
    """Đọc JSON từ request body."""
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


def _is_staff():
    roles = frappe.get_roles(frappe.session.user)
    return any(r in roles for r in _STAFF_ROLES)


def _user_dict(user_id):
    """Map User -> dict giống IT ticket (creator / assignedTo)."""
    if not user_id:
        return None
    row = frappe.db.get_value(
        "User",
        user_id,
        ["full_name", "email", "user_image"],
        as_dict=True,
    )
    if not row:
        return None
    dept = frappe.db.get_value("User", user_id, "department") or ""
    job = ""
    try:
        if frappe.get_meta("User").has_field("job_title"):
            job = frappe.db.get_value("User", user_id, "job_title") or ""
    except Exception:
        job = ""
    return {
        "_id": user_id,
        "fullname": row.get("full_name") or user_id,
        "email": row.get("email") or "",
        "avatarUrl": row.get("user_image") or "",
        "department": dept,
        "jobTitle": job,
    }


def _ticket_to_dict(doc, include_feedback=True):
    """Chuyển ERP Administrative Ticket -> payload frontend (tương thích IT ticket)."""
    cat_label = ""
    if doc.category:
        cat_label = frappe.db.get_value(
            "ERP Administrative Support Category", doc.category, "title"
        ) or doc.category

    creator = {
        "fullname": doc.creator_fullname or "",
        "email": doc.creator_email or "",
        "avatarUrl": doc.creator_avatar or "",
        "department": doc.creator_department or "",
        "jobTitle": "",
    }
    assigned = _user_dict(doc.assigned_to) if doc.assigned_to else None

    feedback = None
    if include_feedback and doc.status == "Closed" and (doc.feedback_rating or 0) > 0:
        badges = doc.feedback_badges
        if isinstance(badges, str):
            try:
                badges = json.loads(badges)
            except Exception:
                badges = []
        if not isinstance(badges, list):
            badges = []
        feedback = {
            "assignedTo": doc.assigned_to,
            "rating": doc.feedback_rating,
            "comment": doc.feedback_comment or "",
            "badges": badges,
        }

    attachment_url = doc.attachment or ""

    return {
        "_id": doc.name,
        "name": doc.name,
        "title": doc.title,
        "description": doc.description or "",
        "ticketCode": doc.ticket_code or doc.name,
        "status": doc.status,
        "priority": doc.priority or "Medium",
        "category": doc.category,
        "category_label": cat_label,
        "notes": doc.notes or "",
        "cancellationReason": doc.cancellation_reason or "",
        "creator": creator,
        "creatorEmail": doc.creator_email or "",
        "assignedTo": assigned,
        "feedback": feedback,
        "closedAt": doc.closed_at,
        "createdAt": doc.creation,
        "updatedAt": doc.modified,
        "acceptedAt": doc.accepted_at,
        "area_title": doc.area_title or "",
        "attachment": attachment_url,
    }


def _can_read_ticket(doc):
    if _is_staff():
        return True
    email = _session_email()
    if doc.creator_email and doc.creator_email == email:
        return True
    if doc.assigned_to == frappe.session.user:
        return True
    return False


def _append_history(ticket_id, action, user=None):
    user = user or frappe.session.user
    uemail = _session_email()
    ufn = frappe.db.get_value("User", user, "full_name") or user
    uav = frappe.db.get_value("User", user, "user_image") or ""
    row = frappe.get_doc(
        {
            "doctype": HISTORY_DOCTYPE,
            "ticket": ticket_id,
            "action": action,
            "user_email": uemail,
            "user_fullname": ufn,
            "user_avatar": uav,
        }
    )
    row.insert(ignore_permissions=True)


def _resolve_pic_from_assignment(category, area_title):
    """Tìm PIC theo danh mục + khu vực (nếu có)."""
    if not category:
        return None
    area_title = (area_title or "").strip()
    filters = {"support_category": category}
    rows = frappe.get_all(
        "ERP Administrative Support Assignment",
        filters=filters,
        fields=["pic", "area_title"],
    )
    if not rows:
        return None
    if area_title:
        for r in rows:
            if (r.area_title or "").strip() == area_title:
                return r.pic
    return rows[0].pic


@frappe.whitelist(allow_guest=False)
def get_ticket_categories():
    """Danh sách danh mục (Support Category) cho dropdown ticket."""
    try:
        rows = frappe.get_all(
            "ERP Administrative Support Category",
            fields=["name", "title"],
            order_by="title asc",
        )
        out = [{"value": r.name, "label": r.title} for r in rows]
        return success_response({"categories": out}, "OK")
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "administrative_ticket.get_ticket_categories")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def get_my_tickets():
    """Ticket do user hiện tại tạo."""
    try:
        email = _session_email()
        if not email:
            return validation_error_response(_("Chưa đăng nhập"), {"user": ["required"]})
        rows = frappe.get_all(
            DOCTYPE,
            filters={"creator_email": email},
            fields=["name"],
            order_by="creation desc",
        )
        tickets = []
        for r in rows:
            doc = frappe.get_doc(DOCTYPE, r.name)
            tickets.append(_ticket_to_dict(doc))
        return success_response({"tickets": tickets}, "OK")
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "administrative_ticket.get_my_tickets")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def get_all_tickets():
    """Tất cả ticket — chỉ staff HC / BOD / System Manager."""
    try:
        if not _is_staff():
            return forbidden_response(_("Không có quyền xem tất cả ticket"))
        rows = frappe.get_all(
            DOCTYPE,
            fields=["name"],
            order_by="creation desc",
        )
        tickets = []
        for r in rows:
            doc = frappe.get_doc(DOCTYPE, r.name)
            tickets.append(_ticket_to_dict(doc))
        return success_response({"tickets": tickets}, "OK")
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "administrative_ticket.get_all_tickets")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def get_ticket(ticket_id=None):
    """Chi tiết một ticket."""
    try:
        data = _parse_json_body()
        ticket_id = ticket_id or data.get("ticket_id") or data.get("name")
        if not ticket_id or not frappe.db.exists(DOCTYPE, ticket_id):
            return not_found_response(_("Không tìm thấy ticket"))
        doc = frappe.get_doc(DOCTYPE, ticket_id)
        if not _can_read_ticket(doc):
            return forbidden_response(_("Không có quyền xem ticket này"))
        return success_response(_ticket_to_dict(doc), "OK")
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "administrative_ticket.get_ticket")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def create_ticket():
    """Tạo ticket mới."""
    try:
        data = _parse_json_body()
        title = (data.get("title") or "").strip()
        description = (data.get("description") or "").strip()
        category = (data.get("category") or "").strip()
        if not title or not description or not category:
            return validation_error_response(
                _("Thiếu title, description hoặc category"),
                {"title": ["required"], "description": ["required"], "category": ["required"]},
            )
        if not frappe.db.exists("ERP Administrative Support Category", category):
            return validation_error_response(_("Danh mục không hợp lệ"), {"category": ["invalid"]})

        priority = (data.get("priority") or "Medium").strip()
        notes = (data.get("notes") or "").strip()
        area_title = (data.get("area_title") or "").strip()
        attachment = (data.get("attachment") or "").strip()

        email = _session_email()
        ufn = frappe.db.get_value("User", frappe.session.user, "full_name") or frappe.session.user
        uimg = frappe.db.get_value("User", frappe.session.user, "user_image") or ""
        udept = frappe.db.get_value("User", frappe.session.user, "department") or ""

        pic = _resolve_pic_from_assignment(category, area_title)

        doc = frappe.get_doc(
            {
                "doctype": DOCTYPE,
                "title": title,
                "description": description,
                "category": category,
                "priority": priority,
                "notes": notes,
                "area_title": area_title or None,
                "attachment": attachment or None,
                "status": "Open",
                "creator_email": email,
                "creator_fullname": ufn,
                "creator_avatar": uimg,
                "creator_department": udept,
            }
        )
        if pic:
            doc.assigned_to = pic
            pfn = frappe.db.get_value("User", pic, "full_name") or pic
            doc.assigned_to_fullname = pfn
            doc.status = "Assigned"
            doc.accepted_at = now_datetime()

        doc.insert(ignore_permissions=True)

        _append_history(doc.name, _("Tạo yêu cầu"))
        frappe.db.commit()

        return success_response(_ticket_to_dict(frappe.get_doc(DOCTYPE, doc.name)), "OK")
    except frappe.exceptions.ValidationError as e:
        return validation_error_response(str(e), {"error": [str(e)]})
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "administrative_ticket.create_ticket")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def update_ticket():
    """Cập nhật ticket (staff hoặc người tạo khi còn mở)."""
    try:
        data = _parse_json_body()
        ticket_id = data.get("ticket_id") or data.get("name")
        if not ticket_id or not frappe.db.exists(DOCTYPE, ticket_id):
            return not_found_response(_("Không tìm thấy ticket"))
        doc = frappe.get_doc(DOCTYPE, ticket_id)
        if not _can_read_ticket(doc):
            return forbidden_response(_("Không có quyền"))

        staff = _is_staff()
        email = _session_email()
        is_creator = doc.creator_email == email
        if not staff and not is_creator:
            return forbidden_response(_("Không có quyền sửa"))

        if not staff and doc.status in ("Closed", "Cancelled", "Resolved"):
            return validation_error_response(_("Không thể sửa ticket đã đóng"), {"status": ["locked"]})

        if "title" in data and data["title"]:
            doc.title = str(data["title"]).strip()
        if "description" in data:
            doc.description = str(data["description"] or "")
        if "category" in data and data["category"]:
            cat = str(data["category"]).strip()
            if frappe.db.exists("ERP Administrative Support Category", cat):
                doc.category = cat
        if "priority" in data and data["priority"]:
            doc.priority = str(data["priority"]).strip()
        if "notes" in data:
            doc.notes = str(data["notes"] or "")
        if "area_title" in data:
            doc.area_title = str(data["area_title"] or "").strip() or None
        if "attachment" in data:
            doc.attachment = str(data["attachment"] or "").strip() or None
        if staff and "status" in data and data["status"]:
            doc.status = str(data["status"]).strip()
        if staff and "assigned_to" in data:
            at = data.get("assigned_to")
            if at:
                doc.assigned_to = at
                doc.assigned_to_fullname = frappe.db.get_value("User", at, "full_name") or at
            else:
                doc.assigned_to = None
                doc.assigned_to_fullname = None

        doc.save(ignore_permissions=True)
        _append_history(doc.name, _("Cập nhật ticket"))
        frappe.db.commit()
        return success_response(_ticket_to_dict(frappe.get_doc(DOCTYPE, doc.name)), "OK")
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "administrative_ticket.update_ticket")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def delete_ticket():
    """Xóa ticket — chỉ staff."""
    try:
        if not _is_staff():
            return forbidden_response(_("Không có quyền xóa"))
        data = _parse_json_body()
        ticket_id = data.get("ticket_id") or data.get("name")
        if not ticket_id or not frappe.db.exists(DOCTYPE, ticket_id):
            return not_found_response(_("Không tìm thấy ticket"))
        frappe.delete_doc(DOCTYPE, ticket_id, ignore_permissions=True)
        frappe.db.commit()
        return success_response({"deleted": True}, "OK")
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "administrative_ticket.delete_ticket")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def assign_ticket():
    """Nhận ticket (gán cho user hiện tại)."""
    try:
        data = _parse_json_body()
        ticket_id = data.get("ticket_id") or data.get("name")
        if not ticket_id or not frappe.db.exists(DOCTYPE, ticket_id):
            return not_found_response(_("Không tìm thấy ticket"))
        doc = frappe.get_doc(DOCTYPE, ticket_id)
        if not _is_staff():
            return forbidden_response(_("Chỉ nhân viên HC mới nhận ticket"))
        uid = frappe.session.user
        doc.assigned_to = uid
        doc.assigned_to_fullname = frappe.db.get_value("User", uid, "full_name") or uid
        # Open → Assigned: lần nhận đầu (ticket chưa gán PIC).
        # Assigned → In Progress: ticket đã gán PIC / auto-Assigned — nhân viên nhấn "Nhận ticket" = bắt đầu xử lý thực sự.
        if doc.status == "Open":
            doc.status = "Assigned"
        elif doc.status == "Assigned":
            doc.status = "In Progress"
        doc.accepted_at = now_datetime()
        doc.save(ignore_permissions=True)
        _append_history(doc.name, _("Nhận xử lý ticket"))
        frappe.db.commit()
        return success_response(_ticket_to_dict(frappe.get_doc(DOCTYPE, doc.name)), "OK")
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "administrative_ticket.assign_ticket")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def cancel_ticket():
    """Hủy ticket."""
    try:
        data = _parse_json_body()
        ticket_id = data.get("ticket_id") or data.get("name")
        reason = (data.get("cancelReason") or data.get("cancellation_reason") or "").strip()
        if not ticket_id or not frappe.db.exists(DOCTYPE, ticket_id):
            return not_found_response(_("Không tìm thấy ticket"))
        doc = frappe.get_doc(DOCTYPE, ticket_id)
        email = _session_email()
        if doc.creator_email != email and not _is_staff():
            return forbidden_response(_("Không có quyền hủy"))
        if not reason:
            return validation_error_response(_("Thiếu lý do hủy"), {"cancelReason": ["required"]})
        doc.status = "Cancelled"
        doc.cancellation_reason = reason
        doc.save(ignore_permissions=True)
        _append_history(doc.name, _("Hủy ticket"))
        frappe.db.commit()
        return success_response(_ticket_to_dict(frappe.get_doc(DOCTYPE, doc.name)), "OK")
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "administrative_ticket.cancel_ticket")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def reopen_ticket():
    """Mở lại ticket."""
    try:
        data = _parse_json_body()
        ticket_id = data.get("ticket_id") or data.get("name")
        if not ticket_id or not frappe.db.exists(DOCTYPE, ticket_id):
            return not_found_response(_("Không tìm thấy ticket"))
        doc = frappe.get_doc(DOCTYPE, ticket_id)
        if not _can_read_ticket(doc):
            return forbidden_response(_("Không có quyền"))
        doc.status = "Open"
        doc.closed_at = None
        doc.feedback_rating = 0
        doc.feedback_comment = None
        doc.feedback_badges = None
        doc.save(ignore_permissions=True)
        _append_history(doc.name, _("Mở lại ticket"))
        frappe.db.commit()
        return success_response(_ticket_to_dict(frappe.get_doc(DOCTYPE, doc.name)), "OK")
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "administrative_ticket.reopen_ticket")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def accept_feedback():
    """Đánh giá và đóng ticket."""
    try:
        data = _parse_json_body()
        ticket_id = data.get("ticket_id") or data.get("name")
        rating = int(data.get("rating") or 0)
        comment = (data.get("comment") or "").strip()
        badges = data.get("badges") or []
        if not isinstance(badges, list):
            badges = []
        if not ticket_id or not frappe.db.exists(DOCTYPE, ticket_id):
            return not_found_response(_("Không tìm thấy ticket"))
        if rating < 1 or rating > 5:
            return validation_error_response(_("Điểm từ 1-5"), {"rating": ["invalid"]})
        doc = frappe.get_doc(DOCTYPE, ticket_id)
        email = _session_email()
        if doc.creator_email != email and not _is_staff():
            return forbidden_response(_("Chỉ người tạo mới đánh giá"))
        doc.feedback_rating = rating
        doc.feedback_comment = comment
        # JSON field không cho gán list trực tiếp (Frappe chỉ tự stringify dict)
        doc.feedback_badges = (
            json.dumps(badges, separators=(",", ":")) if badges else None
        )
        doc.status = "Closed"
        doc.closed_at = now_datetime()
        doc.save(ignore_permissions=True)
        _append_history(doc.name, _("Chấp nhận kết quả / đóng ticket"))
        frappe.db.commit()
        return success_response({"success": True}, "OK")
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "administrative_ticket.accept_feedback")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def get_subtasks():
    """Danh sách subtask."""
    try:
        data = _parse_json_body()
        ticket_id = data.get("ticket_id") or data.get("name")
        if not ticket_id or not frappe.db.exists(DOCTYPE, ticket_id):
            return not_found_response(_("Không tìm thấy ticket"))
        doc = frappe.get_doc(DOCTYPE, ticket_id)
        if not _can_read_ticket(doc):
            return forbidden_response(_("Không có quyền"))
        rows = frappe.get_all(
            SUBTASK_DOCTYPE,
            filters={"ticket": ticket_id},
            fields=["name"],
            order_by="creation asc",
        )
        out = []
        for r in rows:
            st = frappe.get_doc(SUBTASK_DOCTYPE, r.name)
            assignee = _user_dict(st.assigned_to) if st.assigned_to else None
            out.append(
                {
                    "_id": st.name,
                    "title": st.title,
                    "description": st.description or "",
                    "assignedTo": assignee,
                    "status": st.status,
                    "createdAt": st.creation,
                    "updatedAt": st.modified,
                }
            )
        return success_response({"subTasks": out}, "OK")
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "administrative_ticket.get_subtasks")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def create_subtask():
    """Tạo subtask."""
    try:
        data = _parse_json_body()
        ticket_id = data.get("ticket_id") or data.get("ticket")
        if not ticket_id or not frappe.db.exists(DOCTYPE, ticket_id):
            return not_found_response(_("Không tìm thấy ticket"))
        tdoc = frappe.get_doc(DOCTYPE, ticket_id)
        if not _can_read_ticket(tdoc):
            return forbidden_response(_("Không có quyền"))
        title = (data.get("title") or "").strip()
        if not title:
            return validation_error_response(_("Thiếu tiêu đề"), {"title": ["required"]})
        assigned_to = data.get("assigned_to") or data.get("assignedTo")
        pfn = ""
        if assigned_to:
            pfn = frappe.db.get_value("User", assigned_to, "full_name") or assigned_to
        st = frappe.get_doc(
            {
                "doctype": SUBTASK_DOCTYPE,
                "ticket": ticket_id,
                "title": title,
                "description": (data.get("description") or "").strip(),
                "assigned_to": assigned_to or None,
                "assigned_to_fullname": pfn,
                "status": (data.get("status") or "In Progress").strip(),
            }
        )
        st.insert(ignore_permissions=True)
        _append_history(ticket_id, _("Thêm công việc con"))
        frappe.db.commit()
        return success_response({"ticket": _ticket_to_dict(frappe.get_doc(DOCTYPE, ticket_id))}, "OK")
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "administrative_ticket.create_subtask")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def update_subtask():
    """Cập nhật trạng thái subtask."""
    try:
        data = _parse_json_body()
        ticket_id = data.get("ticket_id")
        sub_id = data.get("sub_task_id") or data.get("subTaskId")
        status = (data.get("status") or "").strip()
        if not sub_id or not frappe.db.exists(SUBTASK_DOCTYPE, sub_id):
            return not_found_response(_("Không tìm thấy subtask"))
        st = frappe.get_doc(SUBTASK_DOCTYPE, sub_id)
        tdoc = frappe.get_doc(DOCTYPE, st.ticket)
        if not _can_read_ticket(tdoc):
            return forbidden_response(_("Không có quyền"))
        if status:
            st.status = status
        st.save(ignore_permissions=True)
        frappe.db.commit()
        return success_response({"success": True}, "OK")
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "administrative_ticket.update_subtask")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def delete_subtask():
    """Xóa subtask."""
    try:
        data = _parse_json_body()
        sub_id = data.get("sub_task_id") or data.get("subTaskId")
        if not sub_id or not frappe.db.exists(SUBTASK_DOCTYPE, sub_id):
            return not_found_response(_("Không tìm thấy subtask"))
        st = frappe.get_doc(SUBTASK_DOCTYPE, sub_id)
        tid = st.ticket
        tdoc = frappe.get_doc(DOCTYPE, tid)
        if not _is_staff() and tdoc.assigned_to != frappe.session.user:
            return forbidden_response(_("Không có quyền"))
        frappe.delete_doc(SUBTASK_DOCTYPE, sub_id, ignore_permissions=True)
        frappe.db.commit()
        return success_response({"success": True}, "OK")
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "administrative_ticket.delete_subtask")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def get_comments():
    """Tin nhắn trao đổi (alias get_messages)."""
    try:
        data = _parse_json_body()
        ticket_id = data.get("ticket_id") or data.get("name")
        if not ticket_id or not frappe.db.exists(DOCTYPE, ticket_id):
            return not_found_response(_("Không tìm thấy ticket"))
        doc = frappe.get_doc(DOCTYPE, ticket_id)
        if not _can_read_ticket(doc):
            return forbidden_response(_("Không có quyền"))
        rows = frappe.get_all(
            COMMENT_DOCTYPE,
            filters={"ticket": ticket_id},
            fields=["name"],
            order_by="creation asc",
        )
        messages = []
        for r in rows:
            c = frappe.get_doc(COMMENT_DOCTYPE, r.name)
            sender = {
                "_id": c.sender_email or "",
                "fullname": c.sender_fullname or "",
                "email": c.sender_email or "",
                "avatarUrl": c.sender_avatar or "",
            }
            imgs = c.images_json
            if isinstance(imgs, str):
                try:
                    imgs = json.loads(imgs)
                except Exception:
                    imgs = []
            if not isinstance(imgs, list):
                imgs = []
            messages.append(
                {
                    "_id": c.name,
                    "sender": sender,
                    "text": c.text or "",
                    "timestamp": c.creation,
                    "type": c.message_type or "text",
                    "images": imgs,
                }
            )
        return success_response({"messages": messages, "success": True}, "OK")
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "administrative_ticket.get_comments")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def send_comment():
    """Gửi tin nhắn — text và/hoặc danh sách URL ảnh/video (FE upload qua upload_file trước, giống luồng IT)."""
    try:
        data = _parse_json_body()
        ticket_id = data.get("ticket_id") or data.get("name")
        text = (data.get("text") or "").strip()
        if not ticket_id or not frappe.db.exists(DOCTYPE, ticket_id):
            return not_found_response(_("Không tìm thấy ticket"))
        doc = frappe.get_doc(DOCTYPE, ticket_id)
        if not _can_read_ticket(doc):
            return forbidden_response(_("Không có quyền"))

        raw_images = data.get("images") or []
        if isinstance(raw_images, str):
            raw_images = [raw_images] if raw_images.strip() else []
        if not isinstance(raw_images, list):
            raw_images = []
        images = [str(u).strip() for u in raw_images if u]

        if not text and not images:
            return validation_error_response(_("Vui lòng nhập nội dung hoặc đính kèm ảnh/video"))

        email = _session_email()
        ufn = frappe.db.get_value("User", frappe.session.user, "full_name") or frappe.session.user
        uimg = frappe.db.get_value("User", frappe.session.user, "user_image") or ""

        if images and not text:
            msg_type = "image"
        else:
            msg_type = "text"

        row = {
            "doctype": COMMENT_DOCTYPE,
            "ticket": ticket_id,
            "sender_email": email,
            "sender_fullname": ufn,
            "sender_avatar": uimg,
            "text": text,
            "message_type": msg_type,
        }
        if images:
            row["images_json"] = images
        c = frappe.get_doc(row)
        c.insert(ignore_permissions=True)
        _append_history(ticket_id, _("Trao đổi"))
        frappe.db.commit()
        return success_response(
            {
                "success": True,
                "messageData": {
                    "_id": c.name,
                    "sender": {
                        "_id": email,
                        "fullname": ufn,
                        "email": email,
                        "avatarUrl": uimg,
                    },
                    "text": text,
                    "timestamp": c.creation,
                    "type": msg_type,
                    "images": images,
                },
            },
            "OK",
        )
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "administrative_ticket.send_comment")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def get_history():
    """Lịch sử xử lý."""
    try:
        data = _parse_json_body()
        ticket_id = data.get("ticket_id") or data.get("name")
        if not ticket_id or not frappe.db.exists(DOCTYPE, ticket_id):
            return not_found_response(_("Không tìm thấy ticket"))
        doc = frappe.get_doc(DOCTYPE, ticket_id)
        if not _can_read_ticket(doc):
            return forbidden_response(_("Không có quyền"))
        rows = frappe.get_all(
            HISTORY_DOCTYPE,
            filters={"ticket": ticket_id},
            fields=["name", "creation", "action", "user_email", "user_fullname", "user_avatar"],
            order_by="creation asc",
        )
        out = []
        for r in rows:
            out.append(
                {
                    "_id": r.name,
                    "timestamp": r.creation,
                    "action": r.action,
                    "user": {
                        "_id": r.user_email or "",
                        "fullname": r.user_fullname or "",
                        "email": r.user_email or "",
                        "avatarUrl": r.user_avatar or "",
                    },
                }
            )
        return success_response(out, "OK")
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "administrative_ticket.get_history")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def get_feedback_stats(email=None):
    """Thống kê đánh giá theo email PIC (ticket đã đóng có feedback)."""
    try:
        data = _parse_json_body()
        email = email or data.get("email")
        if not email:
            return validation_error_response(_("Thiếu email"), {"email": ["required"]})
        user_id = frappe.db.get_value("User", {"email": email}, "name")
        if not user_id:
            return success_response(
                {
                    "feedback": {
                        "averageRating": 0,
                        "totalFeedbacks": 0,
                        "badges": [],
                        "badgeCounts": {},
                    },
                    "summary": {"feedbackCount": 0},
                },
                "OK",
            )

        tickets = frappe.get_all(
            DOCTYPE,
            filters={"assigned_to": user_id, "status": "Closed", "feedback_rating": [">", 0]},
            fields=["feedback_rating", "feedback_badges"],
        )
        if not tickets:
            return success_response(
                {
                    "feedback": {
                        "averageRating": 0,
                        "totalFeedbacks": 0,
                        "badges": [],
                        "badgeCounts": {},
                    },
                    "summary": {"feedbackCount": 0},
                },
                "OK",
            )

        ratings = [t.feedback_rating for t in tickets]
        avg = sum(ratings) / len(ratings)
        badge_counts = {}
        for t in tickets:
            bd = t.feedback_badges
            if isinstance(bd, str) and bd:
                try:
                    bd = json.loads(bd)
                except Exception:
                    bd = []
            if isinstance(bd, list):
                for b in bd:
                    badge_counts[b] = badge_counts.get(b, 0) + 1

        all_badges = list(badge_counts.keys())
        return success_response(
            {
                "feedback": {
                    "averageRating": round(avg, 2),
                    "totalFeedbacks": len(tickets),
                    "badges": all_badges,
                    "badgeCounts": badge_counts,
                },
                "summary": {"feedbackCount": len(tickets)},
            },
            "OK",
        )
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "administrative_ticket.get_feedback_stats")
        return error_response(str(e))


# Alias theo tên camelCase (frontend)
getTicket = get_ticket
getAllTickets = get_all_tickets
getMyTickets = get_my_tickets
