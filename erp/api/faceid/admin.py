"""API quản trị FaceID cho frappe-sis-frontend."""

from __future__ import annotations

import json
from datetime import date

import frappe
from frappe.utils import cint

from erp.api.faceid.sync_worker import create_device_sync_job, run_sync_jobs_now
from erp.utils.faceid_gateway import gateway_get, gateway_post


def _ok(data=None, message="OK"):
    return {"success": True, "message": message, "data": data}


def _err(message, data=None):
    return {"success": False, "message": message, "data": data}


def _person_is_active(row) -> bool:
    """Bản ghi cũ có thể chưa có is_active — mặc định doctype là bật."""
    val = row.get("is_active") if isinstance(row, dict) else getattr(row, "is_active", None)
    if val is None or val == "":
        return True
    return cint(val) == 1


def _apply_person_campus_filter(filters: dict, person_type: str | None, campus_id: str | None):
    """
    Lọc campus cho FaceID Person.
    NV (staff) theo user_management — User không gắn campus_id, bỏ qua filter campus.
    HS/PH lấy từ CRM Student/Guardian có campus_id.
    """
    if not campus_id:
        return
    if person_type == "staff":
        return
    filters["campus_id"] = campus_id


# ---- Persons ----


@frappe.whitelist()
def list_persons(
    person_type=None,
    campus_id=None,
    sync_status=None,
    is_active=None,
    search=None,
    limit=100,
    offset=0,
):
    filters = {}
    if person_type:
        filters["person_type"] = person_type
    _apply_person_campus_filter(filters, person_type, campus_id)
    if sync_status:
        filters["sync_status"] = sync_status
    if is_active is not None and str(is_active) != "":
        filters["is_active"] = int(is_active)

    or_filters = None
    if search:
        q = f"%{search.strip()}%"
        or_filters = [
            ["display_name", "like", q],
            ["external_code", "like", q],
            ["position", "like", q],
            ["department", "like", q],
        ]

    rows = frappe.get_all(
        "FaceID Person",
        filters=filters,
        or_filters=or_filters,
        fields=[
            "name",
            "person_type",
            "external_code",
            "display_name",
            "position",
            "department",
            "photo_url",
            "campus_id",
            "work_shift",
            "is_active",
            "on_device",
            "face_status",
            "sync_status",
            "last_synced_at",
            "last_error",
            "valid_from",
            "valid_to",
            "source_synced_at",
        ],
        order_by="modified desc",
        limit=int(limit),
        start=int(offset),
    )
    total = frappe.db.count("FaceID Person", filters=filters)
    if or_filters:
        total = len(
            frappe.get_all(
                "FaceID Person",
                filters=filters,
                or_filters=or_filters,
                pluck="name",
                limit=0,
            )
        )
    return _ok({"items": rows, "total": total})


@frappe.whitelist()
def refresh_persons_from_source(person_type, campus_id=None, class_id=None):
    """Lấy dữ liệu từ nguồn CRM/SIS/User và upsert vào FaceID Person."""
    from erp.api.faceid.person_source import refresh_persons_from_source as _refresh

    stats = _refresh(person_type, campus_id, class_id)
    msg = f"Đã lấy dữ liệu: {stats.get('created', 0)} mới, {stats.get('updated', 0)} cập nhật"
    if stats.get("conflicts"):
        msg += f", {stats['conflicts']} bỏ qua (trùng mã loại khác)"
    if stats.get("skipped"):
        msg += f", {stats['skipped']} bỏ qua (không đọc được user)"
    return _ok(stats, message=msg)


@frappe.whitelist()
def set_person_active(name, active=1):
    """Bật/tắt kích hoạt person (staged — chưa đẩy xuống máy)."""
    doc = frappe.get_doc("FaceID Person", name)
    doc.is_active = int(active)
    doc.sync_status = "pending"
    doc.flags.faceid_refresh = 1
    doc.save(ignore_permissions=True)
    return _ok(doc.as_dict())


@frappe.whitelist()
def set_persons_active(names, active=1):
    """Bật/tắt hàng loạt."""
    name_list = frappe.parse_json(names) if isinstance(names, str) else names
    updated = 0
    for n in name_list or []:
        if not frappe.db.exists("FaceID Person", n):
            continue
        doc = frappe.get_doc("FaceID Person", n)
        doc.is_active = int(active)
        doc.sync_status = "pending"
        doc.flags.faceid_refresh = 1
        doc.save(ignore_permissions=True)
        updated += 1
    return _ok({"updated": updated})


