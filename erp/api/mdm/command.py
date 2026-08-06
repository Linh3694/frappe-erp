"""Hàng đợi lệnh: chiều xuống dùng POLL, Frappe không gọi ngược vào máy.

Máy học sinh bật/tắt liên tục và nằm sau NAT — push là mô hình sai ở đây. Máy
offline nhận lệnh khi bật lại, không mất.
"""

from __future__ import annotations

import frappe
from frappe.utils import cint, now_datetime

from erp.api.mdm.auth import get_authenticated_device

DOCTYPE = "MDM Command"
DEVICE_DOCTYPE = "MDM Device"

COMMAND_TYPES = (
    "set_wallpaper", "lock", "restart", "logoff", "notify",
    "run_policy", "update_agent", "collect_inventory",
)

# Giao quá số lần này mà không ack thì coi như hỏng — tránh một lệnh lỗi được
# giao lại vô hạn mỗi lần agent poll.
MAX_ATTEMPTS = 5


@frappe.whitelist(allow_guest=True, methods=["GET", "POST"])
def pull_commands():
    """Agent kéo lệnh đang chờ. Pending → Sent."""
    device = get_authenticated_device()

    rows = frappe.get_all(
        DOCTYPE,
        filters={"device": device.name, "status": ["in", ["Pending", "Sent"]]},
        fields=["name", "command_type", "params", "attempts"],
        order_by="creation asc",
        limit_page_length=20,
    )

    commands = []
    for row in rows:
        attempts = cint(row.attempts) + 1
        if attempts > MAX_ATTEMPTS:
            frappe.db.set_value(
                DOCTYPE, row.name,
                {"status": "Failed", "result": f"Agent không ack sau {MAX_ATTEMPTS} lần giao",
                 "completed_at": now_datetime()},
                update_modified=False,
            )
            continue

        frappe.db.set_value(
            DOCTYPE, row.name,
            {"status": "Sent", "sent_at": now_datetime(), "attempts": attempts},
            update_modified=False,
        )
        commands.append(
            {
                "id": row.name,
                "command_type": row.command_type,
                "params": frappe.parse_json(row.params) if row.params else {},
            }
        )

    frappe.db.commit()
    return {"commands": commands}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def ack_command(command_id=None, status=None, result=None):
    """Agent báo kết quả thực thi."""
    device = get_authenticated_device()

    if not command_id:
        frappe.throw("Thiếu command_id")
    if status not in ("Done", "Failed"):
        frappe.throw("status phải là Done hoặc Failed")

    owner_device = frappe.db.get_value(DOCTYPE, command_id, "device")
    if owner_device != device.name:
        # Máy này ack lệnh của máy khác — token đúng nhưng lệnh không phải của nó
        frappe.local.response["http_status_code"] = 403
        frappe.throw("Lệnh không thuộc thiết bị này", frappe.PermissionError)

    frappe.db.set_value(
        DOCTYPE, command_id,
        {"status": status, "result": (result or "")[:500], "completed_at": now_datetime()},
        update_modified=False,
    )
    frappe.db.commit()
    return {"ok": True}


@frappe.whitelist(methods=["POST"])
def send_command(device=None, room=None, command_type=None, params=None):
    """Admin ra lệnh cho một máy hoặc cả phòng (fan-out thành lệnh riêng từng máy)."""
    if not frappe.has_permission(DOCTYPE, "create"):
        frappe.throw("Không có quyền gửi lệnh", frappe.PermissionError)
    if command_type not in COMMAND_TYPES:
        frappe.throw(f"Loại lệnh không hợp lệ: {command_type}")
    if not device and not room:
        frappe.throw("Cần device hoặc room")

    if device:
        targets = [device]
    else:
        targets = frappe.get_all(
            DEVICE_DOCTYPE, filters={"room": room, "status": "Active"}, pluck="name"
        )
    if not targets:
        frappe.throw("Không có máy nào khớp")

    if isinstance(params, str):
        params = frappe.parse_json(params)

    created = []
    for target in targets:
        doc = frappe.get_doc(
            {
                "doctype": DOCTYPE,
                "device": target,
                "command_type": command_type,
                "params": params or {},
                "status": "Pending",
                "issued_by": frappe.session.user,
                "issued_at": now_datetime(),
            }
        )
        doc.insert(ignore_permissions=True)
        created.append(doc.name)

    frappe.db.commit()
    return {"ok": True, "created": created, "count": len(created)}


@frappe.whitelist()
def list_commands(device=None, limit=50):
    if not frappe.has_permission(DOCTYPE, "read"):
        frappe.throw("Không có quyền xem lệnh", frappe.PermissionError)

    filters = {"device": device} if device else {}
    return frappe.get_all(
        DOCTYPE,
        filters=filters,
        fields=[
            "name", "device", "command_type", "status", "params",
            "issued_by", "issued_at", "sent_at", "completed_at", "result", "attempts",
        ],
        order_by="creation desc",
        limit_page_length=cint(limit) or 50,
    )


def has_pending_commands(device_name: str) -> bool:
    return bool(
        frappe.db.exists(DOCTYPE, {"device": device_name, "status": ["in", ["Pending", "Sent"]]})
    )
