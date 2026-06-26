"""API quản trị FaceID cho frappe-sis-frontend."""

from __future__ import annotations

import json
from datetime import date

import frappe

from erp.api.faceid.sync_worker import create_device_sync_job
from erp.utils.faceid_gateway import gateway_get, gateway_post


def _ok(data=None, message="OK"):
    return {"success": True, "message": message, "data": data}


def _err(message, data=None):
    return {"success": False, "message": message, "data": data}


# ---- Persons ----


@frappe.whitelist()
def list_persons(person_type=None, campus_id=None, sync_status=None, limit=100, offset=0):
    filters = {}
    if person_type:
        filters["person_type"] = person_type
    if campus_id:
        filters["campus_id"] = campus_id
    if sync_status:
        filters["sync_status"] = sync_status
    rows = frappe.get_all(
        "FaceID Person",
        filters=filters,
        fields=[
            "name",
            "person_type",
            "external_code",
            "display_name",
            "campus_id",
            "work_shift",
            "face_status",
            "sync_status",
            "last_synced_at",
            "last_error",
            "valid_from",
            "valid_to",
        ],
        order_by="modified desc",
        limit=int(limit),
        start=int(offset),
    )
    return _ok(rows)


@frappe.whitelist()
def get_person(name):
    doc = frappe.get_doc("FaceID Person", name)
    data = doc.as_dict()
    data["target_devices"] = [r.device for r in doc.target_devices or []]
    return _ok(data)


@frappe.whitelist()
def save_person(data):
    payload = frappe.parse_json(data) if isinstance(data, str) else data
    name = payload.get("name")
    if name and frappe.db.exists("FaceID Person", name):
        doc = frappe.get_doc("FaceID Person", name)
        doc.update(payload)
    else:
        doc = frappe.get_doc({"doctype": "FaceID Person", **payload})
    doc.set("target_devices", [])
    for dev in payload.get("target_devices") or []:
        doc.append("target_devices", {"device": dev})
    doc.save(ignore_permissions=True)
    return _ok(doc.as_dict())


@frappe.whitelist()
def delete_person(name):
    frappe.delete_doc("FaceID Person", name, ignore_permissions=True)
    return _ok()


@frappe.whitelist()
def resync_person(name):
    create_device_sync_job("upsert_person", "FaceID Person", name, priority=8)
    return _ok(message="Đã xếp hàng sync person")


@frappe.whitelist()
def bulk_enroll_students(campus_id=None, class_id=None):
    """Enroll hàng loạt học sinh từ CRM Student."""
    filters = {}
    if campus_id:
        filters["campus_id"] = campus_id
    students = frappe.get_all(
        "CRM Student",
        filters=filters,
        fields=["name", "student_name", "student_code", "campus_id"],
        limit=5000,
    )
    if class_id:
        class_students = frappe.get_all(
            "SIS Class Student",
            filters={"parent": class_id},
            pluck="student_id",
        )
        students = [s for s in students if s.name in class_students]
    created = 0
    for s in students:
        if frappe.db.exists("FaceID Person", {"external_code": s.student_code}):
            continue
        doc = frappe.get_doc(
            {
                "doctype": "FaceID Person",
                "person_type": "student",
                "external_code": s.student_code,
                "display_name": s.student_name,
                "crm_student": s.name,
                "campus_id": s.campus_id,
            }
        )
        doc.insert(ignore_permissions=True)
        created += 1
    return _ok({"created": created, "total_candidates": len(students)})


@frappe.whitelist()
def bulk_enroll_staff():
    """Enroll nhân viên từ User có employee_code."""
    users = frappe.get_all(
        "User",
        filters={"enabled": 1, "employee_code": ["is", "set"]},
        fields=["name", "full_name", "employee_code"],
        limit=5000,
    )
    created = 0
    for u in users:
        if frappe.db.exists("FaceID Person", {"external_code": u.employee_code}):
            continue
        doc = frappe.get_doc(
            {
                "doctype": "FaceID Person",
                "person_type": "staff",
                "external_code": u.employee_code,
                "display_name": u.full_name or u.name,
                "user": u.name,
            }
        )
        doc.insert(ignore_permissions=True)
        created += 1
    return _ok({"created": created})