@frappe.whitelist()
def sync_persons(person_type=None, campus_id=None, force=0):
    """
    Đồng bộ dữ liệu xuống controller local:
    - is_active=1 → upsert_person (force=1: đẩy lại tất cả đang bật)
    - is_active=0 & on_device=1 → delete_person
    Chạy job ngay sau khi xếp hàng (operator-driven).
    """
    force = cint(force)
    filters = {}
    if person_type:
        filters["person_type"] = person_type
    _apply_person_campus_filter(filters, person_type, campus_id)

    upsert_count = delete_count = 0
    job_names: list[str] = []
    persons = frappe.get_all(
        "FaceID Person",
        filters=filters,
        fields=["name", "is_active", "on_device", "sync_status", "external_code"],
        limit=10000,
    )
    for p in persons:
        if _person_is_active(p):
            if force or p.sync_status != "synced" or not cint(p.on_device):
                job_names.append(
                    create_device_sync_job("upsert_person", "FaceID Person", p.name, priority=8)
                )
                upsert_count += 1
        elif cint(p.on_device):
            job_names.append(
                create_device_sync_job(
                    "delete_person",
                    "FaceID Person",
                    p.name,
                    payload={"external_code": p.external_code},
                    priority=8,
                )
            )
            delete_count += 1

    run_stats = run_sync_jobs_now(job_names) if job_names else {"processed": 0, "failed": 0, "errors": []}
    processed = run_stats.get("processed", 0)
    failed = run_stats.get("failed", 0)

    if upsert_count == 0 and delete_count == 0:
        msg = "Không có person nào cần đồng bộ (kiểm tra tab loại và trạng thái kích hoạt)"
    elif failed:
        msg = (
            f"Đã xử lý {processed}/{upsert_count + delete_count} job; "
            f"{failed} lỗi (xem FaceID Device Sync Job hoặc last_error trên person)"
        )
    else:
        msg = f"Đã đồng bộ: {upsert_count} đẩy xuống, {delete_count} xóa khỏi máy"

    return _ok(
        {
            "upsert_queued": upsert_count,
            "delete_queued": delete_count,
            "processed": processed,
            "failed": failed,
            "errors": run_stats.get("errors") or [],
        },
        message=msg,
    )


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
    doc = frappe.get_doc("FaceID Person", name)
    if doc.is_active:
        create_device_sync_job("upsert_person", "FaceID Person", name, priority=8)
        return _ok(message="Đã xếp hàng sync person")
    if doc.on_device:
        create_device_sync_job(
            "delete_person",
            "FaceID Person",
            name,
            payload={"external_code": doc.external_code},
            priority=8,
        )
        return _ok(message="Đã xếp hàng xóa person khỏi máy")
    return _ok(message="Person không cần sync")


# Giữ alias bulk_enroll_* cho tương thích ngược — gọi refresh
@frappe.whitelist()
def bulk_enroll_students(campus_id=None, class_id=None):
    return refresh_persons_from_source("student", campus_id, class_id)


@frappe.whitelist()
def bulk_enroll_staff():
    return refresh_persons_from_source("staff")


@frappe.whitelist()
def bulk_enroll_guardians(campus_id=None):
    return refresh_persons_from_source("guardian", campus_id)


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


@frappe.whitelist()
def sync_all_work_shifts():
    """Đồng bộ tất cả ca làm việc xuống controller."""
    shifts = frappe.get_all("FaceID Work Shift", pluck="name")
    for name in shifts:
        create_device_sync_job("sync_shift", "FaceID Work Shift", name, priority=7)
    return _ok({"queued": len(shifts)}, message=f"Đã xếp hàng sync {len(shifts)} ca")


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
def get_sync_status(person_type=None):
    person_filters = {}
    if person_type:
        person_filters["person_type"] = person_type
    pending = frappe.db.count("FaceID Device Sync Job", {"state": "pending"})
    failed = frappe.db.count("FaceID Device Sync Job", {"state": "failed"})
    running = frappe.db.count("FaceID Device Sync Job", {"state": "running"})
    persons_pending = frappe.db.count(
        "FaceID Person", {**person_filters, "sync_status": "pending"}
    )
    persons_synced = frappe.db.count(
        "FaceID Person", {**person_filters, "sync_status": "synced", "is_active": 1}
    )
    persons_on_device = frappe.db.count(
        "FaceID Person", {**person_filters, "on_device": 1}
    )
    return _ok(
        {
            "jobs_pending": pending,
            "jobs_failed": failed,
            "jobs_running": running,
            "persons_pending": persons_pending,
            "persons_synced": persons_synced,
            "persons_on_device": persons_on_device,
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
