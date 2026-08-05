"""Đồng bộ FaceID Device giữa Frappe và controller local."""

from __future__ import annotations

import frappe
from frappe.utils import cint

from erp.utils.faceid_gateway import gateway_delete, gateway_get, gateway_post, gateway_put


def push_device_to_controller(doc) -> dict:
    """Đẩy metadata + credential xuống controller local."""
    if frappe.flags.get("faceid_skip_controller_push"):
        return {}

    ip = str(doc.ip).split("/")[0]
    body: dict = {
        "name": doc.device_name,
        "ip": ip,
        "model": doc.model,
        "user": doc.username,
        "https": bool(doc.https),
        "auth": doc.auth_mode or "auto",
    }
    pwd = doc.get_password("password")
    if pwd:
        body["password"] = pwd

    if doc.controller_device_id:
        res = gateway_put(f"/api/devices/{doc.controller_device_id}", body)
    else:
        res = gateway_post("/api/devices", body)

    device = res.get("device") if isinstance(res, dict) else None
    cid = (device or {}).get("id") if device else res.get("id") if isinstance(res, dict) else None
    values: dict = {"push_status": "synced", "last_error": None}
    if cid and int(cid) != cint(doc.controller_device_id):
        values["controller_device_id"] = int(cid)
        doc.controller_device_id = int(cid)
    frappe.db.set_value("FaceID Device", doc.name, values, update_modified=False)
    doc.push_status = "synced"
    return device or res or {}


def delete_device_from_controller(controller_device_id: int | None) -> None:
    if not controller_device_id:
        return
    gateway_delete(f"/api/devices/{controller_device_id}")


def _extract_isapi_count(data, *keys: str) -> int | None:
    if not isinstance(data, dict):
        return None
    for key in keys:
        if key in data and data[key] is not None:
            try:
                return int(data[key])
            except (TypeError, ValueError):
                pass
    for val in data.values():
        if isinstance(val, dict):
            found = _extract_isapi_count(val, *keys)
            if found is not None:
                return found
    return None


def _error_status(err: Exception) -> str:
    """Lỗi cấu hình (4xx từ controller) không có nghĩa là máy tắt."""
    resp = getattr(err, "response", None)
    code = getattr(resp, "status_code", None)
    if code and 400 <= code < 500:
        return "unknown"
    return "offline"


def mark_device_offline(doc_name: str, error: Exception | str | None = None) -> None:
    """Ghi nhận không đọc được trạng thái: offline nếu mất kết nối, unknown nếu lỗi cấu hình."""
    status = _error_status(error) if isinstance(error, Exception) else "offline"
    frappe.db.set_value(
        "FaceID Device",
        doc_name,
        {
            "status": status,
            "last_status_at": frappe.utils.now(),
            "last_error": str(error or "")[:500] or None,
        },
        update_modified=False,
    )


def fetch_device_status(doc) -> dict:
    """Đọc trạng thái máy từ controller và cache vào doc."""
    ip = str(doc.ip).split("/")[0]
    try:
        res = gateway_get(f"/api/devices/{ip}/status")
    except Exception as e:
        mark_device_offline(doc.name, e)
        raise
    status = res.get("status") or {}
    person_count = _extract_isapi_count(status.get("persons") or {}, "userNumber", "recordNum")
    face_count = _extract_isapi_count(
        status.get("faces") or {},
        # Terminal Hikvision trả recordDataNumber cho FDLib/Count
        "recordDataNumber",
        "faceLibNum",
        "recordNum",
        "faceNum",
    )
    time_info = status.get("time") or {}
    device_time = time_info.get("localTime") or time_info.get("LocalTime")

    screen_images: dict = {}
    try:
        screen_images = gateway_get(f"/api/devices/{ip}/screen-images") or {}
    except Exception:
        frappe.log_error(
            title=f"FaceID screen images {doc.name}",
            message=frappe.get_traceback(),
        )

    now = frappe.utils.now()
    # Cột Int của Frappe là NOT NULL — ghi None sẽ ném IntegrityError và làm
    # máy bị đánh nhầm thành offline, nên chỉ ghi field nào đọc được.
    values: dict = {
        "last_status_at": now,
        # Đọc được ISAPI nghĩa là terminal đang sống
        "status": "online",
        "last_seen": now,
        "last_error": None,
    }
    if person_count is not None:
        values["person_count"] = person_count
    if face_count is not None:
        values["face_count"] = face_count
    if device_time:
        values["device_time"] = device_time
    frappe.db.set_value("FaceID Device", doc.name, values, update_modified=False)

    return {
        "status": "online",
        "last_seen": now,
        "last_status_at": now,
        "person_count": person_count,
        "face_count": face_count,
        "device_time": device_time,
        "time_zone": time_info.get("timeZone") or time_info.get("TimeZone"),
        "raw": status,
        "screen_images": screen_images,
    }
