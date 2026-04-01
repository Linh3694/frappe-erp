"""
CRM History API - Lich su chuyen buoc, thay doi thong tin, thong bao Parent Portal
"""

import glob
import json
import os

import frappe
from frappe import _
from erp.utils.api_response import (
    success_response, list_response, validation_error_response, not_found_response
)
from erp.api.crm.utils import check_crm_permission


@frappe.whitelist()
def get_step_history():
    """Lich su chuyen buoc"""
    check_crm_permission()
    
    lead_name = frappe.request.args.get("lead_name")
    if not lead_name:
        return validation_error_response("Thieu lead_name", {"lead_name": ["Bat buoc"]})
    
    if not frappe.db.exists("CRM Lead", lead_name):
        return not_found_response(f"Khong tim thay ho so {lead_name}")
    
    history = frappe.get_all(
        "CRM Lead Step History",
        filters={"lead": lead_name},
        fields=["old_step", "new_step", "old_status", "new_status", "changed_by", "changed_at",
                "reject_reason", "reject_detail"],
        order_by="changed_at asc"
    )

    # Bo sung full_name tu User cho changed_by de FE chuẩn hoa bang userUtils
    for h in history:
        user_id = h.get("changed_by")
        if user_id:
            full_name = frappe.db.get_value("User", user_id, "full_name")
            h["changed_by_full_name"] = full_name or user_id
        else:
            h["changed_by_full_name"] = None

    return list_response(history)


@frappe.whitelist()
def get_change_history():
    """Lich su thay doi thong tin (dung Frappe Version)"""
    check_crm_permission()
    
    lead_name = frappe.request.args.get("lead_name")
    if not lead_name:
        return validation_error_response("Thieu lead_name", {"lead_name": ["Bat buoc"]})
    
    if not frappe.db.exists("CRM Lead", lead_name):
        return not_found_response(f"Khong tim thay ho so {lead_name}")
    
    versions = frappe.get_all(
        "Version",
        filters={"ref_doctype": "CRM Lead", "docname": lead_name},
        fields=["name", "owner", "creation", "data"],
        order_by="creation desc",
        limit_page_length=50
    )
    
    changes = []
    for v in versions:
        try:
            import json
            version_data = json.loads(v.get("data", "{}"))
            changed_fields = version_data.get("changed", [])
            owner = v["owner"]
            full_name = frappe.db.get_value("User", owner, "full_name") if owner else None
            changes.append({
                "version": v["name"],
                "changed_by": owner,
                "changed_by_full_name": full_name or owner,
                "changed_at": str(v["creation"]),
                "changes": changed_fields
            })
        except Exception:
            pass
    
    return list_response(changes)


# Cac loai ERP Notification hien thi trong CRM (thong bao/tin den PH & HS)
_PARENT_NOTIFICATION_TYPES = (
    "news",
    "announcement",
    "post",
    "info",
    "reminder",
    "alert",
    "report_card",
    "contact_log",
    "leave",
    "attendance",
    "health_examination",
    "periodic_health_checkup",
)

# Nhan loai tieng Viet — dung cho tim kiem
_NOTIF_TYPE_LABELS_VI = {
    "news": "tin tức",
    "announcement": "thông báo",
    "post": "bài đăng",
    "info": "thông tin",
    "reminder": "nhắc nhở",
    "alert": "cảnh báo",
    "report_card": "báo cáo học tập",
    "contact_log": "sổ liên lạc",
    "leave": "xin nghỉ",
    "attendance": "điểm danh",
    "health_examination": "khám sức khỏe",
    "periodic_health_checkup": "khám sk định kỳ",
}


def _notif_type_label_vi(ntype):
    if not ntype:
        return ""
    return _NOTIF_TYPE_LABELS_VI.get(ntype, str(ntype).replace("_", " "))


def _parse_bilingual_text(raw):
    """Lay chuoi tieng Viet (hoac EN) tu title/message dang JSON hoac plain."""
    if raw is None:
        return ""
    if isinstance(raw, dict):
        return (raw.get("vi") or raw.get("en") or "").strip()
    s = str(raw).strip()
    if not s:
        return ""
    try:
        j = json.loads(s)
        if isinstance(j, dict):
            return (j.get("vi") or j.get("en") or s).strip()
    except Exception:
        pass
    return s


