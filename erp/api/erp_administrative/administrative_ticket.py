# Copyright (c) 2026, Wellspring International School and contributors
# API: Ticket Hành chính (Frappe DocType ERP Administrative Ticket)

import json

import frappe
from frappe import _
from frappe.utils import cint, get_datetime, now_datetime, today

from erp.api.erp_administrative.room_activity_log import log_room_activity
from erp.utils.api_response import (
    error_response,
    forbidden_response,
    list_response,
    not_found_response,
    single_item_response,
    success_response,
    validation_error_response,
)
from erp.utils.campus_utils import get_current_campus_from_context

DOCTYPE = "ERP Administrative Ticket"
COMMENT_DOCTYPE = "ERP Administrative Ticket Comment"
SUBTASK_DOCTYPE = "ERP Administrative Ticket Sub Task"
HISTORY_DOCTYPE = "ERP Administrative Ticket History"

_STAFF_ROLES = ("System Manager", "SIS Administrative", "SIS BOD")

# Danh mục cố định — tên Doc ERP Administrative Support Category (đồng bộ frontend)
EVENT_FACILITY_CATEGORY_NAME = "__event_facility__"


def _normalize_related_student_ids(raw):
    """Chuẩn hoá danh sách student_id từ JSON / list."""
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return []
    if not isinstance(raw, list):
        return []
    return [str(x).strip() for x in raw if x]


def _normalize_related_equipment_ids(raw):
    """Chuẩn hoá mảng name dòng CSVC (ERP Administrative Room Facility Equipment)."""
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return []
    if not isinstance(raw, list):
        return []
    seen = set()
    out = []
    for x in raw:
        s = str(x).strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _json_list_field_for_db(items):
    """Ghi list vào cột JSON: Frappe base_document từ chối list thuần — chỉ dict được xử lý đặc biệt."""
    if not items:
        return None
    return json.dumps(items, separators=(",", ":"))


def _merge_equipment_ids_from_payload(data):
    """Gộp related_equipment_ids + related_equipment_id; id đơn (nếu có) đứng đầu — tương thích API cũ."""
    eq_ids = _normalize_related_equipment_ids(data.get("related_equipment_ids"))
    rel_single = (data.get("related_equipment_id") or "").strip()
    if rel_single:
        eq_ids = [rel_single] + [x for x in eq_ids if x != rel_single]
    return eq_ids


def _related_equipment_ids_resolved(doc):
    """Mảng id CSVC từ doc đã lưu (JSON + fallback Link đơn)."""
    ids = _normalize_related_equipment_ids(getattr(doc, "related_equipment_ids", None))
    rel = (getattr(doc, "related_equipment_id", None) or "").strip()
    if not ids and rel:
        return [rel]
    if rel and rel not in ids:
        return [rel] + ids
    return ids


def _validate_related_equipment_belongs_to_room(equipment_line_id, room_ref):
    """Đảm bảo dòng thiết bị CSVC thuộc đúng phòng (ERP Administrative Room name)."""
    if not equipment_line_id or not room_ref:
        return True
    r = frappe.db.get_value(
        "ERP Administrative Room Facility Equipment", equipment_line_id, "room"
    )
    return (r or "").strip() == (room_ref or "").strip()


def _ticket_log_room_repair_activity(doc, activity_type):
    """Ghi Room Activity Log khi ticket có phòng / thiết bị gắn phòng."""
    room_id = None
    if cint(getattr(doc, "is_event_facility", 0)):
        room_id = (getattr(doc, "event_room_id", None) or "").strip()
    else:
        room_id = (getattr(doc, "room_id", None) or "").strip()
    if not room_id:
        eq_ids = _related_equipment_ids_resolved(doc)
        if eq_ids:
            room_id = frappe.db.get_value(
                "ERP Administrative Room Facility Equipment",
                eq_ids[0],
                "room",
            )
        elif getattr(doc, "related_equipment_id", None):
            room_id = frappe.db.get_value(
                "ERP Administrative Room Facility Equipment",
                doc.related_equipment_id,
                "room",
            )
    if not room_id:
        return
    sy = _active_school_year_id_api()
    try:
        log_room_activity(
            room_id,
            activity_type,
            user=frappe.session.user,
            reference_doctype=DOCTYPE,
            reference_name=doc.name,
            note=(getattr(doc, "title", None) or "")[:500],
            school_year_id=sy,
            activity_date=today(),
        )
    except Exception:
        frappe.log_error(frappe.get_traceback(), "administrative_ticket._ticket_log_room_repair_activity")


def _active_school_year_id_api(explicit=None):
    """Năm học đang bật (is_enable) hoặc giá trị truyền vào."""
    sy = (explicit or "").strip()
    if sy and frappe.db.exists("SIS School Year", sy):
        return sy
    return frappe.db.get_value(
        "SIS School Year",
        {"is_enable": 1},
        "name",
        order_by="start_date desc",
    )


def _resolve_campus_id_api(explicit=None):
    """Campus từ tham số hoặc ngữ cảnh user."""
    cid = (explicit or "").strip()
    if cid and frappe.db.exists("SIS Campus", cid):
        return cid
    return get_current_campus_from_context()


def _ensure_event_facility_support_category():
    """Tạo danh mục CSVC sự kiện (name cố định) nếu chưa có — dùng rename sau insert vì autoname series."""
    if frappe.db.exists("ERP Administrative Support Category", EVENT_FACILITY_CATEGORY_NAME):
        return EVENT_FACILITY_CATEGORY_NAME
    doc = frappe.get_doc(
        {
            "doctype": "ERP Administrative Support Category",
            "title": "Yêu cầu cơ sở vật chất cho sự kiện",
            "ticket_code_prefix": "EVT",
        }
    )
    doc.insert(ignore_permissions=True)
    if doc.name != EVENT_FACILITY_CATEGORY_NAME:
        frappe.rename_doc(
            "ERP Administrative Support Category",
            doc.name,
            EVENT_FACILITY_CATEGORY_NAME,
            force=True,
            merge=False,
        )
    frappe.db.commit()
    return EVENT_FACILITY_CATEGORY_NAME


