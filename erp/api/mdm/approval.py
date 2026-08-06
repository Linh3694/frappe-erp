"""Duyệt / từ chối yêu cầu enroll — hành động của admin trên Admin Web.

Duyệt là lúc máy được ghép vào sổ tài sản và được cấp danh tính. Trước đó nó
chỉ là một dòng trong hàng đợi, không có quyền gì.
"""

from __future__ import annotations

import frappe
from frappe.utils import cint, now_datetime

from erp.api.mdm.auth import generate_token_pair, hash_secret

REQUEST_DOCTYPE = "MDM Enrollment Request"
DEVICE_DOCTYPE = "MDM Device"
ASSET_DOCTYPE = "ERP Inventory Device"


@frappe.whitelist()
def list_pending(limit=100):
    """Hàng đợi chờ duyệt, kèm gợi ý tài sản khớp serial."""
    _check_permission("read")

    requests = frappe.get_all(
        REQUEST_DOCTYPE,
        filters={"status": "Pending"},
        fields=[
            "name",
            "serial_number",
            "hostname",
            "os_version",
            "specs_summary",
            "source_ip",
            "first_seen",
            "last_seen",
            "known_serial",
        ],
        order_by="last_seen desc",
        limit_page_length=cint(limit) or 100,
    )

    for req in requests:
        # Gợi ý ghép sẵn: serial trùng sổ tài sản thì admin bấm Duyệt là xong
        asset = frappe.db.get_value(
            ASSET_DOCTYPE, {"serial": req["serial_number"]}, ["name", "name_display"], as_dict=True
        )
        req["suggested_asset"] = asset.name if asset else None
        req["suggested_asset_name"] = asset.name_display if asset else None
        if req["known_serial"]:
            req["existing_device"] = frappe.db.get_value(
                DEVICE_DOCTYPE, {"serial_number": req["serial_number"]}, "name"
            )
    return requests


@frappe.whitelist(methods=["POST"])
def approve_enrollment(request_id=None, asset=None):
    """Duyệt: ghép tài sản, tạo/tái dùng MDM Device, sinh token cho agent lấy.

    Gọi lại trên một request đã Approved = **re-approve**: cấp token mới cho máy
    (dùng khi agent mất state.json). Bản ghi thiết bị và lịch sử giữ nguyên.
    """
    _check_permission("write")
    return _do_approve(request_id, asset=asset, approved_by=frappe.session.user)


def auto_approve(request_id: str, asset: str | None = None):
    """Tự duyệt serial đã biết — chỉ gọi từ server, KHÔNG whitelist.

    Tách khỏi hàm whitelisted có chủ đích: nếu để cờ "bỏ qua kiểm quyền" thành
    tham số của một endpoint public thì ai cũng tự duyệt được máy của mình.
    """
    return _do_approve(request_id, asset=asset, approved_by="Administrator")


def _do_approve(request_id: str | None, asset: str | None, approved_by: str):
    if not request_id:
        frappe.throw("Thiếu request_id")

    req = frappe.get_doc(REQUEST_DOCTYPE, request_id)
    if req.status == "Rejected":
        frappe.throw("Yêu cầu này đã bị từ chối. Máy phải check-in lại.")

    asset = asset or req.linked_asset or _match_asset(req.serial_number)

    device = _get_or_create_device(req, asset)

    token_key, token_secret = generate_token_pair()
    device.token_key = token_key
    device.token_secret_hash = hash_secret(token_secret)
    device.status = "Active"
    device.save(ignore_permissions=True)

    req.status = "Approved"
    req.linked_device = device.name
    req.linked_asset = asset
    req.approved_by = approved_by
    req.approved_on = now_datetime()
    # Bản rõ nằm đây tới khi agent lấy đúng một lần rồi bị xóa
    req.pending_token_secret = token_secret
    req.token_delivered_on = None
    req.save(ignore_permissions=True)
    frappe.db.commit()

    return {
        "ok": True,
        "device": device.name,
        "asset": asset,
        "serial_number": device.serial_number,
        "reused_device": bool(device.get("_reused")),
    }


@frappe.whitelist(methods=["POST"])
def reject_enrollment(request_id=None, reason=None, block_serial=0):
    """Từ chối. Bật block_serial nếu không muốn máy đó quay lại hàng đợi."""
    _check_permission("write")

    if not request_id:
        frappe.throw("Thiếu request_id")

    req = frappe.get_doc(REQUEST_DOCTYPE, request_id)
    if req.status == "Approved":
        frappe.throw(
            "Yêu cầu đã được duyệt. Muốn thu hồi máy thì đặt MDM Device sang "
            "Disabled/Retired, không từ chối ở đây."
        )

    req.status = "Rejected"
    req.reject_reason = reason
    req.blocked = cint(block_serial)
    req.pending_token_secret = None
    req.save(ignore_permissions=True)
    frappe.db.commit()

    return {"ok": True, "blocked": bool(req.blocked)}


def _get_or_create_device(req, asset):
    """Tái dùng bản ghi theo serial — máy cài lại Windows không được sinh trùng."""
    existing = frappe.db.get_value(DEVICE_DOCTYPE, {"serial_number": req.serial_number}, "name")

    if existing:
        device = frappe.get_doc(DEVICE_DOCTYPE, existing)
        device.set("_reused", True)
    else:
        device = frappe.new_doc(DEVICE_DOCTYPE)
        device.serial_number = req.serial_number
        device.enrolled_on = now_datetime()

    device.device_name = req.hostname or device.device_name
    device.os_version = req.os_version or device.os_version
    device.last_ip = req.source_ip
    device.hardware_snapshot = req.specs_summary or device.hardware_snapshot
    if asset:
        device.inventory_device = asset
    return device


def _match_asset(serial_number: str) -> str | None:
    return frappe.db.get_value(ASSET_DOCTYPE, {"serial": serial_number}, "name")


def _check_permission(ptype: str):
    if not frappe.has_permission(DEVICE_DOCTYPE, ptype):
        frappe.throw("Không có quyền duyệt enroll thiết bị", frappe.PermissionError)
