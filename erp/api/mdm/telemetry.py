"""Nhận kiểm kê phần cứng và telemetry động từ agent.

Hai thứ khác nhau về nhịp và về ý nghĩa:
- **Inventory** đổi rất hiếm (thay RAM, thay ổ) → so sánh với ảnh chụp cũ và
  cảnh báo khi lệch. Đây chính là giá trị quản lý tài sản nhà trường cần nhất.
- **Telemetry** đổi liên tục → nhận theo lô, có TTL để không phình DB.
"""

from __future__ import annotations

import json

import frappe
from frappe.utils import cint, flt, now_datetime

from erp.api.mdm.alert import raise_alert
from erp.api.mdm.auth import client_ip, get_authenticated_device

TELEMETRY_DOCTYPE = "MDM Telemetry"
TELEMETRY_TTL_DAYS = 30


@frappe.whitelist(allow_guest=True, methods=["POST"])
def ingest_inventory(inventory=None):
    """Agent gửi kiểm kê đầy đủ. Lệch so với lần trước thì sinh cảnh báo."""
    device = get_authenticated_device()

    if isinstance(inventory, str):
        inventory = frappe.parse_json(inventory)
    if not isinstance(inventory, dict):
        frappe.local.response["http_status_code"] = 400
        frappe.throw("inventory phải là object", frappe.ValidationError)

    previous = _load_snapshot(device.hardware_snapshot)
    changes = _diff_hardware(previous, inventory) if previous else []

    frappe.db.set_value(
        "MDM Device",
        device.name,
        {
            "hardware_snapshot": json.dumps(inventory, ensure_ascii=False),
            "os_version": inventory.get("os", {}).get("caption") or device.os_version,
            "os_build": inventory.get("os", {}).get("build") or device.os_build,
            "last_ip": client_ip(),
        },
        update_modified=False,
    )

    for change in changes:
        raise_alert(
            device=device.name,
            alert_type="hardware_change",
            severity="critical",
            title=f"Nghi tháo/đổi linh kiện: {change['what']}",
            detail=f"Trước: {change['before']}\nSau: {change['after']}",
            # Cùng một thay đổi chưa xử lý thì không đẻ cảnh báo mới mỗi lần gửi
            dedup_key=f"hwchange:{device.name}:{change['what']}:{change['after']}",
        )

    frappe.db.commit()
    return {"ok": True, "changes": len(changes)}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def ingest_telemetry(samples=None):
    """Nhận lô mẫu telemetry. Agent gom 1–5 phút mới gửi một lần."""
    device = get_authenticated_device()

    if isinstance(samples, str):
        samples = frappe.parse_json(samples)
    if isinstance(samples, dict):
        samples = [samples]
    if not isinstance(samples, list):
        frappe.local.response["http_status_code"] = 400
        frappe.throw("samples phải là mảng", frappe.ValidationError)

    accepted = 0
    worst_disk = None
    for sample in samples[:500]:
        try:
            doc = frappe.get_doc(
                {
                    "doctype": TELEMETRY_DOCTYPE,
                    "device": device.name,
                    "captured_at": sample.get("captured_at") or now_datetime(),
                    "cpu_pct": flt(sample.get("cpu_pct")),
                    "ram_pct": flt(sample.get("ram_pct")),
                    "disk_free_gb": flt(sample.get("disk_free_gb")),
                    "disk_total_gb": flt(sample.get("disk_total_gb")),
                    "disk_health": sample.get("disk_health"),
                    "battery_pct": cint(sample.get("battery_pct")),
                    "charging": cint(sample.get("charging")),
                    "uptime_sec": cint(sample.get("uptime_sec")),
                    "cpu_temp": flt(sample.get("cpu_temp")) or None,
                }
            )
            doc.insert(ignore_permissions=True)
            accepted += 1
            if sample.get("disk_health") in ("warning", "critical"):
                worst_disk = sample.get("disk_health")
        except Exception:
            # Một mẫu hỏng không được làm mất cả lô
            frappe.log_error(title="MDM ingest telemetry", message=frappe.get_traceback())

    if worst_disk:
        raise_alert(
            device=device.name,
            alert_type="disk_health",
            severity="critical" if worst_disk == "critical" else "warning",
            title=f"Ổ đĩa báo tình trạng {worst_disk}",
            detail="SMART báo ổ có nguy cơ hỏng. Sao lưu và lên kế hoạch thay.",
            dedup_key=f"disk:{device.name}:{worst_disk}",
        )

    frappe.db.set_value(
        "MDM Device", device.name, "last_heartbeat", now_datetime(), update_modified=False
    )
    frappe.db.commit()
    return {"ok": True, "accepted": accepted}


@frappe.whitelist()
def device_telemetry(device=None, limit=200):
    """Chuỗi telemetry gần nhất cho biểu đồ ở trang chi tiết máy."""
    if not frappe.has_permission("MDM Device", "read"):
        frappe.throw("Không có quyền xem telemetry", frappe.PermissionError)
    if not device:
        frappe.throw("Thiếu device")

    rows = frappe.get_all(
        TELEMETRY_DOCTYPE,
        filters={"device": device},
        fields=[
            "captured_at", "cpu_pct", "ram_pct", "disk_free_gb", "disk_total_gb",
            "battery_pct", "charging", "uptime_sec", "cpu_temp", "disk_health",
        ],
        order_by="captured_at desc",
        limit_page_length=cint(limit) or 200,
    )
    rows.reverse()
    return rows


def cleanup_old_telemetry():
    """Scheduled: xóa telemetry quá hạn. Đặt TTL từ đầu, không đợi DB phình rồi mới lo."""
    frappe.db.sql(
        """DELETE FROM `tabMDM Telemetry`
           WHERE captured_at < DATE_SUB(NOW(), INTERVAL %s DAY)""",
        (TELEMETRY_TTL_DAYS,),
    )
    frappe.db.commit()


def _load_snapshot(raw) -> dict | None:
    if not raw:
        return None
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def _diff_hardware(before: dict, after: dict) -> list[dict]:
    """So sánh những thứ mất đi thì đáng ngờ. Thêm vào (nâng cấp) không cảnh báo.

    Chỉ so tổng dung lượng và serial ổ: đủ để bắt tháo RAM/đổi ổ mà không báo
    giả mỗi lần Windows đếm lại thiết bị theo thứ tự khác.
    """
    changes = []

    ram_before = flt((before.get("ram") or {}).get("total_gb"))
    ram_after = flt((after.get("ram") or {}).get("total_gb"))
    if ram_before and ram_after and ram_after < ram_before - 0.5:
        changes.append({"what": "RAM", "before": f"{ram_before} GB", "after": f"{ram_after} GB"})

    def disk_serials(snapshot):
        return {d.get("serial") for d in (snapshot.get("disks") or []) if d.get("serial")}

    missing = disk_serials(before) - disk_serials(after)
    if missing:
        changes.append(
            {
                "what": "Ổ đĩa",
                "before": ", ".join(sorted(disk_serials(before))),
                "after": ", ".join(sorted(disk_serials(after))) or "(không thấy ổ nào)",
            }
        )

    board_before = (before.get("board") or {}).get("serial")
    board_after = (after.get("board") or {}).get("serial")
    if board_before and board_after and board_before != board_after:
        changes.append({"what": "Mainboard", "before": board_before, "after": board_after})

    return changes