def _body_text_from_data_dict(data):
    """Mot so loai thong bao chi dat noi dung trong data (body/message/content)."""
    if not isinstance(data, dict):
        return ""
    for key in ("body", "message", "content", "text", "description"):
        if key not in data:
            continue
        val = data[key]
        if val is None:
            continue
        if isinstance(val, dict):
            t = (val.get("vi") or val.get("en") or "").strip()
            if t:
                return t
        if isinstance(val, str):
            t = _parse_bilingual_text(val)
            if t.strip():
                return t.strip()
    return ""


def _notification_row_body_text(row, data):
    """Noi dung tin gui PH: uu tien cot message, khong co thi lay tu data."""
    m = _parse_bilingual_text(row.get("message"))
    if m and m.strip():
        return m.strip()
    return _body_text_from_data_dict(data)


def _notification_expanded_body(row, data, ntype):
    """
    Noi dung day du khi mo rong (vd. sổ liên lạc: nhan xet GVCN trong data,
    khac voi dong tom tat trong cot message).
    """
    if ntype == "contact_log" and isinstance(data, dict):
        c = (data.get("contact_log_comment") or "").strip()
        if c:
            return c
        # Thong bao cu: thu lay tu ban ghi SIS Class Log Student neu co id trong data
        cls_name = data.get("class_log_student_id")
        if cls_name and frappe.db.exists("SIS Class Log Student", cls_name):
            c2 = frappe.db.get_value("SIS Class Log Student", cls_name, "contact_log_comment")
            if c2 and str(c2).strip():
                return str(c2).strip()
    return _notification_row_body_text(row, data)


def _crm_absolute_file_url(path):
    """Chuyen duong dan file Frappe thanh URL day du (dung cho anh bia / attach)."""
    if not path:
        return ""
    s = str(path).strip()
    if not s:
        return ""
    if s.startswith("http://") or s.startswith("https://"):
        return s
    if s.startswith("/"):
        return frappe.utils.get_url(s)
    return frappe.utils.get_url("/files/" + s)


def _crm_report_card_image_urls(report_id):
    """
    Lay danh sach URL anh bao cao hoc tap (cung logic thu muc voi parent_portal/report_card).
    """
    if not report_id or not frappe.db.exists("SIS Student Report Card", report_id):
        return []
    try:
        report = frappe.get_doc("SIS Student Report Card", report_id, ignore_permissions=True)
    except Exception:
        return []
    try:
        student = frappe.get_doc("CRM Student", report.student_id, ignore_permissions=True)
        student_code = student.student_code or report.student_id
    except Exception:
        student_code = report.student_id
    school_year = (
        getattr(report, "school_year", None)
        or getattr(report, "academic_year", None)
        or "unknown"
    )
    semester_part = (
        getattr(report, "semester_part", None)
        or getattr(report, "semester", None)
        or "semester_1"
    )
    physical_path = frappe.get_site_path(
        "public", "files", "reportcard", student_code, school_year, semester_part
    )
    folder_path = f"/files/reportcard/{student_code}/{school_year}/{semester_part}"
    if not os.path.exists(physical_path):
        return []
    png_files = glob.glob(os.path.join(physical_path, "page_*.png"))
    png_files.sort()
    out = []
    for file_path in png_files:
        filename = os.path.basename(file_path)
        rel = f"{folder_path}/{filename}"
        out.append(frappe.utils.get_url(rel))
    return out


def _crm_health_examination_image_urls(exam_id):
    """Lay URL anh tu bang con SIS Examination Image."""
    if not exam_id or not frappe.db.exists("SIS Health Examination", exam_id):
        return []
    rows = frappe.get_all(
        "SIS Examination Image",
        filters={"parent": exam_id},
        fields=["image"],
        order_by="idx asc",
    )
    out = []
    for r in rows:
        img = (r.get("image") or "").strip()
        if img:
            out.append(_crm_absolute_file_url(img))
    return out


