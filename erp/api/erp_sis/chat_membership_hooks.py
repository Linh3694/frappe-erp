"""
Doc-event hooks: bắn sync membership nhóm chat (social-service) khi roster lớp đổi.

Bổ sung cho cron 6:30 hằng ngày — các thay đổi sau có hiệu lực gần như tức thì:
  - Đổi GVCN / phó GVCN trên SIS Class
  - Thêm / sửa / xoá SIS Subject Assignment (phân công giảng dạy)

Cơ chế: enqueue background job (dedupe theo class+year, chạy sau commit) → POST
`/api/social/chat/sync/memberships` của social-service với body {classId, schoolYearId}.

Cấu hình site_config.json (thiếu thì hook im lặng bỏ qua, không chặn save):
  - social_service_base_url        vd "https://prod.sis.wellspring.edu.vn"
  - social_service_sync_api_key    trùng FRAPPE_API_KEY của social-service
  - social_service_sync_api_secret trùng FRAPPE_API_SECRET của social-service
"""

import frappe
import requests


def _social_service_config():
    base_url = (frappe.conf.get("social_service_base_url") or "").rstrip("/")
    api_key = frappe.conf.get("social_service_sync_api_key") or ""
    api_secret = frappe.conf.get("social_service_sync_api_secret") or ""
    if not base_url or not api_key or not api_secret:
        return None
    return {"base_url": base_url, "api_key": api_key, "api_secret": api_secret}


def enqueue_chat_membership_sync(class_id, school_year_id):
    """Enqueue sync cho một lớp — dedupe khi cùng lớp bắn dồn dập (import/sửa hàng loạt)."""
    if not class_id or not school_year_id:
        return
    if not _social_service_config():
        return
    try:
        frappe.enqueue(
            "erp.api.erp_sis.chat_membership_hooks.push_chat_membership_sync",
            queue="short",
            enqueue_after_commit=True,
            job_id=f"chat-membership-sync::{class_id}::{school_year_id}",
            deduplicate=True,
            class_id=class_id,
            school_year_id=school_year_id,
        )
    except Exception as e:
        frappe.logger().warning(
            f"[Chat Membership Hook] enqueue failed {class_id}/{school_year_id}: {str(e)}"
        )


def push_chat_membership_sync(class_id, school_year_id):
    """Background job: gọi endpoint sync của social-service cho đúng một lớp."""
    cfg = _social_service_config()
    if not cfg:
        return
    try:
        resp = requests.post(
            f"{cfg['base_url']}/api/social/chat/sync/memberships",
            json={"classId": class_id, "schoolYearId": school_year_id},
            headers={
                "Authorization": f"token {cfg['api_key']}:{cfg['api_secret']}",
                "Content-Type": "application/json",
            },
            timeout=60,
        )
        body = {}
        try:
            body = resp.json()
        except Exception:
            pass
        frappe.logger().info(
            f"[Chat Membership Hook] synced {class_id}/{school_year_id}: "
            f"status={resp.status_code} summary={body.get('data', {}) if isinstance(body, dict) else ''}"
        )
    except Exception as e:
        frappe.logger().warning(
            f"[Chat Membership Hook] push failed {class_id}/{school_year_id}: {str(e)}"
        )


def on_sis_class_change(doc, method=None):
    """SIS Class on_update/after_insert — chỉ bắn khi GVCN/phó GVCN đổi (hoặc lớp mới)."""
    try:
        changed = True
        if method == "on_update":
            prev = doc.get_doc_before_save()
            if prev:
                changed = (
                    (prev.get("homeroom_teacher") or "") != (doc.get("homeroom_teacher") or "")
                    or (prev.get("vice_homeroom_teacher") or "") != (doc.get("vice_homeroom_teacher") or "")
                )
        if changed:
            enqueue_chat_membership_sync(doc.name, doc.get("school_year_id"))
    except Exception as e:
        # Hook không được chặn luồng lưu doc.
        frappe.logger().warning(f"[Chat Membership Hook] on_sis_class_change: {str(e)}")


def on_subject_assignment_change(doc, method=None):
    """SIS Subject Assignment after_insert/on_update/on_trash — roster GVBM đổi."""
    try:
        enqueue_chat_membership_sync(doc.get("class_id"), doc.get("school_year_id"))
    except Exception as e:
        frappe.logger().warning(
            f"[Chat Membership Hook] on_subject_assignment_change: {str(e)}"
        )
