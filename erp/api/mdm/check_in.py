"""Bootstrap enroll: agent check-in vào hàng đợi chờ duyệt, rồi hỏi kết quả.

Mô hình: agent **không biết trước danh tính gì**. Nó tự sinh keypair, báo danh
bằng serial + cấu hình, rồi chờ admin duyệt. Token riêng của máy chỉ sinh ra
lúc duyệt và agent tự kéo về ở lần poll kế tiếp.

Hai endpoint này **public** (allow_guest) vì lúc này agent chưa có danh tính gì
để xác thực. Cổng chặn gồm ba lớp: site key chung nhúng MSI, rate-limit theo
IP, và blocklist serial. Cổng tin cậy thật là nút Duyệt của admin — ba lớp trên
chỉ để hàng đợi không bị rác.
"""

from __future__ import annotations

import hashlib
import json
import secrets

import frappe
from frappe.utils import cint, now_datetime

from erp.mdm.doctype.mdm_enroll_settings.mdm_enroll_settings import get_settings

REQUEST_DOCTYPE = "MDM Enrollment Request"
DEVICE_DOCTYPE = "MDM Device"

DEFAULT_POLL_INTERVAL_SEC = 30
DEFAULT_RATE_LIMIT_PER_HOUR = 120


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


@frappe.whitelist(allow_guest=True, methods=["POST"])
def check_in(
    serial_number=None,
    hostname=None,
    os_version=None,
    specs_summary=None,
    agent_pubkey=None,
    agent_version=None,
):
    """Agent báo danh. Trả về check_in_id + secret để hỏi trạng thái duyệt."""
    settings = get_settings()
    if not cint(settings.check_in_enabled):
        _throw(403, "Hàng đợi check-in đang đóng")

    _verify_site_key(settings)

    source_ip = getattr(frappe.local, "request_ip", None)
    _rate_limit(source_ip, settings)

    serial_number = (serial_number or "").strip()
    if not serial_number:
        _throw(400, "Thiếu serial_number")
    if not agent_pubkey:
        _throw(400, "Thiếu agent_pubkey")

    if _is_blocked(serial_number):
        _throw(403, "Serial này đã bị chặn. Liên hệ IT.")

    if isinstance(specs_summary, str):
        try:
            specs_summary = json.loads(specs_summary)
        except json.JSONDecodeError:
            specs_summary = {"raw": specs_summary[:500]}

    known_serial = bool(
        frappe.db.exists(DEVICE_DOCTYPE, {"serial_number": serial_number, "status": "Active"})
    )

    check_in_secret = secrets.token_urlsafe(32)
    now = now_datetime()

    # Idempotent theo (serial + pubkey): agent poll lại/khởi động lại không được
    # sinh thêm hàng trong hàng đợi. Secret xoay mỗi lần check-in, agent luôn giữ
    # bản mới nhất.
    existing = frappe.db.get_value(
        REQUEST_DOCTYPE,
        {"serial_number": serial_number, "agent_pubkey": agent_pubkey, "status": "Pending"},
        "name",
    )

    if existing:
        doc = frappe.get_doc(REQUEST_DOCTYPE, existing)
        doc.hostname = hostname or doc.hostname
        doc.os_version = os_version or doc.os_version
        doc.specs_summary = specs_summary or doc.specs_summary
        doc.known_serial = int(known_serial)
        doc.source_ip = source_ip
        doc.last_seen = now
        doc.check_in_secret_hash = hash_secret(check_in_secret)
        doc.save(ignore_permissions=True)
    else:
        doc = frappe.get_doc(
            {
                "doctype": REQUEST_DOCTYPE,
                "serial_number": serial_number,
                "hostname": hostname,
                "os_version": os_version,
                "specs_summary": specs_summary,
                "agent_pubkey": agent_pubkey,
                "check_in_secret_hash": hash_secret(check_in_secret),
                "status": "Pending",
                "known_serial": int(known_serial),
                "source_ip": source_ip,
                "first_seen": now,
                "last_seen": now,
            }
        )
        doc.insert(ignore_permissions=True)

    auto_approved = False
    if known_serial and cint(settings.auto_approve_known_serial):
        # Cài lại Windows hàng loạt: serial đã thuộc một máy Active thì không bắt
        # admin bấm lại từng cái.
        from erp.api.mdm.approval import auto_approve

        auto_approve(doc.name)
        auto_approved = True
        doc.reload()

    frappe.db.commit()

    return {
        "check_in_id": doc.name,
        "check_in_secret": check_in_secret,
        "poll_interval_sec": cint(settings.poll_interval_sec) or DEFAULT_POLL_INTERVAL_SEC,
        "status": doc.status.lower(),
        "known_serial": known_serial,
        "auto_approved": auto_approved,
    }


