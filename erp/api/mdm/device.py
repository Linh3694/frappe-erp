"""Danh sách máy đã đăng ký — đủ để kiểm chứng enroll/heartbeat từ Admin Web.

Dashboard đầy đủ (inventory, biểu đồ telemetry) thuộc GĐ1-06.
"""

from __future__ import annotations

import frappe
from frappe.utils import cint, get_datetime, now_datetime

DOCTYPE = "MDM Device"

# Quá ngưỡng này mà không heartbeat thì coi là offline. Nới rộng hơn chu kỳ
# heartbeat (2 phút) để một lần lỡ nhịp không làm máy nhấp nháy trên dashboard.
OFFLINE_AFTER_MINUTES = 15


@frappe.whitelist()
def list_devices(status=None, search=None, limit=100):
    if not frappe.has_permission(DOCTYPE, "read"):
        frappe.throw("Không có quyền xem thiết bị MDM", frappe.PermissionError)

    filters = {}
    if status:
        filters["status"] = status

    or_filters = None
    if search:
        or_filters = [
            ["device_name", "like", f"%{search}%"],
            ["serial_number", "like", f"%{search}%"],
        ]

    # limit=0 nghĩa là lấy hết (dùng cho device_summary), không phải "về mặc định 100"
    page_length = cint(limit)
    if page_length < 0:
        page_length = 100

    devices = frappe.get_all(
        DOCTYPE,
        filters=filters,
        or_filters=or_filters,
        fields=[
            "name",
            "device_name",
            "serial_number",
            "inventory_device",
            "inventory_name",
            "room",
            "status",
            "agent_version",
            "os_version",
            "last_heartbeat",
            "last_ip",
            "wg_ip",
            "enrolled_on",
        ],
        order_by="last_heartbeat desc",
        limit_page_length=cint(limit) or 100,
    )

    now = now_datetime()
    for d in devices:
        d["online"] = bool(
            d.get("last_heartbeat")
            and (now - get_datetime(d["last_heartbeat"])).total_seconds()
            < OFFLINE_AFTER_MINUTES * 60
        )
    return devices


@frappe.whitelist()
def device_summary():
    """Thẻ KPI cho trang MDM."""
    if not frappe.has_permission(DOCTYPE, "read"):
        frappe.throw("Không có quyền xem thiết bị MDM", frappe.PermissionError)

    devices = list_devices(limit=0)
    return {
        "total": len(devices),
        "online": sum(1 for d in devices if d["online"]),
        "active": sum(1 for d in devices if d["status"] == "Active"),
        "unlinked": sum(1 for d in devices if not d.get("inventory_device")),
    }
