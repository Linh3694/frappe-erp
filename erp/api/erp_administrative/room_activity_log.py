# Copyright (c) 2026, Wellspring International School and contributors
# Ghi nhật ký hoạt động cấp phòng (bàn giao, kiểm kê, gán/gỡ PIC).

import frappe
from frappe.utils import get_fullname

ACTIVITY_TYPES = frozenset(
    {
        "handover_sent",
        "handover_confirmed",
        "inventory_submitted",
        "inventory_accepted",
        "inventory_rejected",
        "user_assigned",
        "user_removed",
    }
)


def log_room_activity(
    room_id,
    activity_type,
    user=None,
    target_user=None,
    reference_doctype=None,
    reference_name=None,
    note=None,
):
    """
    Tạo bản ghi ERP Administrative Room Activity Log.
    Dùng ignore_permissions vì có thể gọi từ user Teacher khi gửi kiểm kê.
    """
    if not room_id or not frappe.db.exists("ERP Administrative Room", room_id):
        return None
    if activity_type not in ACTIVITY_TYPES:
        frappe.log_error(
            f"Invalid activity_type={activity_type}", "room_activity_log.log_room_activity"
        )
        return None

    uid = user or frappe.session.user
    un_name = ""
    if uid:
        try:
            un_name = get_fullname(uid) or uid
        except Exception:
            un_name = uid
    tu_name = ""
    if target_user:
        try:
            tu_name = get_fullname(target_user) or target_user
        except Exception:
            tu_name = target_user

    doc = frappe.get_doc(
        {
            "doctype": "ERP Administrative Room Activity Log",
            "room": room_id,
            "activity_type": activity_type,
            "user": uid,
            "user_name": un_name,
            "target_user": target_user or None,
            "target_user_name": tu_name or None,
            "reference_doctype": reference_doctype or "",
            "reference_name": reference_name or "",
            "note": note or "",
        }
    )
    doc.insert(ignore_permissions=True)
    return doc.name