@frappe.whitelist()
def bulk_enroll_guardians(campus_id=None):
    guardians = frappe.get_all(
        "CRM Guardian",
        fields=["name", "guardian_name", "guardian_id"],
        limit=5000,
    )
    created = 0
    for g in guardians:
        if not g.guardian_id:
            continue
        if frappe.db.exists("FaceID Person", {"external_code": g.guardian_id}):
            continue
        doc = frappe.get_doc(
            {
                "doctype": "FaceID Person",
                "person_type": "guardian",
                "external_code": g.guardian_id,
                "display_name": g.guardian_name,
                "crm_guardian": g.name,
                "campus_id": campus_id,
            }
        )
        doc.insert(ignore_permissions=True)
        created += 1
    return _ok({"created": created})


# ---- Work Shifts ----


@frappe.whitelist()
def list_work_shifts():
    rows = frappe.get_all(
        "FaceID Work Shift",
        fields=[
            "name",
            "shift_name",
            "device_slot",
            "note",
            "controller_shift_id",
            "sync_status",
            "last_synced_at",
        ],
        order_by="device_slot asc",
    )
    return _ok(rows)


@frappe.whitelist()
def get_work_shift(name):
    doc = frappe.get_doc("FaceID Work Shift", name)
    return _ok(doc.as_dict())


@frappe.whitelist()
def save_work_shift(data):
    payload = frappe.parse_json(data) if isinstance(data, str) else data
    name = payload.get("name")
    periods = payload.pop("periods", [])
    if name and frappe.db.exists("FaceID Work Shift", name):
        doc = frappe.get_doc("FaceID Work Shift", name)
        doc.update(payload)
    else:
        doc = frappe.get_doc({"doctype": "FaceID Work Shift", **payload})
    doc.set("periods", [])
    for p in periods:
        doc.append(
            "periods",
            {
                "weekday": p.get("weekday"),
                "start_time": p.get("start_time"),
                "end_time": p.get("end_time"),
            },
        )
    doc.save(ignore_permissions=True)
    return _ok(doc.as_dict())


@frappe.whitelist()
def delete_work_shift(name):
    doc = frappe.get_doc("FaceID Work Shift", name)
    if int(doc.device_slot) == 1:
        return _err("Không thể xóa ca 24/7 (slot 1)")
    frappe.delete_doc("FaceID Work Shift", name, ignore_permissions=True)
    return _ok()


@frappe.whitelist()
def resync_work_shift(name):
    create_device_sync_job("sync_shift", "FaceID Work Shift", name, priority=7)
    return _ok(message="Đã xếp hàng sync ca")


# ---- Pickup Authorization ----


@frappe.whitelist()
def list_pickup_auth(active_only=0):
    filters = {}
    if int(active_only):
        today = date.today()
        rows = frappe.get_all(
            "FaceID Pickup Authorization",
            filters={"revoked": 0, "valid_from": ["<=", today], "valid_to": [">=", today]},
            fields=[
                "name",
                "guardian",
                "student",
                "valid_from",
                "valid_to",
                "method",
                "revoked",
                "sync_status",
                "controller_auth_id",
            ],
            order_by="modified desc",
        )
        return _ok(_enrich_pickup(rows))
    rows = frappe.get_all(
        "FaceID Pickup Authorization",
        fields=[
            "name",
            "guardian",
            "student",
            "valid_from",
            "valid_to",
            "method",
            "revoked",
            "sync_status",
            "controller_auth_id",
        ],
        order_by="modified desc",
        limit=500,
    )
    return _ok(_enrich_pickup(rows))