def _ensure_administrative_ticket_upload_folder():
    """
    Tạo File folder Home/AdministrativeTicket nếu chưa có.
    upload_file (mobile/web) ghi folder này — thiếu folder gây LinkValidationError khi gửi ảnh trong chat.
    """
    try:
        if frappe.db.exists(
            "File",
            {"is_folder": 1, "file_name": "AdministrativeTicket", "folder": "Home"},
        ):
            return
        frappe.get_doc(
            {
                "doctype": "File",
                "file_name": "AdministrativeTicket",
                "is_folder": 1,
                "folder": "Home",
            }
        ).insert(ignore_permissions=True)
        frappe.db.commit()
    except Exception:
        frappe.db.rollback()
        frappe.log_error(
            frappe.get_traceback(),
            "administrative_ticket._ensure_administrative_ticket_upload_folder",
        )


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

    event_building_label = ""
    event_room_label = ""
    if getattr(doc, "event_building_id", None):
        event_building_label = frappe.db.get_value(
            "ERP Administrative Building", doc.event_building_id, "title_vn"
        ) or doc.event_building_id
    if getattr(doc, "event_room_id", None):
        event_room_label = frappe.db.get_value(
            "ERP Administrative Room", doc.event_room_id, "title_vn"
        ) or doc.event_room_id

    # Phòng (ticket thường), thiết bị & học sinh liên quan
    room_id_val = getattr(doc, "room_id", None) or ""
    room_label_nf = ""
    if room_id_val:
        room_label_nf = frappe.db.get_value(
            "ERP Administrative Room", room_id_val, "title_vn"
        ) or room_id_val

    related_equipment_ids = _related_equipment_ids_resolved(doc)
    rel_eq = related_equipment_ids[0] if related_equipment_ids else (
        getattr(doc, "related_equipment_id", None) or ""
    )
    related_equipments = []
    label_parts = []
    for eq_id in related_equipment_ids:
        cat = frappe.db.get_value(
            "ERP Administrative Room Facility Equipment", eq_id, "category"
        )
        ct = (
            frappe.db.get_value(
                "ERP Administrative Facility Equipment Category", cat, "title"
            )
            if cat
            else None
        )
        related_equipments.append({"name": eq_id, "category_title": (ct or "")})
        label_parts.append((ct or eq_id))
    related_equipment_label = ", ".join(label_parts) if label_parts else ""

    related_student_ids = getattr(doc, "related_student_ids", None)
    if isinstance(related_student_ids, str):
        try:
            related_student_ids = json.loads(related_student_ids)
        except Exception:
            related_student_ids = []
    if not isinstance(related_student_ids, list):
        related_student_ids = []

    related_students_detail = []
    photo_map_rs = {}
    if related_student_ids:
        sids = [str(x).strip() for x in related_student_ids if x]
        for sid in sids:
            st = frappe.db.get_value(
                "CRM Student",
                sid,
                ["student_name", "student_code"],
                as_dict=True,
            )
            if st:
                related_students_detail.append(
                    {
                        "student_id": sid,
                        "student_name": st.get("student_name") or "",
                        "student_code": st.get("student_code") or "",
                        "avatar_url": "",
                    }
                )
        if sids:
            sy_for_photo = frappe.db.get_value(
                "SIS School Year",
                {"is_enable": 1},
                "name",
                order_by="start_date desc",
            )
            photos = frappe.db.sql(
                """
                SELECT student_id, photo, school_year_id, upload_date, creation
                FROM `tabSIS Photo`
                WHERE student_id IN %(sids)s
                  AND type = 'student'
                  AND status = 'Active'
                ORDER BY student_id,
                    CASE WHEN school_year_id = %(sy)s THEN 0 ELSE 1 END,
                    upload_date DESC,
                    creation DESC
                """,
                {"sids": tuple(sids), "sy": sy_for_photo or ""},
                as_dict=True,
            )
            for p in photos:
                sid = p.get("student_id")
                if sid and sid not in photo_map_rs and p.get("photo"):
                    url = p.get("photo")
                    if url and not str(url).startswith("http"):
                        if str(url).startswith("/files/"):
                            url = frappe.utils.get_url(url)
                        else:
                            url = frappe.utils.get_url("/files/" + str(url))
                    photo_map_rs[sid] = url or ""
            for row in related_students_detail:
                sid = row.get("student_id")
                if sid and sid in photo_map_rs:
                    row["avatar_url"] = photo_map_rs[sid]

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
        "is_event_facility": bool(cint(getattr(doc, "is_event_facility", 0))),
        "event_building_id": getattr(doc, "event_building_id", None) or "",
        "event_building_label": event_building_label,
        "event_room_id": getattr(doc, "event_room_id", None) or "",
        "event_room_label": event_room_label,
        "event_start_time": getattr(doc, "event_start_time", None),
        "event_end_time": getattr(doc, "event_end_time", None),
        "room_id": room_id_val,
        "room_label": room_label_nf,
        "related_equipment_id": rel_eq,
        "related_equipment_label": related_equipment_label,
        "related_equipment_ids": related_equipment_ids,
        "related_equipments": related_equipments,
        "related_student_ids": related_student_ids,
        "related_students": related_students_detail,
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


