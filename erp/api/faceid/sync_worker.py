"""Sync engine Frappe -> FaceID Controller (theo lô nhỏ, throttle)."""

from __future__ import annotations

import json
import time
from datetime import date

import frappe

from erp.api.faceid.photo import get_person_photo_bytes
from erp.utils.faceid_gateway import (
    gateway_delete,
    gateway_get,
    gateway_healthz,
    gateway_post,
    gateway_post_file,
    gateway_put,
    get_gateway_config,
)

MAX_ATTEMPTS = 5

# Trạng thái tunnel — phát hiện nối lại để reconcile pickup
_last_gateway_online: bool | None = None


def run_sync_jobs_now(job_names: list[str]) -> dict:
    """Chạy ngay các job vừa xếp hàng (lô nhỏ, ≤ SYNC_INLINE_MAX)."""
    processed = failed = 0
    errors: list[dict] = []
    for name in job_names:
        if not name:
            continue
        try:
            _process_one_job(name)
            processed += 1
        except Exception as e:
            failed += 1
            errors.append({"job": name, "error": str(e)[:200]})
    return {"processed": processed, "failed": failed, "errors": errors}


def drain_pending_device_sync_jobs(max_batches: int = 5000) -> dict:
    """Worker nền: xử lý hết job pending/failed sau operator sync hàng loạt."""
    batches = 0
    for batches in range(1, max_batches + 1):
        pending = frappe.db.count(
            "FaceID Device Sync Job",
            {"state": ["in", ["pending", "failed"]], "attempts": ["<", MAX_ATTEMPTS]},
        )
        if not pending:
            return {"batches": batches - 1, "remaining": 0}
        process_pending_device_sync_jobs()
    remaining = frappe.db.count(
        "FaceID Device Sync Job",
        {"state": ["in", ["pending", "failed"]], "attempts": ["<", MAX_ATTEMPTS]},
    )
    if remaining:
        frappe.log_error(
            title="FaceID drain sync dừng sớm",
            message=f"Còn {remaining} job sau {max_batches} batch",
        )
    return {"batches": max_batches, "remaining": remaining}


def create_device_sync_job(
    job_type: str,
    ref_doctype: str,
    ref_name: str,
    payload: dict | None = None,
    priority: int = 5,
):
    """Tạo job pending (tránh trùng pending cùng ref)."""
    existing = frappe.db.exists(
        "FaceID Device Sync Job",
        {
            "job_type": job_type,
            "ref_doctype": ref_doctype,
            "ref_name": ref_name,
            "state": "pending",
        },
    )
    if existing:
        return existing
    doc = frappe.get_doc(
        {
            "doctype": "FaceID Device Sync Job",
            "job_type": job_type,
            "ref_doctype": ref_doctype,
            "ref_name": ref_name,
            "payload": json.dumps(payload or {}),
            "state": "pending",
            "priority": priority,
        }
    )
    doc.insert(ignore_permissions=True)
    return doc.name


def process_pending_device_sync_jobs():
    """Scheduler: xử lý N job/lần + nghỉ giữa job để đỡ lag máy."""
    cfg = get_gateway_config()
    batch = cfg["batch_size"]
    sleep_sec = cfg["batch_sleep"]

    jobs = frappe.get_all(
        "FaceID Device Sync Job",
        filters={"state": ["in", ["pending", "failed"]], "attempts": ["<", MAX_ATTEMPTS]},
        fields=["name"],
        order_by="priority desc, creation asc",
        limit=batch,
    )
    for j in jobs:
        try:
            _process_one_job(j.name)
        except Exception:
            frappe.log_error(title=f"FaceID job {j.name}", message=frappe.get_traceback())
        time.sleep(sleep_sec)


def _process_one_job(job_name: str):
    job = frappe.get_doc("FaceID Device Sync Job", job_name)
    if job.state == "done":
        return
    job.state = "running"
    job.attempts = (job.attempts or 0) + 1
    job.save(ignore_permissions=True)
    frappe.db.commit()

    try:
        handler = {
            "upsert_person": _job_upsert_person,
            "delete_person": _job_delete_person,
            "upsert_shift": _job_upsert_shift,
            "sync_shift": _job_sync_shift,
            "upsert_pickup": _job_upsert_pickup,
            "revoke_pickup": _job_revoke_pickup,
            "reapply_pickup": _job_reapply_pickup,
            "reconcile_pickup": _job_reconcile_pickup,
            "provision_device": _job_provision_device,
        }.get(job.job_type)
        if not handler:
            raise ValueError(f"Job type không hỗ trợ: {job.job_type}")
        handler(job)
        job.state = "done"
        job.last_error = None
    except Exception as e:
        job.state = "failed"
        job.last_error = str(e)[:500]
        raise
    finally:
        job.save(ignore_permissions=True)
        frappe.db.commit()