def _enrich_pickup(rows):
    for r in rows:
        r["guardian_code"] = frappe.db.get_value("FaceID Person", r.guardian, "external_code")
        r["guardian_name"] = frappe.db.get_value("FaceID Person", r.guardian, "display_name")
        r["student_code"] = frappe.db.get_value("FaceID Person", r.student, "external_code")
        r["student_name"] = frappe.db.get_value("FaceID Person", r.student, "display_name")
    return rows


@frappe.whitelist()
def save_pickup_auth(data):
    payload = frappe.parse_json(data) if isinstance(data, str) else data
    name = payload.get("name")
    if name and frappe.db.exists("FaceID Pickup Authorization", name):
        doc = frappe.get_doc("FaceID Pickup Authorization", name)
        doc.update(payload)
    else:
        doc = frappe.get_doc({"doctype": "FaceID Pickup Authorization", **payload})
    doc.save(ignore_permissions=True)
    return _ok(doc.as_dict())


@frappe.whitelist()
def revoke_pickup_auth(name):
    doc = frappe.get_doc("FaceID Pickup Authorization", name)
    doc.revoked = 1
    doc.save(ignore_permissions=True)
    create_device_sync_job("revoke_pickup", doc.doctype, doc.name, priority=9)
    return _ok(message="Đã thu hồi — sync xuống controller local")


@frappe.whitelist()
def reapply_pickup_auth(name):
    doc = frappe.get_doc("FaceID Pickup Authorization", name)
    doc.revoked = 0
    today = date.today()
    if doc.valid_to and doc.valid_to < today:
        doc.valid_from = today
        doc.valid_to = today
    doc.save(ignore_permissions=True)
    create_device_sync_job("reapply_pickup", doc.doctype, doc.name, priority=9)
    return _ok(message="Đã áp dụng lại — sync xuống controller local")


@frappe.whitelist()
def delete_pickup_auth(name):
    frappe.delete_doc("FaceID Pickup Authorization", name, ignore_permissions=True)
    return _ok()


@frappe.whitelist()
def sync_family_pickup(campus_id=None):
    """Tạo ủy quyền đón từ CRM Family Relationship (ủy quyền đứng)."""
    today = date.today()
    school_year = frappe.db.get_value("SIS School Year", {"is_active": 1}, ["start_date", "end_date"], as_dict=True)
    valid_from = school_year.start_date if school_year else today
    valid_to = school_year.end_date if school_year else today
    rels = frappe.get_all(
        "CRM Family Relationship",
        fields=["student", "guardian"],
        limit=10000,
    )
    created = 0
    for rel in rels:
        g_person = frappe.db.get_value(
            "FaceID Person",
            {"crm_guardian": rel.guardian, "person_type": "guardian"},
            "name",
        )
        s_person = frappe.db.get_value(
            "FaceID Person",
            {"crm_student": rel.student, "person_type": "student"},
            "name",
        )
        if not g_person or not s_person:
            continue
        key = {"guardian": g_person, "student": s_person}
        if frappe.db.exists("FaceID Pickup Authorization", key):
            continue
        doc = frappe.get_doc(
            {
                "doctype": "FaceID Pickup Authorization",
                "guardian": g_person,
                "student": s_person,
                "valid_from": valid_from,
                "valid_to": valid_to,
                "method": "face",
                "revoked": 0,
            }
        )
        doc.insert(ignore_permissions=True)
        created += 1
    return _ok({"created": created})


# ---- Gate Events ----


@frappe.whitelist()
def list_gate_events(
    limit=50,
    event_type=None,
    external_code=None,
    from_date=None,
    to_date=None,
):
    filters = {}
    if event_type:
        filters["event_type"] = event_type
    if external_code:
        filters["external_code"] = external_code
    if from_date:
        filters["occurred_at"] = [">=", from_date]
    rows = frappe.get_all(
        "FaceID Gate Event",
        filters=filters,
        fields=[
            "name",
            "serial_key",
            "device",
            "event_type",
            "external_code",
            "occurred_at",
            "bridged_attendance",
        ],
        order_by="occurred_at desc",
        limit=int(limit),
    )
    return _ok(rows)


# ---- Devices ----


