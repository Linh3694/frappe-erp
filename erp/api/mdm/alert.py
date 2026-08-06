"""Cảnh báo: tháo linh kiện, ổ sắp hỏng, máy mất liên lạc."""

from __future__ import annotations

import frappe
from frappe.utils import cint, now_datetime

DOCTYPE = "MDM Alert"
DEVICE_DOCTYPE = "MDM Device"

# Không heartbeat quá ngần này thì coi như mất liên lạc (máy hỏng, bị gỡ agent,
# hoặc đã nghỉ hè). Rộng hơn hẳn chu kỳ heartbeat để nghỉ cuối tuần không kêu.
OFFLINE_ALERT_DAYS = 3


def raise_alert(device, alert_type, severity, title, detail=None, dedup_key=None):
    """Tạo cảnh báo, bỏ qua nếu cùng sự cố đang mở.

    dedup_key là thứ giữ cho dashboard không biến thành bãi rác: agent gửi
    inventory mỗi giờ, không có nó thì mỗi giờ một cảnh báo "tháo RAM" y hệt.
    """
    dedup_key = dedup_key or f"{alert_type}:{device}:{title}"

    existing = frappe.db.get_value(DOCTYPE, {"dedup_key": dedup_key}, ["name", "status"], as_dict=True)
    if existing:
        if existing.status == "Resolved":
            # Sự cố quay lại sau khi đã đóng → mở lại chính bản ghi đó
            frappe.db.set_value(
                DOCTYPE, existing.name,
                {"status": "Open", "raised_on": now_datetime(), "resolved_on": None},
                update_modified=False,
            )
        return existing.name

    doc = frappe.get_doc(
        {
            "doctype": DOCTYPE,
            "device": device,
            "alert_type": alert_type,
            "severity": severity,
            "title": title,
            "detail": detail,
            "dedup_key": dedup_key,
            "status": "Open",
            "raised_on": now_datetime(),
        }
    )
    doc.insert(ignore_permissions=True)
    return doc.name


@frappe.whitelist()
def list_alerts(status="Open", device=None, limit=200):
    _check_read()
    filters = {}
    if status:
        filters["status"] = status
    if device:
        filters["device"] = device

    return frappe.get_all(
        DOCTYPE,
        filters=filters,
        fields=[
            "name", "device", "alert_type", "severity", "status",
            "title", "detail", "raised_on", "resolved_on",
        ],
        order_by="field(severity,'critical','warning','info'), raised_on desc",
        limit_page_length=cint(limit) or 200,
    )


@frappe.whitelist(methods=["POST"])
def update_alert_status(name=None, status=None):
    if not frappe.has_permission(DOCTYPE, "write"):
        frappe.throw("Không có quyền cập nhật cảnh báo", frappe.PermissionError)
    if status not in ("Open", "Acknowledged", "Resolved"):
        frappe.throw("Trạng thái không hợp lệ")

    updates = {"status": status}
    updates["resolved_on"] = now_datetime() if status == "Resolved" else None
    frappe.db.set_value(DOCTYPE, name, updates)
    frappe.db.commit()
    return {"ok": True}


def check_offline_devices():
    """Scheduled: máy Active mà im lặng quá lâu thì báo IT.

    Đây là lớp bù cho việc phần mềm không chống được admin/boot ngoài: gỡ được
    agent thì gỡ, nhưng không giấu được việc máy ngừng báo cáo.
    """
    stale = frappe.db.sql(
        """SELECT name, device_name, serial_number, last_heartbeat
           FROM `tabMDM Device`
           WHERE status = 'Active'
             AND (last_heartbeat IS NULL
                  OR last_heartbeat < DATE_SUB(NOW(), INTERVAL %s DAY))""",
        (OFFLINE_ALERT_DAYS,),
        as_dict=True,
    )

    for device in stale:
        raise_alert(
            device=device.name,
            alert_type="offline",
            severity="warning",
            title=f"Mất liên lạc: {device.device_name or device.serial_number}",
            detail=(
                f"Heartbeat gần nhất: {device.last_heartbeat or 'chưa bao giờ'}. "
                f"Máy tắt dài ngày, hỏng, hoặc agent đã bị gỡ."
            ),
            dedup_key=f"offline:{device.name}",
        )

    # Máy báo cáo lại thì tự đóng cảnh báo, không bắt IT dọn tay
    frappe.db.sql(
        """UPDATE `tabMDM Alert` a
           JOIN `tabMDM Device` d ON d.name = a.device
           SET a.status = 'Resolved', a.resolved_on = NOW()
           WHERE a.alert_type = 'offline' AND a.status != 'Resolved'
             AND d.last_heartbeat >= DATE_SUB(NOW(), INTERVAL %s DAY)""",
        (OFFLINE_ALERT_DAYS,),
    )
    frappe.db.commit()


def _check_read():
    if not frappe.has_permission(DOCTYPE, "read"):
        frappe.throw("Không có quyền xem cảnh báo", frappe.PermissionError)
