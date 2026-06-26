"""API quản trị FaceID cho frappe-sis-frontend."""

from __future__ import annotations

import json
from datetime import date

import frappe
from frappe.utils import cint

from erp.api.faceid.sync_worker import (
    create_device_sync_job,
    person_sync_job_stats,
    run_sync_jobs_now,
)

# Lô nhỏ chạy inline trong request; lớn hơn → worker nền (tránh timeout FE)
SYNC_INLINE_MAX = 5
from erp.utils.faceid_gateway import (
    gateway_delete,
    gateway_get,
    gateway_post,
    gateway_post_file,
    gateway_put,
)


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
def sync_persons(person_type=None, campus_id=None, force=0, device_names=None):
    """
    Đồng bộ dữ liệu xuống controller local:
    - is_active=1 → upsert_person (force=1: đẩy lại tất cả đang bật)
    - is_active=0 & on_device=1 → delete_person
    device_names: danh sách FaceID Device name — chỉ đẩy xuống các máy đã chọn.
    Chạy inline nếu ≤ SYNC_INLINE_MAX job; lớn hơn → worker nền (tránh timeout HTTP).
    """
    force = cint(force)
    filters = {}
    if person_type:
        filters["person_type"] = person_type
    _apply_person_campus_filter(filters, person_type, campus_id)

    # Resolve máy đích (picker tạm thời — không ghi vào target_devices)
    device_ips: list[str] | None = None
    if device_names:
        raw_names = frappe.parse_json(device_names) if isinstance(device_names, str) else device_names
        if raw_names:
            device_ips = []
            for dev_name in raw_names:
                ip = frappe.db.get_value("FaceID Device", dev_name, "ip")
                if ip:
                    device_ips.append(str(ip).split("/")[0])
            if not device_ips:
                return _err("Không tìm thấy IP cho các máy đã chọn")

    sync_payload = {"device_ips": device_ips} if device_ips else None

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
                    create_device_sync_job(
                        "upsert_person",
                        "FaceID Person",
                        p.name,
                        payload=sync_payload,
                        priority=8,
                    )
                )
                upsert_count += 1
        elif cint(p.on_device):
            job_names.append(
                create_device_sync_job(
                    "delete_person",
                    "FaceID Person",
                    p.name,
                    payload={"external_code": p.external_code, **(sync_payload or {})},
                    priority=8,
                )
            )
            delete_count += 1

    total_queued = upsert_count + delete_count
    async_mode = False
    run_stats: dict = {"processed": 0, "failed": 0, "errors": []}

    if job_names:
        from erp.api.faceid.sync_worker import dedupe_failed_person_sync_jobs

        dedupe_failed_person_sync_jobs(person_type)
        if len(job_names) <= SYNC_INLINE_MAX:
            run_stats = run_sync_jobs_now(job_names)
        else:
            async_mode = True
            frappe.enqueue(
                "erp.api.faceid.sync_worker.drain_pending_device_sync_jobs",
                queue="long",
                timeout=7200,
                enqueue_after_commit=True,
            )

    processed = run_stats.get("processed", 0)
    failed = run_stats.get("failed", 0)

    if total_queued == 0:
        msg = "Không có person nào cần đồng bộ (kiểm tra tab loại và trạng thái kích hoạt)"
    elif async_mode:
        msg = f"Đã xếp hàng {total_queued} job — đang đồng bộ nền"
    elif failed:
        msg = (
            f"Đã xử lý {processed}/{total_queued} job; "
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
            "async": async_mode,
            "errors": run_stats.get("errors") or [],
            **person_sync_job_stats(person_type),
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
    school_year = frappe.db.get_value("SIS School Year", {"is_enable": 1}, ["start_date", "end_date"], as_dict=True)
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


def _extract_isapi_count(data, *keys: str) -> int | None:
    """Trích số đếm từ response ISAPI lồng nhau."""
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


def _push_device_to_controller(doc) -> dict:
    """Đẩy metadata + credential xuống controller local."""
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
    if cid and int(cid) != cint(doc.controller_device_id):
        frappe.db.set_value(
            "FaceID Device",
            doc.name,
            "controller_device_id",
            int(cid),
            update_modified=False,
        )
        doc.controller_device_id = int(cid)
    return device or res or {}


def _device_ip(name: str) -> str:
    ip = frappe.db.get_value("FaceID Device", name, "ip")
    if not ip:
        frappe.throw(f"Không tìm thấy thiết bị {name}")
    return str(ip).split("/")[0]


@frappe.whitelist()
def list_devices():
    rows = frappe.get_all(
        "FaceID Device",
        fields=[
            "name",
            "device_name",
            "ip",
            "gate_type",
            "is_pickup_gate",
            "status",
            "last_seen",
            "username",
            "https",
            "auth_mode",
            "controller_device_id",
            "campus_id",
            "model",
            "person_count",
            "face_count",
            "device_time",
            "last_status_at",
        ],
        order_by="device_name asc",
    )
    return _ok(rows)


@frappe.whitelist()
def save_device(data):
    payload = frappe.parse_json(data) if isinstance(data, str) else data
    name = payload.get("name")
    new_password = payload.pop("password", None)
    if name and frappe.db.exists("FaceID Device", name):
        doc = frappe.get_doc("FaceID Device", name)
        doc.update(payload)
        if new_password:
            doc.password = new_password
    else:
        doc = frappe.get_doc({"doctype": "FaceID Device", **payload})
        if new_password:
            doc.password = new_password
    doc.save(ignore_permissions=True)
    _push_device_to_controller(doc)
    return _ok(doc.as_dict())


@frappe.whitelist()
def delete_device(name):
    doc = frappe.get_doc("FaceID Device", name)
    if doc.controller_device_id:
        try:
            gateway_delete(f"/api/devices/{doc.controller_device_id}")
        except Exception:
            frappe.log_error(title=f"FaceID delete device {name}", message=frappe.get_traceback())
    frappe.delete_doc("FaceID Device", name, ignore_permissions=True)
    return _ok(message="Đã xóa thiết bị")


@frappe.whitelist()
def get_device_status(name):
    """Đọc giờ máy + số person/face + ảnh standby từ controller, cache vào doc."""
    doc = frappe.get_doc("FaceID Device", name)
    ip = _device_ip(name)
    res = gateway_get(f"/api/devices/{ip}/status")
    status = res.get("status") or {}
    person_count = _extract_isapi_count(status.get("persons") or {}, "userNumber", "recordNum")
    face_count = _extract_isapi_count(status.get("faces") or {}, "faceLibNum", "recordNum", "faceNum")
    time_info = status.get("time") or {}
    device_time = time_info.get("localTime") or time_info.get("LocalTime")

    screen_images = {}
    try:
        screen_images = gateway_get(f"/api/devices/{ip}/screen-images") or {}
    except Exception:
        frappe.log_error(
            title=f"FaceID screen images {name}",
            message=frappe.get_traceback(),
        )

    frappe.db.set_value(
        "FaceID Device",
        name,
        {
            "person_count": person_count,
            "face_count": face_count,
            "device_time": device_time,
            "last_status_at": frappe.utils.now(),
        },
        update_modified=False,
    )
    return _ok(
        {
            "person_count": person_count,
            "face_count": face_count,
            "device_time": device_time,
            "time_zone": time_info.get("timeZone") or time_info.get("TimeZone"),
            "raw": status,
            "screen_images": screen_images,
        }
    )


@frappe.whitelist()
def probe_device(name):
    ip = _device_ip(name)
    res = gateway_post(f"/api/devices/{ip}/probe", {})
    return _ok(res)


@frappe.whitelist()
def list_device_screen_images(name):
    ip = _device_ip(name)
    res = gateway_get(f"/api/devices/{ip}/screen-images")
    return _ok(res)


@frappe.whitelist()
def upload_device_screen_image(name):
    ip = _device_ip(name)
    upload = frappe.request.files.get("file")
    if not upload:
        frappe.throw("Thiếu file ảnh (field `file`)")
    res = gateway_post_file(
        f"/api/devices/{ip}/screen-image",
        upload.stream.read(),
        filename=upload.filename or "screen.jpg",
    )
    return _ok(res)


@frappe.whitelist()
def delete_device_screen_image(name, uuid):
    ip = _device_ip(name)
    res = gateway_delete(f"/api/devices/{ip}/screen-image/{uuid}")
    return _ok(res)


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

    job_stats = person_sync_job_stats(person_type)
    persons_pending = frappe.db.count(
        "FaceID Person", {**person_filters, "sync_status": "pending"}
    )
    persons_synced = frappe.db.count(
        "FaceID Person", {**person_filters, "sync_status": "synced", "is_active": 1}
    )
    persons_on_device = frappe.db.count(
        "FaceID Person", {**person_filters, "on_device": 1}
    )
    persons_error = frappe.db.count(
        "FaceID Person", {**person_filters, "sync_status": "error"}
    )

    sample_errors: list[dict] = []
    type_clause = ""
    err_params: list = []
    if person_type:
        type_clause = " AND p.person_type = %s"
        err_params.append(person_type)
    err_rows = frappe.db.sql(
        f"""
        SELECT j.name, j.ref_name, j.last_error, j.attempts
        FROM `tabFaceID Device Sync Job` j
        INNER JOIN `tabFaceID Person` p ON p.name = j.ref_name
        WHERE j.ref_doctype = 'FaceID Person'
          AND j.job_type IN ('upsert_person', 'delete_person')
          AND j.state = 'failed'
          AND j.last_error IS NOT NULL AND j.last_error != ''
          {type_clause}
        ORDER BY j.modified DESC
        LIMIT 5
        """,
        tuple(err_params),
        as_dict=True,
    )
    for row in err_rows:
        sample_errors.append(
            {
                "job": row.name,
                "person": row.ref_name,
                "error": row.last_error,
                "attempts": row.attempts,
            }
        )

    return _ok(
        {
            **job_stats,
            "persons_pending": persons_pending,
            "persons_synced": persons_synced,
            "persons_on_device": persons_on_device,
            "persons_error": persons_error,
            "sample_errors": sample_errors,
        }
    )


@frappe.whitelist()
def retry_failed_person_sync_jobs(person_type=None, limit=2000):
    """Thử lại job person failed (operator)."""
    from erp.api.faceid.sync_worker import (
        dedupe_failed_person_sync_jobs,
        drain_pending_device_sync_jobs,
        retry_failed_sync_jobs,
    )

    deduped = dedupe_failed_person_sync_jobs(person_type)
    retried = retry_failed_sync_jobs(person_type, int(limit))
    if retried:
        frappe.enqueue(
            "erp.api.faceid.sync_worker.drain_pending_device_sync_jobs",
            queue="long",
            timeout=7200,
            enqueue_after_commit=True,
        )
    return _ok(
        {"retried": retried, "deduped": deduped, **person_sync_job_stats(person_type)},
        message=f"Đã dọn {deduped} job trùng, đưa {retried} job lỗi vào hàng chờ lại",
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
