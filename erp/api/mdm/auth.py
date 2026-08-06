"""Xác thực per-device cho MDM agent.

Không dùng API key của Frappe User: mỗi máy học sinh là một `MDM Device`, tạo
User cho từng máy là sai mô hình. Agent gửi `Authorization: token <key>:<secret>`,
ở đây đối chiếu trực tiếp với bản ghi thiết bị.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

import frappe

TOKEN_KEY_BYTES = 16
TOKEN_SECRET_BYTES = 32


def hash_secret(secret: str) -> str:
    """Token là chuỗi ngẫu nhiên 32 byte nên SHA-256 là đủ (không phải mật khẩu người dùng)."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def generate_token_pair() -> tuple[str, str]:
    return secrets.token_urlsafe(TOKEN_KEY_BYTES), secrets.token_urlsafe(TOKEN_SECRET_BYTES)


def parse_authorization_header() -> tuple[str, str] | None:
    header = frappe.get_request_header("Authorization") or ""
    if not header.lower().startswith("token "):
        return None
    raw = header[6:].strip()
    if ":" not in raw:
        return None
    key, secret = raw.split(":", 1)
    key, secret = key.strip(), secret.strip()
    if not key or not secret:
        return None
    return key, secret


def get_authenticated_device() -> "frappe.Document":
    """Trả về `MDM Device` tương ứng token, hoặc ném 401/403.

    Thiết bị `Disabled`/`Retired` bị từ chối — đây là cách thu hồi một máy mà
    không cần chạm vào WireGuard.
    """
    parsed = parse_authorization_header()
    if not parsed:
        _throw_unauthorized("Thiếu hoặc sai định dạng header Authorization")
    key, secret = parsed

    name = frappe.db.get_value("MDM Device", {"token_key": key}, "name")
    if not name:
        _throw_unauthorized("Token không hợp lệ")

    device = frappe.get_doc("MDM Device", name)
    if not hmac.compare_digest(device.token_secret_hash or "", hash_secret(secret)):
        _throw_unauthorized("Token không hợp lệ")

    if device.status != "Active":
        frappe.local.response["http_status_code"] = 403
        frappe.throw(f"Thiết bị đang ở trạng thái {device.status}", frappe.PermissionError)

    return device


def client_ip() -> str | None:
    return getattr(frappe.local, "request_ip", None)


def _throw_unauthorized(msg: str):
    frappe.local.response["http_status_code"] = 401
    frappe.throw(msg, frappe.AuthenticationError)
