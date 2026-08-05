"""Hooks enqueue sync job khi DocType FaceID thay đổi."""

from __future__ import annotations

import frappe


def _enqueue(job_type: str, ref_doctype: str, ref_name: str, payload: dict | None = None):
    frappe.enqueue(
        "erp.api.faceid.sync_worker.create_device_sync_job",
        queue="short",
        enqueue_after_commit=True,
        job_type=job_type,
        ref_doctype=ref_doctype,
        ref_name=ref_name,
        payload=payload or {},
    )


def on_person_changed(doc, method=None, job_type="upsert_person"):
    # Operator-driven: bỏ qua khi refresh/lấy dữ liệu từ nguồn
    if getattr(doc.flags, "faceid_refresh", False):
        return
    _enqueue(job_type, doc.doctype, doc.name)


def on_work_shift_changed(doc, method=None):
    if getattr(doc.flags, "faceid_refresh", False):
        return
    _enqueue("sync_shift", doc.doctype, doc.name)


def on_pickup_auth_changed(doc, method=None, job_type="upsert_pickup"):
    _enqueue(job_type, doc.doctype, doc.name)


# ------------------------------------------------- Access Group (mô hình nhóm)


def on_access_group_changed(doc, method=None):
    """Đổi ca/máy/hiệu lực của nhóm → tính lại toàn bộ thành viên."""
    if getattr(doc.flags, "faceid_skip_refresh", False):
        return
    frappe.enqueue(
        "erp.api.faceid.access_engine.refresh_group",
        queue="long",
        timeout=3600,
        enqueue_after_commit=True,
        group_name=doc.name,
    )


def on_access_group_member_changed(doc, method=None):
    """Thêm/xóa thành viên → chỉ tính lại person bị đụng."""
    if getattr(doc.flags, "faceid_skip_refresh", False):
        return
    frappe.enqueue(
        "erp.api.faceid.access_engine.refresh_persons",
        queue="short",
        enqueue_after_commit=True,
        person_names=[doc.person],
    )


# ------------------------------------------------------- nghỉ học / thôi học

WITHDRAWN_ENROLLMENT = ("Nghi hoc",)
WITHDRAWN_DEAL_STATUS = ("Hoan phi", "Bao luu/Chuyen")


def _faceid_person_for_student(student_name: str) -> str | None:
    return frappe.db.get_value("FaceID Person", {"crm_student": student_name}, "name")


def on_student_enrollment_changed(doc, method=None):
    """CRM Student đổi trạng thái học → tắt/bật person + gỡ khỏi máy NGAY."""
    if not doc.has_value_changed("enrollment_status"):
        return
    person = _faceid_person_for_student(doc.name)
    if not person:
        return

    if doc.enrollment_status in WITHDRAWN_ENROLLMENT:
        frappe.enqueue(
            "erp.api.faceid.access_engine.deactivate_person",
            queue="short",
            enqueue_after_commit=True,
            person_name=person,
            reason=f"CRM Student: {doc.enrollment_status}",
        )
    elif frappe.db.get_value("FaceID Person", person, "is_active") == 0:
        # Đi học lại → bật lại và đẩy xuống các máy theo nhóm hiện có
        frappe.db.set_value("FaceID Person", person, "is_active", 1, update_modified=True)
        frappe.enqueue(
            "erp.api.faceid.access_engine.refresh_persons",
            queue="short",
            enqueue_after_commit=True,
            person_names=[person],
        )


def on_lead_deal_status_changed(doc, method=None):
    """CRM Lead hoàn phí / bảo lưu - chuyển trường → gỡ HS khỏi máy."""
    if not doc.get("linked_student") or not doc.has_value_changed("deal_status"):
        return
    if doc.deal_status not in WITHDRAWN_DEAL_STATUS:
        return
    person = _faceid_person_for_student(doc.linked_student)
    if not person:
        return
    frappe.enqueue(
        "erp.api.faceid.access_engine.deactivate_person",
        queue="short",
        enqueue_after_commit=True,
        person_name=person,
        reason=f"CRM Lead: {doc.deal_status}",
    )