def _device_ids_for_person(doc) -> list[int]:
    ids = []
    for row in doc.target_devices or []:
        cid = frappe.db.get_value("FaceID Device", row.device, "controller_device_id")
        if cid:
            ids.append(int(cid))
    return ids


def _job_upsert_person(job):
    doc = frappe.get_doc("FaceID Person", job.ref_name)
    shift_id = None
    if doc.work_shift:
        shift_id = frappe.db.get_value(
            "FaceID Work Shift", doc.work_shift, "controller_shift_id"
        )
    payload = {
        "employee_no": doc.external_code,
        "person_type": doc.person_type,
        "name": doc.display_name,
        "valid_from": str(doc.valid_from) if doc.valid_from else None,
        "valid_to": str(doc.valid_to) if doc.valid_to else None,
        "shift_id": int(shift_id) if shift_id else None,
        "device_ids": _device_ids_for_person(doc),
        "extra": {},
    }
    try:
        gateway_put(f"/api/persons/{doc.external_code}", payload)
    except Exception:
        gateway_post("/api/persons", payload)

    photo = get_person_photo_bytes(doc)
    if photo:
        gateway_post_file(f"/api/persons/{doc.external_code}/face", photo)
    gateway_post(f"/api/persons/{doc.external_code}/push", {})

    frappe.db.set_value(
        "FaceID Person",
        doc.name,
        {
            "sync_status": "synced",
            "on_device": 1,
            "last_synced_at": frappe.utils.now(),
            "last_error": None,
            "face_status": "synced" if photo else doc.face_status,
        },
        update_modified=False,
    )


def _job_delete_person(job):
    payload = json.loads(job.payload or "{}") if job.payload else {}
    code = payload.get("external_code")
    person_name = job.ref_name
    if not code and frappe.db.exists("FaceID Person", job.ref_name):
        doc = frappe.get_doc("FaceID Person", job.ref_name)
        code = doc.external_code
        person_name = doc.name
    if code:
        gateway_delete(f"/api/persons/{code}")
    if person_name and frappe.db.exists("FaceID Person", person_name):
        frappe.db.set_value(
            "FaceID Person",
            person_name,
            {
                "on_device": 0,
                "sync_status": "synced",
                "last_synced_at": frappe.utils.now(),
                "last_error": None,
            },
            update_modified=False,
        )


def _shift_payload(doc) -> dict:
    periods = []
    for p in doc.periods or []:
        periods.append(
            {
                "weekday": int(p.weekday),
                "start_time": str(p.start_time)[:5],
                "end_time": str(p.end_time)[:5],
            }
        )
    return {
        "name": doc.shift_name,
        "note": doc.note,
        "device_slot": int(doc.device_slot),
        "periods": periods,
    }


def _job_upsert_shift(job):
    doc = frappe.get_doc("FaceID Work Shift", job.ref_name)
    payload = _shift_payload(doc)
    ctrl_id = doc.controller_shift_id
    if ctrl_id:
        gateway_put(f"/api/shifts/{ctrl_id}", payload)
    else:
        res = gateway_post("/api/shifts", payload)
        ctrl_id = res.get("shift", {}).get("id")
        if ctrl_id:
            frappe.db.set_value(
                "FaceID Work Shift",
                doc.name,
                "controller_shift_id",
                ctrl_id,
                update_modified=False,
            )


def _job_sync_shift(job):
    doc = frappe.get_doc("FaceID Work Shift", job.ref_name)
    if not doc.controller_shift_id:
        _job_upsert_shift(job)
        doc.reload()
    gateway_post(
        f"/api/shifts/{doc.controller_shift_id}/sync",
        {"repush_persons": False},
    )
    frappe.db.set_value(
        "FaceID Work Shift",
        doc.name,
        {"sync_status": "synced", "last_synced_at": frappe.utils.now(), "last_error": None},
        update_modified=False,
    )


def _pickup_payload(doc) -> dict:
    g_code = frappe.db.get_value("FaceID Person", doc.guardian, "external_code")
    s_code = frappe.db.get_value("FaceID Person", doc.student, "external_code")
    return {
        "external_ref": doc.name,
        "guardian_no": g_code,
        "student_no": s_code,
        "valid_from": str(doc.valid_from),
        "valid_to": str(doc.valid_to),
        "method": doc.method or "face",
        "revoked": bool(doc.revoked),
    }


