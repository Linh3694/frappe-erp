"""Ingest event từ FaceID Controller + bridge ERP Time Attendance."""

from __future__ import annotations

import json

import frappe


ATTENDANCE_EVENT_TYPES = frozenset(
    {"attendance", "checkout_ok", "pickup_ok", "checkout_deny", "pickup_deny"}
)


@frappe.whitelist(methods=["POST"])
def ingest_events(events=None):
    """
    Nhận batch event từ controller worker.
    Auth: API key service user (Authorization: token key:secret).
    """
    if isinstance(events, str):
        events = json.loads(events)
    if not isinstance(events, list):
        events = frappe.parse_json(events) if events else []
    accepted = []
    for ev in events:
        try:
            if _ingest_one(ev):
                accepted.append(ev.get("id"))
        except Exception:
            frappe.log_error(
                title="FaceID ingest event",
                message=frappe.get_traceback(),
            )
    frappe.db.commit()
    return {"ok": True, "accepted_ids": accepted}


def _ingest_one(ev: dict) -> bool:
    serial_key = ev.get("serial_key")
    if not serial_key:
        serial_key = f"{ev.get('device_id')}:{ev.get('serial_no')}"
    if frappe.db.exists("FaceID Gate Event", {"serial_key": serial_key}):
        return True

    device_name = None
    if ev.get("device_ip"):
        device_name = frappe.db.get_value(
            "FaceID Device", {"ip": ev["device_ip"]}, "name"
        )

    doc = frappe.get_doc(
        {
            "doctype": "FaceID Gate Event",
            "serial_key": serial_key,
            "controller_event_id": ev.get("id"),
            "device": device_name,
            "serial_no": ev.get("serial_no"),
            "event_type": ev.get("event_type"),
            "external_code": ev.get("employee_no"),
            "occurred_at": ev.get("occurred_at") or frappe.utils.now(),
            "raw_payload": ev.get("payload") or {},
        }
    )
    doc.insert(ignore_permissions=True)

    if ev.get("event_type") in ATTENDANCE_EVENT_TYPES and ev.get("employee_no"):
        bridged = _bridge_attendance(ev)
        if bridged:
            frappe.db.set_value(
                "FaceID Gate Event", doc.name, "bridged_attendance", 1, update_modified=False
            )
    return True


def _bridge_attendance(ev: dict) -> bool:
    """Bridge sang ERP Time Attendance + Parent Portal notification."""
    from erp.api.attendance.hikvision import process_single_attendance_event

    payload = ev.get("payload") or {}
    if isinstance(payload, str):
        payload = json.loads(payload)
    inner = payload.get("AccessControllerEvent") or payload
    if isinstance(inner, str):
        inner = json.loads(inner)

    employee_code = ev.get("employee_no") or inner.get("employeeNoString") or inner.get("employeeNo")
    timestamp = inner.get("dateTime") or ev.get("occurred_at")
    device_id = inner.get("ipAddress") or ev.get("device_ip")
    device_name = inner.get("deviceName") or ev.get("device_name")

    event_data = {
        "employee_code": employee_code,
        "employee_name": inner.get("name") or employee_code,
        "timestamp": timestamp,
        "device_id": device_id,
        "device_name": device_name,
        "event_type": ev.get("event_type"),
        "sub_event_type": inner.get("subEventType"),
        "similarity": inner.get("similarity"),
        "face_id_name": inner.get("name"),
    }
    return bool(process_single_attendance_event(event_data))