def _append_history(ticket_id, action, user=None, detail=None):
    """Ghi lịch sử; detail = nội dung phụ (trao đổi, tiêu đề CV con, lý do hủy...)."""
    user = user or frappe.session.user
    uemail = _session_email()
    ufn = frappe.db.get_value("User", user, "full_name") or user
    uav = frappe.db.get_value("User", user, "user_image") or ""
    detail_clean = (detail or "").strip()
    row = frappe.get_doc(
        {
            "doctype": HISTORY_DOCTYPE,
            "ticket": ticket_id,
            "action": action,
            "detail": detail_clean or None,
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


def _team_leader_emails_for_category(category_name):
    """Email (User) của team leader danh mục CSVC — dùng khi chưa auto-gán PIC."""
    if not category_name or not frappe.db.exists("ERP Administrative Support Category", category_name):
        return []
    cat = frappe.get_doc("ERP Administrative Support Category", category_name)
    out = []
    for row in cat.get("team_leaders") or []:
        u = (getattr(row, "user", None) or "").strip()
        if u and u not in out:
            out.append(u)
    return out


def _hc_normalize_base_url(raw):
    """frontend_url đôi khi là str hoặc list trong site_config — chuẩn hoá về một chuỗi."""
    if raw is None:
        return ""
    if isinstance(raw, (list, tuple)):
        for x in raw:
            s = _hc_normalize_base_url(x)
            if s:
                return s
        return ""
    return str(raw).strip()


def _hc_frontend_base_url():
    """Base URL frontend SIS (site_config frontend_url)."""
    u = _hc_normalize_base_url(frappe.conf.get("frontend_url")) or _hc_normalize_base_url(
        frappe.get_site_config().get("frontend_url")
    )
    return u.rstrip("/") if u else ""


def _hc_category_label(doc):
    """Tiêu đề danh mục hiển thị trong email."""
    c = getattr(doc, "category", None)
    if not c:
        return ""
    t = frappe.db.get_value("ERP Administrative Support Category", c, "title")
    return (t or c or "").strip()


def _hc_ticket_url_for_recipient(doc, recipient_email):
    """Người tạo → màn ứng dụng; PIC/staff → màn operation."""
    base = _hc_frontend_base_url()
    if not base:
        return ""
    rec = (recipient_email or "").strip().lower()
    creator = (doc.creator_email or "").strip().lower()
    tid = doc.name
    if rec == creator:
        return f"{base}/applications/ticket/administrative/view/{tid}"
    return f"{base}/operation/administrative-ticket/view/{tid}"


def _hc_administrative_ticket_email_enabled():
    """
    Có gửi email ticket HC qua email-service hay không.
    - Mặc định: bật trên mọi môi trường (kể cả production).
    - Tắt khi cần: site_config administrative_ticket_email_enabled = false
    """
    site = frappe.get_site_config()
    forced = site.get("administrative_ticket_email_enabled")
    if forced is False:
        return False
    return True


def _hc_post_ticket_email(payload):
    """Gửi email qua email-service (POST /notify-administrative-ticket)."""
    if not _hc_administrative_ticket_email_enabled():
        return
    try:
        import requests

        base = (frappe.conf.get("email_service_url") or "http://localhost:5030").rstrip("/")
        url = f"{base}/notify-administrative-ticket"
        r = requests.post(
            url,
            json=payload,
            timeout=20,
            headers={"Content-Type": "application/json"},
        )
        if r.status_code >= 400:
            frappe.logger().error(
                f"administrative_ticket: email HTTP {r.status_code}: {(r.text or '')[:800]}"
            )
    except Exception as ex:
        frappe.logger().error(f"administrative_ticket: email request failed: {ex}")


def _notify_new_admin_ticket_mobile(doc):
    """
    Push Expo cho PIC / team leader khi có ticket HC mới.
    Payload khớp mobile: type=ticket + action=new_ticket_admin → kênh ticket + sound ticket_create.wav (như Ticket IT).
    """
    try:
        from erp.api.erp_sis.mobile_push_notification import send_mobile_notification_persisted
    except Exception as e:
        frappe.logger().warning(f"administrative_ticket: không import send_mobile_notification_persisted: {e}")
        return

    creator = (doc.creator_email or "").strip()
    recipients = []
    if getattr(doc, "assigned_to", None):
        recipients.append(doc.assigned_to)
    else:
        recipients.extend(_team_leader_emails_for_category(doc.category))

    title = _("Ticket hành chính mới")
    code = (doc.ticket_code or doc.name or "").strip()
    t = (doc.title or "").strip() or code
    body = _("{0}: {1}").format(code, t)

    data = {
        "type": "ticket",
        "action": "new_ticket_admin",
        "ticket_kind": "administrative",
        "ticketId": doc.name,
        "ticket_id": doc.name,
        "ticketCode": code,
    }

    seen = set()
    for user_email in recipients:
        if not user_email or user_email in seen:
            continue
        if user_email == creator:
            continue
        seen.add(user_email)
        try:
            send_mobile_notification_persisted(
                user_email,
                title,
                body,
                data,
                erp_notification_type="ticket",
                reference_doctype=DOCTYPE,
                reference_name=doc.name,
            )
        except Exception as ex:
            frappe.logger().error(f"administrative_ticket: push failed {user_email}: {ex}")


def _hc_user_email(user_id):
    """Lấy email User (name có thể trùng email đăng nhập)."""
    if not user_id:
        return None
    em = frappe.db.get_value("User", user_id, "email")
    return (em or user_id or "").strip()


def _hc_send_ticket_email(doc, event_type, recipient_email, extra=None):
    """Gửi email thông báo HC qua email-service (template tối giản)."""
    if not recipient_email or not (recipient_email or "").strip():
        return
    extra = extra or {}
    code = (doc.ticket_code or doc.name or "").strip()
    t = (doc.title or "").strip() or code
    creator_fn = (getattr(doc, "creator_fullname", None) or "").strip() or (
        doc.creator_email or ""
    ).strip()
    desc = (getattr(doc, "description", None) or "") or ""
    desc_snippet = desc if len(desc) <= 400 else (desc[:400] + "…")
    created_at = ""
    try:
        if doc.creation:
            from frappe.utils import format_datetime

            created_at = format_datetime(doc.creation, "dd/MM/yyyy HH:mm")
    except Exception:
        created_at = str(doc.creation or "")

    creator_em = (getattr(doc, "creator_email", None) or "").strip()
    payload = {
        "eventType": event_type,
        "recipientEmail": (recipient_email or "").strip(),
        # email-service: bật khối English khi recipient == creator (user); PIC/HC chỉ TV
        "creatorEmail": creator_em,
        "ticketUrl": _hc_ticket_url_for_recipient(doc, recipient_email),
        "ticketCode": code,
        "title": t,
        "categoryLabel": _hc_category_label(doc),
        "creatorName": creator_fn,
        "descriptionSnippet": desc_snippet,
        "status": getattr(doc, "status", None) or "",
        "createdAt": created_at,
    }
    payload.update(extra)
    _hc_post_ticket_email(payload)


def _hc_send_emails_on_ticket_create(doc):
    """Xác nhận cho người tạo + thông báo ticket mới cho PIC/leader (cùng logic push)."""
    creator = (doc.creator_email or "").strip()
    if creator:
        try:
            _hc_send_ticket_email(doc, "ticket_creation_confirmation", creator, {})
        except Exception as ex:
            frappe.logger().error(f"administrative_ticket: email create confirm {ex}")

    recipients = []
    if getattr(doc, "assigned_to", None):
        em = _hc_user_email(doc.assigned_to)
        if em:
            recipients.append(em)
    else:
        recipients.extend(_team_leader_emails_for_category(doc.category))

    seen = set()
    for em in recipients:
        em = (em or "").strip()
        if not em or em in seen or em == creator:
            continue
        seen.add(em)
        try:
            _hc_send_ticket_email(doc, "new_ticket", em, {})
        except Exception as ex:
            frappe.logger().error(f"administrative_ticket: email new ticket {em}: {ex}")


def _hc_ticket_payload(doc, action, extra=None):
    """Payload mobile + ERP — khớp NotificationsScreen (action + ticket_kind administrative)."""
    code = (doc.ticket_code or doc.name or "").strip()
    d = {
        "type": "ticket",
        "action": action,
        "ticket_kind": "administrative",
        "ticketId": doc.name,
        "ticket_id": doc.name,
        "ticketCode": code,
    }
    if extra:
        d.update(extra)
    return d


def _hc_send_persisted(recipient_email, title, body, data, exclude_email=None):
    """Gửi ERP Notification + Expo; bỏ qua người gửi."""
    if not recipient_email:
        return
    if exclude_email and recipient_email.strip() == (exclude_email or "").strip():
        return
    try:
        from erp.api.erp_sis.mobile_push_notification import send_mobile_notification_persisted

        tid = data.get("ticketId") or data.get("ticket_id")
        send_mobile_notification_persisted(
            recipient_email,
            title,
            body,
            data,
            erp_notification_type="ticket",
            reference_doctype=DOCTYPE,
            reference_name=tid,
        )
    except Exception as ex:
        frappe.logger().error(f"administrative_ticket: HC notify failed {recipient_email}: {ex}")


def _notify_hc_user_reply(doc, sender_email):
    """Người tạo nhắn → PIC; PIC/Staff nhắn → người tạo (tương đương IT user_reply)."""
    sender = (sender_email or "").strip()
    creator = (doc.creator_email or "").strip()
    if not sender:
        return
    code = (doc.ticket_code or doc.name or "").strip()
    t = (doc.title or "").strip() or code

    if sender == creator and doc.assigned_to:
        rec = _hc_user_email(doc.assigned_to)
        if rec and rec != sender:
            d = _hc_ticket_payload(doc, "user_reply")
            _hc_send_persisted(
                rec,
                _("Ticket hành chính: tin nhắn mới"),
                _("{0} có phản hồi mới: {1}").format(code, t),
                d,
                exclude_email=sender,
            )
            try:
                _hc_send_ticket_email(doc, "user_reply", rec, {})
            except Exception as ex:
                frappe.logger().error(f"administrative_ticket: email user_reply {rec}: {ex}")
    elif sender != creator and creator:
        d = _hc_ticket_payload(doc, "user_reply")
        _hc_send_persisted(
            creator,
            _("Ticket hành chính: tin nhắn mới"),
            _("Có tin nhắn mới về {0}: {1}").format(code, t),
            d,
            exclude_email=sender,
        )
        try:
            _hc_send_ticket_email(doc, "user_reply", creator, {})
        except Exception as ex:
            frappe.logger().error(f"administrative_ticket: email user_reply creator: {ex}")


def _notify_hc_status_changed(doc, old_status, new_status, actor_email):
    """Đổi trạng thái — thông báo người tạo + PIC (trừ người thao tác)."""
    if old_status == new_status:
        return
    data = _hc_ticket_payload(
        doc,
        "ticket_status_changed",
        {"oldStatus": old_status, "newStatus": new_status},
    )
    title = _("Cập nhật trạng thái ticket HC")
    code = (doc.ticket_code or doc.name or "").strip()
    body = _("{0}: {1} → {2}").format(code, old_status, new_status)
    actor = (actor_email or "").strip()
    recipients = []
    ce = (doc.creator_email or "").strip()
    ae = _hc_user_email(doc.assigned_to)
    if ce and ce != actor:
        recipients.append(ce)
    if ae and ae != actor and ae not in recipients:
        recipients.append(ae)
    for r in recipients:
        _hc_send_persisted(r, title, body, data, exclude_email=actor)
        try:
            _hc_send_ticket_email(
                doc,
                "ticket_status_changed",
                r,
                {"oldStatus": old_status, "newStatus": new_status, "actorName": actor or ""},
            )
        except Exception as ex:
            frappe.logger().error(f"administrative_ticket: email status {r}: {ex}")


def _notify_hc_assignment_changed(doc, old_assignee, new_assignee, actor_email):
    """Gán / đổi PIC — thông báo PIC mới (giống IT ticket_assigned)."""
    if old_assignee == new_assignee or not new_assignee:
        return
    data = _hc_ticket_payload(doc, "ticket_assigned")
    ne = _hc_user_email(new_assignee)
    actor = (actor_email or "").strip()
    code = (doc.ticket_code or doc.name or "").strip()
    t = (doc.title or "").strip() or code
    if ne and ne != actor:
        _hc_send_persisted(
            ne,
            _("Ticket hành chính được gán cho bạn"),
            _("{0}: {1}").format(code, t),
            data,
            exclude_email=actor,
        )
        try:
            _hc_send_ticket_email(
                doc, "ticket_assigned", ne, {"actorName": (actor or "").strip()}
            )
        except Exception as ex:
            frappe.logger().error(f"administrative_ticket: email assign {ne}: {ex}")


def _notify_hc_ticket_pickup(doc):
    """Staff nhấn Nhận ticket — báo người tạo."""
    creator = (doc.creator_email or "").strip()
    actor = _session_email()
    if not creator or creator == actor:
        return
    data = _hc_ticket_payload(doc, "ticket_assigned")
    code = (doc.ticket_code or doc.name or "").strip()
    t = (doc.title or "").strip() or code
    ufn = frappe.db.get_value("User", frappe.session.user, "full_name") or frappe.session.user
    _hc_send_persisted(
        creator,
        _("Ticket HC đã được nhận xử lý"),
        _("{0} đang được xử lý bởi {1}. {2}").format(code, ufn, t),
        data,
        exclude_email=actor,
    )
    try:
        _hc_send_ticket_email(doc, "ticket_pickup", creator, {"actorName": ufn})
    except Exception as ex:
        frappe.logger().error(f"administrative_ticket: email pickup: {ex}")


def _notify_hc_cancelled(doc, actor_email):
    """Hủy ticket — báo bên còn lại."""
    data = _hc_ticket_payload(doc, "ticket_cancelled")
    actor = (actor_email or "").strip()
    code = (doc.ticket_code or doc.name or "").strip()
    t = (doc.title or "").strip() or code
    body = _("Ticket {0} đã bị hủy: {1}").format(code, t)
    title = _("Ticket HC đã hủy")
    for em in ((doc.creator_email or "").strip(), _hc_user_email(doc.assigned_to)):
        if em and em != actor:
            _hc_send_persisted(em, title, body, data, exclude_email=actor)
            try:
                _hc_send_ticket_email(doc, "ticket_cancelled", em, {"actorName": actor or ""})
            except Exception as ex:
                frappe.logger().error(f"administrative_ticket: email cancel {em}: {ex}")


def _notify_hc_reopened(doc, actor_email):
    """Mở lại ticket — báo PIC + người tạo (trừ người thao tác)."""
    data = _hc_ticket_payload(
        doc,
        "ticket_status_changed",
        {"oldStatus": _("Đóng/Kết thúc"), "newStatus": "Open"},
    )
    title = _("Ticket HC được mở lại")
    code = (doc.ticket_code or doc.name or "").strip()
    t = (doc.title or "").strip() or code
    body = _("{0} đã được mở lại: {1}").format(code, t)
    actor = (actor_email or "").strip()
    for em in ((doc.creator_email or "").strip(), _hc_user_email(doc.assigned_to)):
        if em and em != actor:
            _hc_send_persisted(em, title, body, data, exclude_email=actor)
            try:
                _hc_send_ticket_email(doc, "ticket_reopened", em, {"actorName": actor or ""})
            except Exception as ex:
                frappe.logger().error(f"administrative_ticket: email reopen {em}: {ex}")


def _notify_hc_feedback_received(doc, actor_email):
    """Người tạo đánh giá đóng ticket — báo PIC (ticket_feedback_received)."""
    pic = _hc_user_email(doc.assigned_to)
    actor = (actor_email or "").strip()
    if not pic or pic == actor:
        return
    rating = int(getattr(doc, "feedback_rating", 0) or 0)
    data = _hc_ticket_payload(
        doc,
        "ticket_feedback_received",
        {"rating": rating},
    )
    code = (doc.ticket_code or doc.name or "").strip()
    title = _("Đánh giá ticket HC")
    body = _("{0}: {1} sao").format(code, rating)
    _hc_send_persisted(pic, title, body, data, exclude_email=actor)
    try:
        _hc_send_ticket_email(
            doc,
            "ticket_feedback_received",
            pic,
            {"rating": rating, "actorName": actor or ""},
        )
    except Exception as ex:
        frappe.logger().error(f"administrative_ticket: email feedback: {ex}")


@frappe.whitelist(allow_guest=False)
def get_ticket_categories():
    """Danh sách danh mục (Support Category) cho dropdown ticket."""
    try:
        _ensure_administrative_ticket_upload_folder()
        _ensure_event_facility_support_category()
        rows = frappe.get_all(
            "ERP Administrative Support Category",
            fields=["name", "title", "ticket_code_prefix"],
            order_by="title asc",
        )
        out = [
            {
                "value": r.name,
                "label": r.title,
                "ticket_code_prefix": (r.ticket_code_prefix or "").strip(),
            }
            for r in rows
        ]
        return success_response({"categories": out}, "OK")
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "administrative_ticket.get_ticket_categories")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def get_my_tickets():
    """Ticket do user hiện tại tạo."""
    try:
        _ensure_administrative_ticket_upload_folder()
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
        _ensure_administrative_ticket_upload_folder()
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
        _ensure_administrative_ticket_upload_folder()
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
def get_rooms_by_building(building_id=None):
    """Danh sách phòng theo tòa nhà (ERP Administrative Room)."""
    try:
        data = _parse_json_body()
        building_id = building_id or data.get("building_id")
        building_id = (building_id or "").strip()
        if not building_id:
            return validation_error_response(_("Thiếu building_id"), {"building_id": ["required"]})
        if not frappe.db.exists("ERP Administrative Building", building_id):
            return validation_error_response(_("Tòa nhà không tồn tại"), {"building_id": ["invalid"]})
        rooms = frappe.get_all(
            "ERP Administrative Room",
            filters={"building_id": building_id},
            fields=["name", "title_vn", "title_en", "short_title", "room_type", "capacity"],
            order_by="title_vn asc",
        )
        return success_response({"rooms": rooms}, "OK")
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "administrative_ticket.get_rooms_by_building")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def get_room_equipment_for_ticket(room_id=None):
    """Danh sách thiết bị CSVC theo phòng — dùng form ticket."""
    try:
        data = _parse_json_body()
        room_id = room_id or data.get("room_id")
        room_id = (room_id or "").strip()
        if not room_id:
            return validation_error_response(_("Thiếu room_id"), {"room_id": ["required"]})
        if not frappe.db.exists("ERP Administrative Room", room_id):
            return not_found_response(_("Không tìm thấy phòng"))

        rows = frappe.get_all(
            "ERP Administrative Room Facility Equipment",
            filters={"room": room_id},
            fields=["name"],
            order_by="creation asc",
        )
        out = []
        for r in rows:
            doc = frappe.get_doc("ERP Administrative Room Facility Equipment", r.name)
            cat_title = frappe.db.get_value(
                "ERP Administrative Facility Equipment Category", doc.category, "title"
            )
            cat_type = frappe.db.get_value(
                "ERP Administrative Facility Equipment Category", doc.category, "equipment_type"
            )
            out.append(
                {
                    "name": doc.name,
                    "room": doc.room,
                    "category": doc.category,
                    "category_title": cat_title,
                    "equipment_type": cat_type,
                    "quantity": doc.quantity,
                    "condition": doc.condition or "",
                }
            )
        return success_response({"equipment": out}, "OK")
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "administrative_ticket.get_room_equipment_for_ticket")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def get_students_by_room(room_id=None, school_year_id=None, campus_id=None):
    """Học sinh theo phòng: phòng → lớp gắn phòng → SIS Class Student (lọc năm học + campus)."""
    try:
        data = _parse_json_body()
        room_id = room_id or data.get("room_id")
        room_id = (room_id or "").strip()
        school_year_id = (school_year_id or data.get("school_year_id") or "").strip() or None
        campus_id = (campus_id or data.get("campus_id") or "").strip() or None

        if not room_id:
            return validation_error_response(_("Thiếu room_id"), {"room_id": ["required"]})
        if not frappe.db.exists("ERP Administrative Room", room_id):
            return not_found_response(_("Không tìm thấy phòng"))

        school_year_id = _active_school_year_id_api(school_year_id)
        if not school_year_id:
            return validation_error_response(
                _("Không xác định được năm học hiện tại"),
                {"school_year_id": ["required"]},
            )

        campus_id = _resolve_campus_id_api(campus_id)
        if not campus_id:
            return validation_error_response(
                _("Không xác định được campus"),
                {"campus_id": ["required"]},
            )

        students = frappe.db.sql(
            """
            SELECT DISTINCT
                cs.student_id,
                cs.class_id,
                c.title AS class_title
            FROM `tabERP Administrative Room Class` rc
            INNER JOIN `tabSIS Class` c
                ON c.name = rc.class_id
                AND c.school_year_id = %(sy)s
                AND c.campus_id = %(campus)s
            INNER JOIN `tabSIS Class Student` cs
                ON cs.class_id = c.name
                AND cs.school_year_id = %(sy)s
                AND cs.campus_id = %(campus)s
            WHERE rc.parent = %(room)s
                AND rc.parenttype = 'ERP Administrative Room'
            ORDER BY class_title ASC, cs.student_id ASC
            """,
            {"room": room_id, "sy": school_year_id, "campus": campus_id},
            as_dict=True,
        )

        if not students:
            return success_response({"students": []}, "OK")

        seen = {}
        ordered_ids = []
        for row in students:
            sid = row.get("student_id")
            if not sid or sid in seen:
                continue
            seen[sid] = {
                "student_id": sid,
                "class_id": row.get("class_id"),
                "class_title": row.get("class_title") or "",
            }
            ordered_ids.append(sid)

        stu_rows = frappe.get_all(
            "CRM Student",
            filters={"name": ["in", ordered_ids]},
            fields=["name", "student_name", "student_code"],
        )
        stu_map = {s.name: s for s in stu_rows}

        photo_map = {}
        if ordered_ids:
            photos = frappe.db.sql(
                """
                SELECT student_id, photo, school_year_id, upload_date, creation
                FROM `tabSIS Photo`
                WHERE student_id IN %(sids)s
                  AND type = 'student'
                  AND status = 'Active'
                ORDER BY student_id,
                    CASE WHEN school_year_id = %(sy)s THEN 0 ELSE 1 END,
                    upload_date DESC,
                    creation DESC
                """,
                {"sids": tuple(ordered_ids), "sy": school_year_id},
                as_dict=True,
            )
            for p in photos:
                sid = p.get("student_id")
                if sid and sid not in photo_map and p.get("photo"):
                    url = p.get("photo")
                    if url and not str(url).startswith("http"):
                        if str(url).startswith("/files/"):
                            url = frappe.utils.get_url(url)
                        else:
                            url = frappe.utils.get_url("/files/" + str(url))
                    photo_map[sid] = url or ""

        out = []
        for sid in ordered_ids:
            meta = seen.get(sid) or {}
            st = stu_map.get(sid)
            if not st:
                continue
            out.append(
                {
                    "student_id": sid,
                    "student_name": st.get("student_name") or "",
                    "student_code": st.get("student_code") or "",
                    "avatar_url": photo_map.get(sid) or "",
                    "class_title": meta.get("class_title") or "",
                }
            )

        return success_response({"students": out}, "OK")
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "administrative_ticket.get_students_by_room")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def create_ticket():
    """Tạo ticket mới."""
    try:
        data = _parse_json_body()
        title = (data.get("title") or "").strip()
        description = (data.get("description") or "").strip()
        category = (data.get("category") or "").strip()
        is_event_facility = cint(data.get("is_event_facility"))

        if category == EVENT_FACILITY_CATEGORY_NAME or is_event_facility:
            _ensure_event_facility_support_category()
            category = EVENT_FACILITY_CATEGORY_NAME
            is_event_facility = 1

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

        event_building_id = (data.get("event_building_id") or "").strip()
        event_room_id = (data.get("event_room_id") or "").strip()
        event_start_raw = data.get("event_start_time")
        event_end_raw = data.get("event_end_time")

        if is_event_facility:
            if not event_building_id or not frappe.db.exists("ERP Administrative Building", event_building_id):
                return validation_error_response(
                    _("Thiếu hoặc sai tòa nhà (sự kiện)"),
                    {"event_building_id": ["required"]},
                )
            if not event_room_id or not frappe.db.exists("ERP Administrative Room", event_room_id):
                return validation_error_response(
                    _("Thiếu hoặc sai phòng (sự kiện)"),
                    {"event_room_id": ["required"]},
                )
            rb = frappe.db.get_value("ERP Administrative Room", event_room_id, "building_id")
            if (rb or "").strip() != event_building_id:
                return validation_error_response(
                    _("Phòng không thuộc tòa nhà đã chọn"),
                    {"event_room_id": ["invalid"]},
                )
            if not event_start_raw or not event_end_raw:
                return validation_error_response(
                    _("Thiếu thời gian bắt đầu / kết thúc sự kiện"),
                    {"event_start_time": ["required"], "event_end_time": ["required"]},
                )
            try:
                event_start_time = get_datetime(event_start_raw)
                event_end_time = get_datetime(event_end_raw)
            except Exception:
                return validation_error_response(
                    _("Định dạng thời gian sự kiện không hợp lệ"),
                    {"event_start_time": ["invalid"], "event_end_time": ["invalid"]},
                )
            if not event_start_time or not event_end_time or event_end_time <= event_start_time:
                return validation_error_response(
                    _("Thời gian kết thúc phải sau thời gian bắt đầu"),
                    {"event_end_time": ["invalid"]},
                )

        room_id_nf = (data.get("room_id") or "").strip()
        related_equipment_ids_merged = _merge_equipment_ids_from_payload(data)
        related_student_ids_list = _normalize_related_student_ids(data.get("related_student_ids"))

        if is_event_facility:
            room_id_nf = ""
        elif room_id_nf:
            if not frappe.db.exists("ERP Administrative Room", room_id_nf):
                return validation_error_response(_("Phòng không hợp lệ"), {"room_id": ["invalid"]})
            rb = frappe.db.get_value("ERP Administrative Room", room_id_nf, "building_id")
            if area_title and (rb or "").strip() != area_title.strip():
                return validation_error_response(
                    _("Phòng không thuộc khu vực đã chọn"),
                    {"room_id": ["invalid"]},
                )

        effective_room_for_eq = event_room_id if is_event_facility else room_id_nf

        for equipment_id in related_equipment_ids_merged:
            if not frappe.db.exists(
                "ERP Administrative Room Facility Equipment", equipment_id
            ):
                return validation_error_response(
                    _("Thiết bị không hợp lệ"),
                    {"related_equipment_ids": ["invalid"]},
                )
            if effective_room_for_eq and not _validate_related_equipment_belongs_to_room(
                equipment_id, effective_room_for_eq
            ):
                return validation_error_response(
                    _("Thiết bị không thuộc phòng đã chọn"),
                    {"related_equipment_ids": ["invalid"]},
                )

        for sid in related_student_ids_list:
            if not frappe.db.exists("CRM Student", sid):
                return validation_error_response(
                    _("Học sinh không hợp lệ"),
                    {"related_student_ids": ["invalid"]},
                )

        email = _session_email()
        ufn = frappe.db.get_value("User", frappe.session.user, "full_name") or frappe.session.user
        uimg = frappe.db.get_value("User", frappe.session.user, "user_image") or ""
        udept = frappe.db.get_value("User", frappe.session.user, "department") or ""

        pic = _resolve_pic_from_assignment(category, area_title)

        ticket_row = {
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
            "is_event_facility": 1 if is_event_facility else 0,
        }
        if is_event_facility:
            ticket_row["event_building_id"] = event_building_id
            ticket_row["event_room_id"] = event_room_id
            ticket_row["event_start_time"] = event_start_time
            ticket_row["event_end_time"] = event_end_time
            ticket_row["room_id"] = None
        else:
            ticket_row["room_id"] = room_id_nf or None
        ticket_row["related_equipment_id"] = (
            related_equipment_ids_merged[0] if related_equipment_ids_merged else None
        )
        ticket_row["related_equipment_ids"] = _json_list_field_for_db(related_equipment_ids_merged)
        ticket_row["related_student_ids"] = _json_list_field_for_db(related_student_ids_list)

        doc = frappe.get_doc(ticket_row)
        if pic:
            doc.assigned_to = pic
            pfn = frappe.db.get_value("User", pic, "full_name") or pic
            doc.assigned_to_fullname = pfn
            doc.status = "Assigned"
            doc.accepted_at = now_datetime()

        doc.insert(ignore_permissions=True)

        _append_history(doc.name, _("Tạo yêu cầu"))
        try:
            _ticket_log_room_repair_activity(frappe.get_doc(DOCTYPE, doc.name), "repair_reported")
        except Exception:
            frappe.log_error(frappe.get_traceback(), "administrative_ticket.create_ticket.room_log")
        frappe.db.commit()

        try:
            _notify_new_admin_ticket_mobile(frappe.get_doc(DOCTYPE, doc.name))
        except Exception:
            frappe.log_error(frappe.get_traceback(), "administrative_ticket._notify_new_admin_ticket_mobile")

        try:
            _hc_send_emails_on_ticket_create(frappe.get_doc(DOCTYPE, doc.name))
        except Exception:
            frappe.log_error(frappe.get_traceback(), "administrative_ticket._hc_send_emails_on_ticket_create")

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

        old_status = doc.status

        if "title" in data and data["title"]:
            doc.title = str(data["title"]).strip()
        if "description" in data:
            doc.description = str(data["description"] or "")
        if "category" in data and data["category"]:
            cat = str(data["category"]).strip()
            if cat == EVENT_FACILITY_CATEGORY_NAME:
                _ensure_event_facility_support_category()
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

        if "is_event_facility" in data:
            doc.is_event_facility = cint(data.get("is_event_facility"))
        if "event_building_id" in data:
            eb = str(data.get("event_building_id") or "").strip()
            doc.event_building_id = eb or None
        if "event_room_id" in data:
            er = str(data.get("event_room_id") or "").strip()
            doc.event_room_id = er or None
        if "event_start_time" in data:
            evs = data.get("event_start_time")
            if evs in (None, ""):
                doc.event_start_time = None
            else:
                try:
                    doc.event_start_time = get_datetime(evs)
                except Exception:
                    return validation_error_response(
                        _("Định dạng thời gian bắt đầu sự kiện không hợp lệ"),
                        {"event_start_time": ["invalid"]},
                    )
        if "event_end_time" in data:
            eve = data.get("event_end_time")
            if eve in (None, ""):
                doc.event_end_time = None
            else:
                try:
                    doc.event_end_time = get_datetime(eve)
                except Exception:
                    return validation_error_response(
                        _("Định dạng thời gian kết thúc sự kiện không hợp lệ"),
                        {"event_end_time": ["invalid"]},
                    )

        if "room_id" in data:
            rid = str(data.get("room_id") or "").strip()
            doc.room_id = rid or None
        if "related_equipment_ids" in data or "related_equipment_id" in data:
            merged_eq = _merge_equipment_ids_from_payload(
                {
                    "related_equipment_ids": data.get("related_equipment_ids")
                    if "related_equipment_ids" in data
                    else None,
                    "related_equipment_id": data.get("related_equipment_id")
                    if "related_equipment_id" in data
                    else "",
                }
            )
            doc.related_equipment_ids = _json_list_field_for_db(merged_eq)
            doc.related_equipment_id = merged_eq[0] if merged_eq else None
        if "related_student_ids" in data:
            rlist = _normalize_related_student_ids(data.get("related_student_ids"))
            doc.related_student_ids = _json_list_field_for_db(rlist)

        if cint(getattr(doc, "is_event_facility", 0)):
            eb = (getattr(doc, "event_building_id", None) or "").strip()
            er = (getattr(doc, "event_room_id", None) or "").strip()
            if not eb or not frappe.db.exists("ERP Administrative Building", eb):
                return validation_error_response(_("Thiếu tòa nhà (sự kiện)"), {"event_building_id": ["required"]})
            if not er or not frappe.db.exists("ERP Administrative Room", er):
                return validation_error_response(_("Thiếu phòng (sự kiện)"), {"event_room_id": ["required"]})
            rb = frappe.db.get_value("ERP Administrative Room", er, "building_id")
            if (rb or "").strip() != eb:
                return validation_error_response(_("Phòng không thuộc tòa nhà đã chọn"), {"event_room_id": ["invalid"]})
            est = getattr(doc, "event_start_time", None)
            eet = getattr(doc, "event_end_time", None)
            if not est or not eet:
                return validation_error_response(
                    _("Thiếu thời gian sự kiện"),
                    {"event_start_time": ["required"], "event_end_time": ["required"]},
                )
            if eet <= est:
                return validation_error_response(
                    _("Thời gian kết thúc phải sau thời gian bắt đầu"),
                    {"event_end_time": ["invalid"]},
                )

        # Ticket thường: không lưu room_id (dùng event_room_id cho CSVC sự kiện)
        if cint(getattr(doc, "is_event_facility", 0)):
            doc.room_id = None

        area_title_cur = (doc.area_title or "").strip()
        room_id_nf = (getattr(doc, "room_id", None) or "").strip()
        if not cint(getattr(doc, "is_event_facility", 0)) and room_id_nf:
            if not frappe.db.exists("ERP Administrative Room", room_id_nf):
                return validation_error_response(_("Phòng không hợp lệ"), {"room_id": ["invalid"]})
            rb = frappe.db.get_value("ERP Administrative Room", room_id_nf, "building_id")
            if area_title_cur and (rb or "").strip() != area_title_cur.strip():
                return validation_error_response(
                    _("Phòng không thuộc khu vực đã chọn"),
                    {"room_id": ["invalid"]},
                )

        effective_room_for_eq = (
            (getattr(doc, "event_room_id", None) or "").strip()
            if cint(getattr(doc, "is_event_facility", 0))
            else room_id_nf
        )
        for rel_eq in _related_equipment_ids_resolved(doc):
            if not frappe.db.exists("ERP Administrative Room Facility Equipment", rel_eq):
                return validation_error_response(
                    _("Thiết bị không hợp lệ"),
                    {"related_equipment_ids": ["invalid"]},
                )
            if effective_room_for_eq and not _validate_related_equipment_belongs_to_room(
                rel_eq, effective_room_for_eq
            ):
                return validation_error_response(
                    _("Thiết bị không thuộc phòng đã chọn"),
                    {"related_equipment_ids": ["invalid"]},
                )

        related_student_ids_list = _normalize_related_student_ids(getattr(doc, "related_student_ids", None))
        for sid in related_student_ids_list:
            if not frappe.db.exists("CRM Student", sid):
                return validation_error_response(
                    _("Học sinh không hợp lệ"),
                    {"related_student_ids": ["invalid"]},
                )

        old_assigned_to = getattr(doc, "assigned_to", None)

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
        hist_detail = None
        if staff and "status" in data and data.get("status") and old_status != doc.status:
            hist_detail = _("Trạng thái: {0} → {1}").format(old_status, doc.status)
        _append_history(doc.name, _("Cập nhật ticket"), detail=hist_detail)
        try:
            if old_status != doc.status and doc.status in ("Resolved", "Closed", "Done"):
                _ticket_log_room_repair_activity(frappe.get_doc(DOCTYPE, doc.name), "repair_completed")
        except Exception:
            frappe.log_error(frappe.get_traceback(), "administrative_ticket.update_ticket.room_log")
        frappe.db.commit()
        try:
            doc_reload = frappe.get_doc(DOCTYPE, doc.name)
            if staff:
                if "status" in data and data.get("status") and old_status != doc_reload.status:
                    _notify_hc_status_changed(doc_reload, old_status, doc_reload.status, email)
                if "assigned_to" in data and old_assigned_to != doc_reload.assigned_to:
                    _notify_hc_assignment_changed(
                        doc_reload, old_assigned_to, doc_reload.assigned_to, email
                    )
        except Exception:
            frappe.log_error(
                frappe.get_traceback(), "administrative_ticket.update_ticket.notify"
            )
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
        try:
            _notify_hc_ticket_pickup(frappe.get_doc(DOCTYPE, doc.name))
        except Exception:
            frappe.log_error(frappe.get_traceback(), "administrative_ticket.assign_ticket.notify")
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
        _append_history(doc.name, _("Hủy ticket"), detail=reason[:500])
        frappe.db.commit()
        try:
            _notify_hc_cancelled(frappe.get_doc(DOCTYPE, doc.name), email)
        except Exception:
            frappe.log_error(frappe.get_traceback(), "administrative_ticket.cancel_ticket.notify")
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
        email = _session_email()
        doc.status = "Open"
        doc.closed_at = None
        doc.feedback_rating = 0
        doc.feedback_comment = None
        doc.feedback_badges = None
        doc.save(ignore_permissions=True)
        _append_history(doc.name, _("Mở lại ticket"))
        frappe.db.commit()
        try:
            _notify_hc_reopened(frappe.get_doc(DOCTYPE, doc.name), email)
        except Exception:
            frappe.log_error(frappe.get_traceback(), "administrative_ticket.reopen_ticket.notify")
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
        try:
            _notify_hc_feedback_received(frappe.get_doc(DOCTYPE, doc.name), email)
        except Exception:
            frappe.log_error(frappe.get_traceback(), "administrative_ticket.accept_feedback.notify")
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
        _append_history(ticket_id, _("Thêm công việc con"), detail=title[:500])
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
            # Field JSON trên Frappe không chấp nhận gán list trực tiếp (chỉ dict được tự dumps)
            row["images_json"] = json.dumps(images, separators=(",", ":"))
        c = frappe.get_doc(row)
        c.insert(ignore_permissions=True)
        if text:
            excerpt = text[:500] + ("…" if len(text) > 500 else "")
            if images:
                excerpt += _(" (+{0} ảnh/video)").format(len(images))
        elif images:
            excerpt = _("Gửi {0} ảnh/video").format(len(images))
        else:
            excerpt = ""
        _append_history(ticket_id, _("Trao đổi"), detail=excerpt or None)
        frappe.db.commit()
        try:
            _notify_hc_user_reply(frappe.get_doc(DOCTYPE, ticket_id), email)
        except Exception:
            frappe.log_error(frappe.get_traceback(), "administrative_ticket.send_comment.notify")
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
            fields=[
                "name",
                "creation",
                "action",
                "detail",
                "user_email",
                "user_fullname",
                "user_avatar",
            ],
            order_by="creation asc",
        )
        out = []
        for r in rows:
            out.append(
                {
                    "_id": r.name,
                    "timestamp": r.creation,
                    "action": r.action,
                    "detail": r.get("detail") or "",
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