def _enrich_page_items_crm_history(page_items):
    """
    Bo sung cover_image, image_urls, content_html, reference_id cho tung muc trang hien tai.
    Chi goi sau khi phan trang — tranh query nang cho toan bo lich su.
    """
    enriched = []
    for item in page_items:
        data = item.pop("_data", None) or {}
        if not isinstance(data, dict):
            data = {}
        ntype = item.get("notification_type") or ""
        cover_image = ""
        image_urls = []
        content_html = ""
        reference_id = ""

        try:
            if ntype == "news" and data.get("article_id"):
                reference_id = str(data["article_id"]).strip()
                if reference_id and frappe.db.exists("SIS News Article", reference_id):
                    art = frappe.db.get_value(
                        "SIS News Article",
                        reference_id,
                        ["cover_image", "content_vn", "content_en"],
                        as_dict=True,
                    )
                    if art:
                        cover_image = _crm_absolute_file_url(art.get("cover_image"))
                        content_html = (art.get("content_vn") or art.get("content_en") or "").strip()

            elif ntype == "announcement" and data.get("announcement_id"):
                reference_id = str(data["announcement_id"]).strip()
                if reference_id and frappe.db.exists("SIS Announcement", reference_id):
                    ann = frappe.db.get_value(
                        "SIS Announcement",
                        reference_id,
                        ["content_vn", "content_en"],
                        as_dict=True,
                    )
                    if ann:
                        content_html = (ann.get("content_vn") or ann.get("content_en") or "").strip()

            elif ntype == "report_card":
                rid = data.get("report_id")
                if isinstance(rid, list) and rid:
                    rid = rid[0]
                if rid:
                    reference_id = str(rid).strip()
                    image_urls = _crm_report_card_image_urls(reference_id)

            elif ntype == "periodic_health_checkup":
                ck = (data.get("checkup_name") or "").strip()
                if ck:
                    reference_id = ck
                    try:
                        from erp.api.erp_sis.health_checkup_images import (
                            get_health_checkup_image_urls_for_checkup,
                        )

                        imgs = get_health_checkup_image_urls_for_checkup(ck)
                        image_urls = [x.get("url") for x in imgs if x.get("url")]
                    except Exception:
                        frappe.logger().error(
                            frappe.get_traceback(), "CRM periodic_health_checkup images"
                        )

            elif ntype == "health_examination":
                exam_ids = data.get("exam_ids") or []
                if isinstance(exam_ids, str):
                    exam_ids = [exam_ids]
                if exam_ids:
                    eid = str(exam_ids[0]).strip()
                    reference_id = eid
                    image_urls = _crm_health_examination_image_urls(eid)
        except Exception:
            frappe.logger().error(frappe.get_traceback(), "CRM enrich notification detail")

        item["cover_image"] = cover_image
        item["image_urls"] = image_urls
        item["content_html"] = content_html
        item["reference_id"] = reference_id
        enriched.append(item)
    return enriched


def _recipient_user_ids_from_email(email):
    """User.name co the la email hoac ten dang nhap."""
    if not email or not str(email).strip():
        return []
    email = str(email).strip()
    out = []
    uid = frappe.db.get_value("User", {"email": email}, "name")
    if not uid:
        row = frappe.db.sql(
            "SELECT name FROM `tabUser` WHERE LOWER(email)=LOWER(%s) LIMIT 1",
            (email,),
        )
        if row:
            uid = row[0][0]
    if uid:
        out.append(uid)
    if frappe.db.exists("User", email):
        out.append(email)
    return list(dict.fromkeys(out))


