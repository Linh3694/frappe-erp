"""Tự đăng ký máy học sinh vào hệ thống MDM.

Luồng: MSI nhúng enrollment token chung → agent gọi `enroll` lần chạy đầu →
nhận token riêng của máy + cấu hình WireGuard → từ đó dùng token riêng.
"""

from __future__ import annotations

import frappe
from frappe.utils import cint, now_datetime

from erp.api.mdm.auth import generate_token_pair, hash_secret
from erp.api.mdm import wireguard

DEFAULT_HEARTBEAT_INTERVAL_SEC = 120
ENROLL_RATE_LIMIT_PER_HOUR = 60


@frappe.whitelist(allow_guest=True, methods=["POST"])
def enroll(
    enroll_token=None,
    serial_number=None,
    device_name=None,
    os_version=None,
    os_build=None,
    wg_pubkey=None,
    agent_version=None,
):
    """Đăng ký máy mới hoặc tái kích hoạt máy đã có (theo serial)."""
    client_ip = getattr(frappe.local, "request_ip", None)
    _rate_limit(client_ip)

    serial_number = (serial_number or "").strip()
    if not enroll_token or not serial_number:
        frappe.local.response["http_status_code"] = 400
        frappe.throw("Thiếu enroll_token hoặc serial_number", frappe.ValidationError)

    token_doc = _get_usable_token(enroll_token)
    inventory_device = _match_inventory_device(serial_number, token_doc)

    existing = frappe.db.get_value(
        "MDM Device", {"serial_number": serial_number}, ["name", "status"], as_dict=True
    )

    token_key, token_secret = generate_token_pair()

    if existing:
        # Máy cài lại Windows sẽ enroll lại — tái dùng bản ghi cũ để không mất
        # lịch sử tài sản và không sinh bản ghi trùng serial.
        if existing.status != "Active":
            frappe.local.response["http_status_code"] = 403
            frappe.throw(
                f"Thiết bị serial {serial_number} đang ở trạng thái {existing.status}, "
                "không thể enroll. Liên hệ IT.",
                frappe.PermissionError,
            )
        device = frappe.get_doc("MDM Device", existing.name)
    else:
        device = frappe.new_doc("MDM Device")
        device.serial_number = serial_number
        device.status = "Active"
        device.enrolled_on = now_datetime()

    device.device_name = device_name or device.device_name
    device.os_version = os_version or device.os_version
    device.os_build = os_build or device.os_build
    device.agent_version = agent_version or device.agent_version
    device.token_key = token_key
    device.token_secret_hash = hash_secret(token_secret)
    device.enroll_token_used = token_doc.name
    device.last_ip = client_ip
    if inventory_device and not device.inventory_device:
        device.inventory_device = inventory_device

    if wg_pubkey:
        device.wg_pubkey = wg_pubkey.strip()
        if not device.wg_ip:
            device.wg_ip = wireguard.allocate_ip()

    device.save(ignore_permissions=True)

    if device.wg_pubkey and device.wg_ip:
        wireguard.add_peer(device.wg_pubkey, device.wg_ip)

    token_doc.db_set("used_count", cint(token_doc.used_count) + 1, update_modified=False)
    frappe.db.commit()

    response = {
        "device_id": device.name,
        "token_key": token_key,
        "token_secret": token_secret,
        "wg_ip": device.wg_ip,
        "heartbeat_interval_sec": cint(
            frappe.conf.get("mdm_heartbeat_interval_sec", DEFAULT_HEARTBEAT_INTERVAL_SEC)
        ),
        "inventory_device": device.inventory_device,
    }
    response.update(wireguard.server_config())
    return response


def _get_usable_token(raw_token: str):
    name = frappe.db.get_value("MDM Enroll Token", {"token": raw_token.strip()}, "name")
    if not name:
        frappe.local.response["http_status_code"] = 401
        frappe.throw("Enrollment token không hợp lệ", frappe.AuthenticationError)

    token_doc = frappe.get_doc("MDM Enroll Token", name)
    if not token_doc.is_usable():
        frappe.local.response["http_status_code"] = 403
        frappe.throw(
            "Enrollment token đã hết hạn, hết lượt hoặc bị tắt", frappe.PermissionError
        )
    return token_doc


def _match_inventory_device(serial_number: str, token_doc) -> str | None:
    """Sổ tài sản là nguồn chuẩn: máy không có trong sổ thì không được enroll.

    Ngoại lệ duy nhất là token bật `allow_unknown_serial` (dùng cho máy thử
    nghiệm) — để agent tự sinh bản ghi tài sản sẽ làm bẩn sổ.
    """
    inventory = frappe.db.get_value("ERP Inventory Device", {"serial": serial_number}, "name")
    if inventory:
        return inventory

    if cint(token_doc.allow_unknown_serial):
        frappe.logger("mdm").warning(
            f"Enroll serial {serial_number} không có trong sổ tài sản "
            f"(token {token_doc.name} cho phép serial lạ)"
        )
        return None

    frappe.local.response["http_status_code"] = 412
    frappe.throw(
        f"Serial {serial_number} chưa có trong sổ tài sản (ERP Inventory Device). "
        "Khai báo thiết bị vào sổ trước khi cài agent.",
        frappe.ValidationError,
    )


def _rate_limit(client_ip: str | None):
    """Token enroll là bí mật dùng chung — chặn dò token bằng giới hạn theo IP."""
    if not client_ip:
        return
    cache_key = f"mdm:enroll_attempts:{client_ip}"
    attempts = cint(frappe.cache().get_value(cache_key))
    if attempts >= ENROLL_RATE_LIMIT_PER_HOUR:
        frappe.local.response["http_status_code"] = 429
        frappe.throw("Quá nhiều lượt enroll từ IP này, thử lại sau", frappe.ValidationError)
    frappe.cache().set_value(cache_key, attempts + 1, expires_in_sec=3600)