def _job_upsert_pickup(job):
    doc = frappe.get_doc("FaceID Pickup Authorization", job.ref_name)
    payload = _pickup_payload(doc)
    res = gateway_post("/api/pickup-auth", payload)
    item = res.get("item") or {}
    if item.get("id"):
        frappe.db.set_value(
            "FaceID Pickup Authorization",
            doc.name,
            {
                "controller_auth_id": item["id"],
                "sync_status": "synced",
                "last_synced_at": frappe.utils.now(),
                "last_error": None,
            },
            update_modified=False,
        )


def _job_revoke_pickup(job):
    doc = frappe.get_doc("FaceID Pickup Authorization", job.ref_name)
    if doc.controller_auth_id:
        gateway_post(f"/api/pickup-auth/{doc.controller_auth_id}/revoke", {})
    else:
        # Fallback bulk reconcile sẽ xử lý revoked
        payload = _pickup_payload(doc)
        payload["revoked"] = True
        gateway_post("/api/pickup-auth", payload)
    frappe.db.set_value(
        "FaceID Pickup Authorization",
        doc.name,
        {"sync_status": "synced", "last_synced_at": frappe.utils.now()},
        update_modified=False,
    )


def _job_reapply_pickup(job):
    doc = frappe.get_doc("FaceID Pickup Authorization", job.ref_name)
    if doc.controller_auth_id:
        gateway_post(f"/api/pickup-auth/{doc.controller_auth_id}/reapply", {})
    else:
        payload = _pickup_payload(doc)
        payload["revoked"] = False
        res = gateway_post("/api/pickup-auth", payload)
        item = res.get("item") or {}
        if item.get("id"):
            frappe.db.set_value(
                "FaceID Pickup Authorization",
                doc.name,
                "controller_auth_id",
                item["id"],
                update_modified=False,
            )
    frappe.db.set_value(
        "FaceID Pickup Authorization",
        doc.name,
        {"sync_status": "synced", "last_synced_at": frappe.utils.now(), "revoked": 0},
        update_modified=False,
    )


def _job_reconcile_pickup(job=None):
    """Lớp 2: đẩy snapshot toàn bộ ủy quyền còn hiệu lực xuống controller local."""
    today = date.today()
    rows = frappe.get_all(
        "FaceID Pickup Authorization",
        filters={"revoked": 0, "valid_from": ["<=", today], "valid_to": [">=", today]},
        fields=["name"],
    )
    items = []
    for r in rows:
        doc = frappe.get_doc("FaceID Pickup Authorization", r.name)
        g = frappe.db.get_value("FaceID Person", doc.guardian, "external_code")
        s = frappe.db.get_value("FaceID Person", doc.student, "external_code")
        if not g or not s:
            continue
        items.append(
            {
                "external_ref": doc.name,
                "guardian_no": g,
                "student_no": s,
                "valid_from": str(doc.valid_from),
                "valid_to": str(doc.valid_to),
                "method": doc.method or "face",
                "revoked": False,
            }
        )
    gateway_post("/api/pickup-auth/bulk", {"items": items, "revoke_missing": True})
    for r in rows:
        frappe.db.set_value(
            "FaceID Pickup Authorization",
            r.name,
            {"sync_status": "synced", "last_synced_at": frappe.utils.now()},
            update_modified=False,
        )


def _job_provision_device(job):
    doc = frappe.get_doc("FaceID Device", job.ref_name)
    payload = {"enable_remote_check": bool(doc.is_pickup_gate)}
    gateway_post(f"/api/devices/{doc.ip}/provision", payload)


def reconcile_pickup_auth_to_controller():
    """
    Cron + phát hiện tunnel nối lại: reconcile pickup snapshot.
    Pickup xác thực 100% tại local — chỉ đẩy cache xuống controller.
    """
    global _last_gateway_online
    online = gateway_healthz()
    should_run = False
    if online and _last_gateway_online is False:
        should_run = True  # tunnel vừa nối lại
    elif online:
        should_run = True  # cron định kỳ
    _last_gateway_online = online
    if not should_run or not online:
        return
    create_device_sync_job(
        "reconcile_pickup",
        "FaceID Pickup Authorization",
        "__bulk__",
        priority=10,
    )
    # Xử lý ngay job reconcile vừa tạo
    job = frappe.db.get_value(
        "FaceID Device Sync Job",
        {
            "job_type": "reconcile_pickup",
            "ref_name": "__bulk__",
            "state": "pending",
        },
        "name",
        order_by="creation desc",
    )
    if job:
        _process_one_job(job)


def retry_failed_sync_jobs():
    """Reset failed jobs còn dưới max attempts."""
    failed = frappe.get_all(
        "FaceID Device Sync Job",
        filters={"state": "failed", "attempts": ["<", MAX_ATTEMPTS]},
        pluck="name",
        limit=50,
    )
    for name in failed:
        frappe.db.set_value("FaceID Device Sync Job", name, "state", "pending")
