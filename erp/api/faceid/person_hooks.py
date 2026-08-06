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


def on_work_shift_changed(doc, method=None):
    """Sửa khung giờ của ca → lịch hợp đổi → signature đổi → slot mới trên máy.

    Không tự lan là thành: ca sửa trên WIS nhưng máy vẫn chạy khung giờ cũ.
    """
    if getattr(doc.flags, "faceid_skip_refresh", False):
        return
    groups = set(
        frappe.get_all("FaceID Access Group", filters={"shift_in": doc.name}, pluck="name")
    ) | set(
        frappe.get_all("FaceID Access Group", filters={"shift_out": doc.name}, pluck="name")
    )
    for group in groups:
        frappe.enqueue(
            "erp.api.faceid.access_engine.refresh_group",
            queue="long",
            timeout=3600,
            enqueue_after_commit=True,
            group_name=group,
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


# ------------------------------------------- nguồn person: CRM Lead → CRM Student

# CRM Student.enrollment_status do lead_student_sync tính từ TOÀN BỘ lead trỏ vào.
# "Nghi hoc" (chuyển trường / tốt nghiệp / bảo lưu) và "Chua nhap hoc" đều rời danh sách.
WITHDRAWN_ENROLLMENT = ("Nghi hoc", "Chua nhap hoc")
STUDYING_ENROLLMENT = "Dang hoc"
WITHDRAWN_LEAD_STEP = "Nghi hoc"


def _faceid_person_for_student(student_name: str) -> str | None:
    return frappe.db.get_value("FaceID Person", {"crm_student": student_name}, "name")


def _enqueue_offboard(person: str, reason: str):
    frappe.enqueue(
        "erp.api.faceid.person_source.offboard_person",
        queue="short",
        enqueue_after_commit=True,
        person_name=person,
        reason=reason,
    )


def on_student_enrollment_changed(doc, method=None):
    """CRM Student đổi trạng thái học (được sync từ CRM Lead — SSOT của HS).

    - Lead lên Enrolled → status 'Dang hoc' → tự tạo person (mặc định Kích hoạt).
    - Mọi lead về Nghỉ học (chuyển trường/tốt nghiệp) → gỡ khỏi máy + XOÁ khỏi danh sách.
    """
    if not doc.has_value_changed("enrollment_status"):
        return
    status = (doc.enrollment_status or "").strip()
    person = _faceid_person_for_student(doc.name)

    if status in WITHDRAWN_ENROLLMENT:
        if person:
            _enqueue_offboard(person, f"CRM Student: {status}")
        return

    if status == STUDYING_ENROLLMENT:
        if not person:
            # Nhập học (hoặc quay lại sau khi đã bị xoá) → tạo person mới
            frappe.enqueue(
                "erp.api.faceid.person_source.sync_student_person",
                queue="short",
                enqueue_after_commit=True,
                crm_student=doc.name,
            )
        elif frappe.db.get_value("FaceID Person", person, "is_active") == 0:
            # Bản ghi còn đó nhưng đang tắt → bật lại và đẩy xuống máy theo nhóm hiện có
            frappe.db.set_value("FaceID Person", person, "is_active", 1, update_modified=True)
            frappe.enqueue(
                "erp.api.faceid.access_engine.refresh_persons",
                queue="short",
                enqueue_after_commit=True,
                person_names=[person],
            )


def on_lead_step_changed(doc, method=None):
    """CRM Lead rời Enrolled (Chuyen truong / Tot nghiep / Bao luu) → gỡ HS NGAY.

    Đường chính là hook CRM Student ở trên (lead controller sync student mỗi on_update);
    hook này là lưới tức thời bắt cả các đường ghi enrollment_status bằng db.set_value
    (không chạy hook Document, vd. sync_enrollment_status_for_student khi xoá/relink lead).
    """
    if not doc.get("linked_student") or not doc.has_value_changed("step"):
        return
    if doc.step != WITHDRAWN_LEAD_STEP:
        return
    # HS có thể bị nhiều lead trỏ vào (nghỉ rồi nhập học lại) — chỉ gỡ khi
    # không còn lead nào đang Enrolled.
    from erp.api.crm.lead_student_sync import compute_enrollment_status

    if compute_enrollment_status(doc.linked_student) == STUDYING_ENROLLMENT:
        return
    person = _faceid_person_for_student(doc.linked_student)
    if person:
        _enqueue_offboard(person, f"CRM Lead: {doc.step}/{doc.status}")


# ------------------------------------------------- nguồn person: User (staff)


def on_user_changed(doc, method=None):
    """User bật/tắt tài khoản → đồng bộ trạng thái kích hoạt person staff.

    sync_staff_user tự lọc System User / bỏ tài khoản phụ huynh, và tự
    deactivate (gỡ máy) khi enabled=0, bật lại + đẩy máy khi enabled=1.
    """
    if method == "on_update" and not doc.has_value_changed("enabled"):
        return
    if doc.get("user_type") != "System User":
        return
    frappe.enqueue(
        "erp.api.faceid.person_source.sync_staff_user",
        queue="short",
        enqueue_after_commit=True,
        user_name=doc.name,
    )


# ------------------------------------------------- nguồn person: CRM Guardian


def on_guardian_changed(doc, method=None):
    """CRM Guardian tạo mới / đổi tên-ảnh-campus → upsert person guardian."""
    if method != "after_insert" and not any(
        doc.has_value_changed(f)
        for f in ("guardian_name", "guardian_image", "campus_id", "guardian_id")
    ):
        return
    frappe.enqueue(
        "erp.api.faceid.person_source.sync_guardian_person",
        queue="short",
        enqueue_after_commit=True,
        crm_guardian=doc.name,
    )


# --------------------------------------------- xếp lớp → phòng ban (Trường)


def on_class_student_changed(doc, method=None):
    """Xếp lớp / chuyển lớp / rút khỏi lớp → cập nhật Trường của person HS."""
    if (doc.get("class_type") or "regular") != "regular":
        return
    if not doc.get("student_id"):
        return
    frappe.enqueue(
        "erp.api.faceid.person_source.refresh_student_department",
        queue="short",
        enqueue_after_commit=True,
        crm_student=doc.student_id,
    )