@frappe.whitelist()
def get_parent_notification_history():
    """
    Tom tat thong bao/tin da gui den guardian (User Parent Portal) lien quan ho so CRM.
    Loc theo hoc sinh lien ket (linked_student) neu co — trung khop student_id trong data JSON.

    Query params:
        lead_name (bat buoc)
        page: trang bat dau 1 (mac dinh 1)
        page_size: so muc/trang (mac dinh 10, toi da 50)
        search: loc theo tieu de, noi dung, loai (khong phan biet hoa thuong)
    """
    check_crm_permission()

    lead_name = frappe.request.args.get("lead_name")
    if not lead_name:
        return validation_error_response("Thieu lead_name", {"lead_name": ["Bat buoc"]})

    if not frappe.db.exists("CRM Lead", lead_name):
        return not_found_response(f"Khong tim thay ho so {lead_name}")

    lead = frappe.get_doc("CRM Lead", lead_name)
    guardian_email = (lead.guardian_email or "").strip()
    linked_student = (lead.linked_student or "").strip()

    recipient_set = set()
    for uid in _recipient_user_ids_from_email(guardian_email):
        recipient_set.add(uid)

    if linked_student:
        try:
            from erp.utils.notification_handler import get_guardians_for_students

            for g in get_guardians_for_students([linked_student]) or []:
                em = (g.get("email") or "").strip()
                for uid in _recipient_user_ids_from_email(em):
                    recipient_set.add(uid)
        except Exception:
            frappe.logger().error(frappe.get_traceback(), "CRM get_parent_notification_history guardians")

    if not recipient_set:
        return list_response(
            [],
            meta={
                "total": 0,
                "page": 1,
                "page_size": 10,
                "total_pages": 1,
            },
        )

    try:
        page = int(frappe.request.args.get("page") or 1)
    except Exception:
        page = 1
    page = max(1, page)

    try:
        page_size = int(frappe.request.args.get("page_size") or 10)
    except Exception:
        page_size = 10
    page_size = min(max(1, page_size), 50)

    search_raw = (frappe.request.args.get("search") or "").strip()
    q = search_raw.lower()

    rows = frappe.get_all(
        "ERP Notification",
        filters=[
            ["recipient_user", "in", list(recipient_set)],
            ["notification_type", "in", list(_PARENT_NOTIFICATION_TYPES)],
        ],
        fields=[
            "name",
            "title",
            "message",
            "notification_type",
            "event_timestamp",
            "creation",
            "data",
            "recipient_user",
            "sender",
            "sent_at",
        ],
        order_by="creation desc",
        limit_page_length=2000,
    )

    rows.sort(
        key=lambda r: str(r.get("event_timestamp") or r.get("sent_at") or r.get("creation") or ""),
        reverse=True,
    )

    student_keys = set()
    if linked_student:
        student_keys.add(linked_student)
        sc = frappe.db.get_value("CRM Student", linked_student, "student_code")
        if sc:
            student_keys.add(sc)

    out = []
    for row in rows:
        data = {}
        try:
            data = json.loads(row.get("data") or "{}")
        except Exception:
            data = {}
        sid = data.get("student_id") or data.get("studentId") or data.get("studentCode")
        if linked_student:
            if sid and sid not in student_keys:
                continue
        else:
            if sid:
                continue

        title_vi = _parse_bilingual_text(row.get("title"))
        ntype = row.get("notification_type") or ""
        # Tom tat (dong duoi tieu de khi thu go) vs noi dung mo rong (co the dai hon, vd. contact_log)
        msg_short = _notification_row_body_text(row, data)
        msg_full = _notification_expanded_body(row, data, ntype)
        msg_preview = (msg_short[:240] + "…") if len(msg_short) > 240 else msg_short

        ts = row.get("event_timestamp") or row.get("sent_at") or row.get("creation")
        ts_str = str(ts) if ts else ""

        sender_display = None
        if row.get("sender"):
            sender_display = frappe.db.get_value("User", row["sender"], "full_name") or row["sender"]

        if q:
            blob = " ".join(
                [
                    title_vi,
                    msg_short,
                    msg_full,
                    ntype,
                    _notif_type_label_vi(ntype),
                ]
            ).lower()
            if q not in blob:
                continue

        out.append(
            {
                "name": row["name"],
                "notification_type": ntype,
                "title": title_vi or ntype or "Thông báo",
                "message_preview": msg_preview,
                # Noi dung day du khi mo rong (vd. nhan xet chi tiet sổ liên lạc)
                "message_full": msg_full,
                "sent_at": ts_str,
                "recipient_user": row.get("recipient_user") or "",
                "sender": row.get("sender") or "",
                "sender_display": sender_display,
                # Parse JSON data — dung enrich sau phan trang (khong tra ve client)
                "_data": data,
            }
        )

    total = len(out)
    total_pages = max(1, (total + page_size - 1) // page_size) if total else 1
    if page > total_pages:
        page = total_pages

    start = (page - 1) * page_size
    page_items = out[start : start + page_size]
    page_items = _enrich_page_items_crm_history(page_items)

    return list_response(
        page_items,
        meta={
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        },
    )