@frappe.whitelist()
def list_devices():
    rows = frappe.get_all(
        "FaceID Device",
        fields=["name", "device_name", "ip", "gate_type", "is_pickup_gate", "status", "last_seen"],
        order_by="device_name asc",
    )
    return _ok(rows)


@frappe.whitelist()
def save_device(data):
    payload = frappe.parse_json(data) if isinstance(data, str) else data
    name = payload.get("name")
    if name and frappe.db.exists("FaceID Device", name):
        doc = frappe.get_doc("FaceID Device", name)
        doc.update(payload)
    else:
        doc = frappe.get_doc({"doctype": "FaceID Device", **payload})
    doc.save(ignore_permissions=True)
    return _ok(doc.as_dict())


@frappe.whitelist()
def provision_device(name):
    create_device_sync_job("provision_device", "FaceID Device", name, priority=6)
    return _ok(message="Đã xếp hàng provision thiết bị")


@frappe.whitelist()
def pull_devices_from_controller():
    """Đồng bộ danh sách thiết bị từ controller."""
    res = gateway_get("/api/devices")
    devices = res.get("devices") or []
    synced = 0
    for d in devices:
        ip = str(d.get("ip", "")).split("/")[0]
        existing = frappe.db.get_value("FaceID Device", {"ip": ip}, "name")
        if existing:
            frappe.db.set_value(
                "FaceID Device",
                existing,
                {
                    "controller_device_id": d.get("id"),
                    "status": d.get("status") or "unknown",
                    "last_seen": d.get("last_seen"),
                },
                update_modified=False,
            )
        else:
            frappe.get_doc(
                {
                    "doctype": "FaceID Device",
                    "device_name": d.get("name") or ip,
                    "ip": ip,
                    "controller_device_id": d.get("id"),
                    "model": d.get("model"),
                    "status": d.get("status") or "unknown",
                }
            ).insert(ignore_permissions=True)
        synced += 1
    return _ok({"synced": synced})


# ---- Sync status ----


@frappe.whitelist()
def get_sync_status():
    pending = frappe.db.count("FaceID Device Sync Job", {"state": "pending"})
    failed = frappe.db.count("FaceID Device Sync Job", {"state": "failed"})
    persons_pending = frappe.db.count("FaceID Person", {"sync_status": "pending"})
    return _ok(
        {
            "jobs_pending": pending,
            "jobs_failed": failed,
            "persons_pending": persons_pending,
        }
    )


@frappe.whitelist()
def list_sync_jobs(state=None, limit=20):
    filters = {}
    if state:
        filters["state"] = state
    rows = frappe.get_all(
        "FaceID Device Sync Job",
        filters=filters,
        fields=["name", "job_type", "ref_name", "state", "attempts", "last_error", "creation"],
        order_by="creation desc",
        limit=int(limit),
    )
    return _ok(rows)


@frappe.whitelist()
def search_person_candidates(person_type, search=None, limit=30):
    """Tìm HS/NV/PH chưa enroll hoặc để link."""
    limit = int(limit)
    if person_type == "student":
        filters = {}
        if search:
            filters["student_name"] = ["like", f"%{search}%"]
        rows = frappe.get_all(
            "CRM Student",
            filters=filters,
            fields=["name", "student_name", "student_code", "campus_id"],
            limit=limit,
        )
        return _ok(rows)
    if person_type == "guardian":
        filters = {}
        if search:
            filters["guardian_name"] = ["like", f"%{search}%"]
        rows = frappe.get_all(
            "CRM Guardian",
            filters=filters,
            fields=["name", "guardian_name", "guardian_id"],
            limit=limit,
        )
        return _ok(rows)
    if person_type == "staff":
        filters = {"enabled": 1}
        if search:
            filters["full_name"] = ["like", f"%{search}%"]
        rows = frappe.get_all(
            "User",
            filters=filters,
            fields=["name", "full_name", "employee_code"],
            limit=limit,
        )
        return _ok(rows)
    return _err("person_type không hợp lệ")
