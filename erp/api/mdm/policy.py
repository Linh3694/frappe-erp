"""Chính sách áp theo phòng/campus/toàn trường — hiện mới có hình nền.

Agent poll `get_policy` và tự áp. Không đẩy từ server xuống: máy tắt/bật liên
tục, push chỉ tạo ảo giác là đã áp xong.
"""

from __future__ import annotations

import frappe
from frappe.utils import cint

from erp.api.mdm.auth import get_authenticated_device

DOCTYPE = "MDM Policy"


@frappe.whitelist(allow_guest=True, methods=["GET", "POST"])
def get_policy():
    """Chính sách hiệu lực cho chính máy đang gọi."""
    device = get_authenticated_device()
    policy = _resolve_policy(device)

    if not policy:
        return {"wallpaper_url": None, "wallpaper_locked": False, "policy": None}

    return {
        "policy": policy.name,
        "wallpaper_url": frappe.utils.get_url(policy.wallpaper) if policy.wallpaper else None,
        "wallpaper_locked": bool(cint(policy.wallpaper_locked)),
    }


def _resolve_policy(device):
    """Phòng thắng Campus, Campus thắng Toàn trường; cùng mức thì priority lớn thắng.

    Máy chưa gắn phòng vẫn nhận được chính sách toàn trường — nếu không thì máy
    mới cài sẽ không có nền cho tới khi ai đó nhớ ra phải gán phòng.
    """
    candidates = []

    if device.room:
        candidates += frappe.get_all(
            DOCTYPE,
            filters={"is_active": 1, "scope": "Phòng", "room": device.room},
            fields=["name", "wallpaper", "wallpaper_locked", "priority"],
        )
    if not candidates and device.campus_id:
        candidates += frappe.get_all(
            DOCTYPE,
            filters={"is_active": 1, "scope": "Campus", "campus_id": device.campus_id},
            fields=["name", "wallpaper", "wallpaper_locked", "priority"],
        )
    if not candidates:
        candidates += frappe.get_all(
            DOCTYPE,
            filters={"is_active": 1, "scope": "Toàn trường"},
            fields=["name", "wallpaper", "wallpaper_locked", "priority"],
        )

    if not candidates:
        return None
    candidates.sort(key=lambda p: cint(p.priority), reverse=True)
    return frappe._dict(candidates[0])


@frappe.whitelist()
def list_policies():
    if not frappe.has_permission(DOCTYPE, "read"):
        frappe.throw("Không có quyền xem chính sách", frappe.PermissionError)

    policies = frappe.get_all(
        DOCTYPE,
        fields=["name", "title", "scope", "campus_id", "room", "wallpaper",
                "wallpaper_locked", "priority", "is_active"],
        order_by="is_active desc, priority desc",
    )
    for p in policies:
        p["wallpaper_url"] = frappe.utils.get_url(p["wallpaper"]) if p["wallpaper"] else None
    return policies


@frappe.whitelist(methods=["POST"])
def apply_policy_now(policy=None, room=None):
    """Đẩy lệnh run_policy để máy áp ngay thay vì đợi chu kỳ poll."""
    from erp.api.mdm.command import send_command

    if not frappe.has_permission(DOCTYPE, "write"):
        frappe.throw("Không có quyền áp chính sách", frappe.PermissionError)

    if room:
        return send_command(room=room, command_type="run_policy", params={"policy": policy})

    targets = frappe.get_all("MDM Device", filters={"status": "Active"}, pluck="name")
    created = []
    for target in targets:
        created += send_command(
            device=target, command_type="run_policy", params={"policy": policy}
        )["created"]
    return {"ok": True, "count": len(created)}