@frappe.whitelist(allow_guest=True, methods=["GET"])
def enrollment_status(check_in_id=None):
    """Agent hỏi đã được duyệt chưa. Auth: Bearer <check_in_secret>."""
    if not check_in_id:
        _throw(400, "Thiếu check_in_id")

    if not frappe.db.exists(REQUEST_DOCTYPE, check_in_id):
        _throw(404, "Không có yêu cầu enroll này")

    doc = frappe.get_doc(REQUEST_DOCTYPE, check_in_id)
    _verify_check_in_secret(doc)

    if doc.status == "Rejected":
        return {"status": "rejected", "reason": doc.reject_reason}

    if doc.status == "Pending":
        settings = get_settings()
        frappe.db.set_value(
            REQUEST_DOCTYPE, doc.name, "last_seen", now_datetime(), update_modified=False
        )
        frappe.db.commit()
        return {
            "status": "pending",
            "poll_interval_sec": cint(settings.poll_interval_sec) or DEFAULT_POLL_INTERVAL_SEC,
        }

    # Approved — giao token đúng một lần rồi xóa bản rõ khỏi hàng đợi
    secret = doc.get_password("pending_token_secret", raise_exception=False)
    if not secret:
        _throw(
            409,
            "Token đã được giao cho máy này rồi. Nếu agent mất state, dùng "
            "Re-approve trên UI để cấp lại.",
        )

    device = frappe.get_doc(DEVICE_DOCTYPE, doc.linked_device)

    doc.db_set("pending_token_secret", None, update_modified=False)
    doc.db_set("token_delivered_on", now_datetime(), update_modified=False)
    frappe.db.commit()

    return {
        "status": "approved",
        "device_id": device.name,
        "token_key": device.token_key,
        "token_secret": secret,
        "heartbeat_interval_sec": cint(
            frappe.conf.get("mdm_heartbeat_interval_sec", 120)
        ),
        "asset": device.inventory_device,
    }


def _verify_site_key(settings):
    provided = frappe.get_request_header("X-MDM-Site-Key") or ""
    expected = settings.site_check_in_key or ""
    if not expected:
        _throw(503, "Chưa cấu hình site check-in key trong MDM Enroll Settings")
    if not secrets.compare_digest(provided, expected):
        _throw(403, "Site key không hợp lệ")


def _verify_check_in_secret(doc):
    header = frappe.get_request_header("Authorization") or ""
    if not header.lower().startswith("bearer "):
        _throw(401, "Thiếu Bearer token")
    provided = header[7:].strip()
    if not secrets.compare_digest(hash_secret(provided), doc.check_in_secret_hash or ""):
        _throw(401, "check_in_secret không hợp lệ")


def _is_blocked(serial_number: str) -> bool:
    return bool(
        frappe.db.exists(
            REQUEST_DOCTYPE, {"serial_number": serial_number, "blocked": 1, "status": "Rejected"}
        )
    )


def _rate_limit(source_ip: str | None, settings):
    if not source_ip:
        return
    limit = cint(settings.check_in_rate_limit_per_hour) or DEFAULT_RATE_LIMIT_PER_HOUR
    key = f"mdm:check_in:{source_ip}"
    attempts = cint(frappe.cache().get_value(key))
    if attempts >= limit:
        _throw(429, "Quá nhiều lượt check-in từ IP này, thử lại sau")
    frappe.cache().set_value(key, attempts + 1, expires_in_sec=3600)


def _throw(status: int, message: str):
    frappe.local.response["http_status_code"] = status
    exc = frappe.PermissionError if status in (401, 403) else frappe.ValidationError
    frappe.throw(message, exc)
