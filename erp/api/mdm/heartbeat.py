"""Heartbeat: agent báo còn sống + nhận tín hiệu có lệnh đang chờ."""

from __future__ import annotations

import frappe
from frappe.utils import cint, now_datetime

from erp.api.mdm.auth import client_ip, get_authenticated_device
from erp.api.mdm.enroll import DEFAULT_HEARTBEAT_INTERVAL_SEC

# Ngưỡng coi máy là mất liên tục (dùng cho dashboard GĐ1 và cảnh báo GĐ4)
OFFLINE_AFTER_MINUTES = 15


@frappe.whitelist(allow_guest=True, methods=["POST"])
def heartbeat(agent_version=None, os_version=None, os_build=None):
    device = get_authenticated_device()

    updates = {
        "last_heartbeat": now_datetime(),
        "last_ip": client_ip(),
    }
    if agent_version:
        updates["agent_version"] = agent_version
    if os_version:
        updates["os_version"] = os_version
    if os_build:
        updates["os_build"] = os_build

    # db_set thay vì save(): heartbeat chạy mỗi 2 phút trên hàng trăm máy,
    # không cần chạy validate/hooks mỗi lần.
    frappe.db.set_value("MDM Device", device.name, updates, update_modified=False)
    frappe.db.commit()

    return {
        "ok": True,
        "device_id": device.name,
        "server_time": now_datetime().isoformat(),
        "heartbeat_interval_sec": cint(
            frappe.conf.get("mdm_heartbeat_interval_sec", DEFAULT_HEARTBEAT_INTERVAL_SEC)
        ),
        # GĐ2 sẽ nối vào hàng đợi MDM Command; giữ field từ bây giờ để agent
        # không phải đổi hợp đồng API khi command queue lên.
        "has_pending_commands": False,
    }
