"""
CRM History API - Lich su chuyen buoc, thay doi thong tin, thong bao Parent Portal
"""

import json

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


def _recipient_user_ids_from_email(email):
    """User.name co the la email hoac ten dang nhap."""
    if not email or not str(email).strip():
        return []
    email = str(email).strip()
    out = []
    uid = frappe.db.get_value("User", {"email": email}, "name")
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
        return list_response([])

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
        limit_page_length=300,
    )

    rows.sort(
        key=lambda r: str(r.get("event_timestamp") or r.get("sent_at") or r.get("creation") or ""),
        reverse=True,
    )
    rows = rows[:200]

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
        msg_raw = _parse_bilingual_text(row.get("message"))
        msg_preview = (msg_raw[:240] + "…") if len(msg_raw) > 240 else msg_raw

        ts = row.get("event_timestamp") or row.get("sent_at") or row.get("creation")
        ts_str = str(ts) if ts else ""

        sender_display = None
        if row.get("sender"):
            sender_display = frappe.db.get_value("User", row["sender"], "full_name") or row["sender"]

        out.append(
            {
                "name": row["name"],
                "notification_type": row.get("notification_type") or "",
                "title": title_vi or row.get("notification_type") or "Thông báo",
                "message_preview": msg_preview,
                "sent_at": ts_str,
                "recipient_user": row.get("recipient_user") or "",
                "sender": row.get("sender") or "",
                "sender_display": sender_display,
            }
        )

    return list_response(out)
