"""Lấy dữ liệu person từ nguồn CRM/SIS/User và upsert vào FaceID Person."""

from __future__ import annotations

import frappe

from erp.api.faceid.photo import (
    get_guardian_photo_url,
    get_student_photo_url,
    get_user_photo_url,
)


def education_stage_label(grade_code: str | None) -> str:
    """Map grade_code sang nhãn cấp học (Tiểu học / Trung học)."""
    if not grade_code:
        return ""
    try:
        n = int(str(grade_code).strip())
    except (TypeError, ValueError):
        return ""
    if 1 <= n <= 5:
        return "Tiểu học (khối 1-5)"
    if 6 <= n <= 12:
        return "Trung học (khối 6-12)"
    return ""


def _active_school_year(campus_id: str | None = None) -> str | None:
    filters = {"is_enable": 1}
    if campus_id:
        filters["campus_id"] = campus_id
    return frappe.db.get_value("SIS School Year", filters, "name", order_by="creation desc")


def _student_grade_map(student_ids: list[str], school_year: str | None) -> dict[str, str]:
    """student_id -> grade_code."""
    if not student_ids:
        return {}
    placeholders = ", ".join(["%s"] * len(student_ids))
    params: list = list(student_ids)
    year_clause = ""
    if school_year:
        year_clause = " AND cs.school_year_id = %s"
        params.append(school_year)
    rows = frappe.db.sql(
        f"""
        SELECT cs.student_id, eg.grade_code
        FROM `tabSIS Class Student` cs
        INNER JOIN `tabSIS Class` c ON c.name = cs.class_id AND c.class_type = 'regular'
        INNER JOIN `tabSIS Education Grade` eg ON eg.name = c.education_grade
        WHERE cs.student_id IN ({placeholders})
          AND cs.class_type = 'regular'
          {year_clause}
        ORDER BY cs.modified DESC
        """,
        tuple(params),
        as_dict=True,
    )
    result: dict[str, str] = {}
    for r in rows:
        if r.student_id not in result and r.grade_code:
            result[r.student_id] = r.grade_code
    return result


def _student_photo_map(student_ids: list[str], school_year: str | None) -> dict[str, str]:
    if not student_ids:
        return {}
    placeholders = ", ".join(["%s"] * len(student_ids))
    params: list = list(student_ids)
    year_order = ""
    if school_year:
        year_order = "CASE WHEN school_year_id = %s THEN 0 ELSE 1 END,"
        params.insert(0, school_year)
    rows = frappe.db.sql(
        f"""
        SELECT student_id, photo
        FROM `tabSIS Photo`
        WHERE student_id IN ({placeholders})
          AND type = 'student'
          AND status = 'Active'
          AND photo IS NOT NULL AND photo != ''
        ORDER BY {year_order} upload_date DESC, creation DESC
        """,
        tuple(params),
        as_dict=True,
    )
    result: dict[str, str] = {}
    for r in rows:
        if r.student_id not in result and r.photo:
            result[r.student_id] = r.photo
    return result


def _user_extra_fields() -> list[str]:
    """Các cột User tùy chọn (custom field)."""
    cols = []
    for col in ("job_title", "designation", "department", "user_image"):
        if frappe.db.has_column("User", col):
            cols.append(col)
    return cols


def _upsert_person(values: dict) -> tuple[str, str]:
    """
    Upsert FaceID Person theo external_code.
    Trả (name, action) với action = 'created' | 'updated' | 'unchanged'.
    """
    external_code = values["external_code"]
    existing = frappe.db.get_value("FaceID Person", {"external_code": external_code}, "name")
    now = frappe.utils.now()

    if existing:
        doc = frappe.get_doc("FaceID Person", existing)
        changed = False
        for key in (
            "display_name",
            "position",
            "department",
            "photo_url",
            "campus_id",
            "crm_student",
            "crm_guardian",
            "user",
        ):
            if key not in values:
                continue
            new_val = values.get(key)
            if doc.get(key) != new_val:
                doc.set(key, new_val)
                changed = True
        if changed:
            doc.sync_status = "pending"
            doc.source_synced_at = now
        doc.flags.faceid_refresh = 1
        doc.save(ignore_permissions=True)
        return doc.name, "updated" if changed else "unchanged"

    doc = frappe.get_doc(
        {
            "doctype": "FaceID Person",
            "person_type": values["person_type"],
            "external_code": external_code,
            "display_name": values["display_name"],
            "position": values.get("position"),
            "department": values.get("department"),
            "photo_url": values.get("photo_url"),
            "campus_id": values.get("campus_id"),
            "crm_student": values.get("crm_student"),
            "crm_guardian": values.get("crm_guardian"),
            "user": values.get("user"),
            "is_active": 1,
            "on_device": 0,
            "sync_status": "pending",
            "source_synced_at": now,
        }
    )
    doc.flags.faceid_refresh = 1
    doc.insert(ignore_permissions=True)
    return doc.name, "created"


def refresh_students(campus_id: str | None = None, class_id: str | None = None) -> dict:
    filters = {}
    if campus_id:
        filters["campus_id"] = campus_id
    students = frappe.get_all(
        "CRM Student",
        filters=filters,
        fields=["name", "student_name", "student_code", "campus_id"],
        limit=10000,
    )
    if class_id:
        class_students = frappe.get_all(
            "SIS Class Student",
            filters={"class_id": class_id},
            pluck="student_id",
        )
        students = [s for s in students if s.name in class_students]

    school_year = _active_school_year(campus_id)
    student_ids = [s.name for s in students]
    grade_map = _student_grade_map(student_ids, school_year)
    photo_map = _student_photo_map(student_ids, school_year)

    created = updated = 0
    for s in students:
        if not s.student_code:
            continue
        grade_code = grade_map.get(s.name)
        _, action = _upsert_person(
            {
                "person_type": "student",
                "external_code": s.student_code,
                "display_name": s.student_name,
                "position": "Học sinh",
                "department": education_stage_label(grade_code),
                "photo_url": photo_map.get(s.name) or get_student_photo_url(s.name),
                "campus_id": s.campus_id,
                "crm_student": s.name,
            }
        )
        if action == "created":
            created += 1
        elif action == "updated":
            updated += 1

    return {"created": created, "updated": updated, "total_candidates": len(students)}


def refresh_guardians(campus_id: str | None = None) -> dict:
    filters = {}
    if campus_id:
        filters["campus_id"] = campus_id
    guardians = frappe.get_all(
        "CRM Guardian",
        filters=filters,
        fields=["name", "guardian_name", "guardian_id", "guardian_image", "campus_id"],
        limit=10000,
    )
    created = updated = 0
    for g in guardians:
        if not g.guardian_id:
            continue
        _, action = _upsert_person(
            {
                "person_type": "guardian",
                "external_code": g.guardian_id,
                "display_name": g.guardian_name,
                "position": "Phụ huynh",
                "department": "Giám hộ",
                "photo_url": g.guardian_image or get_guardian_photo_url(g.name),
                "campus_id": g.campus_id or campus_id,
                "crm_guardian": g.name,
            }
        )
        if action == "created":
            created += 1
        elif action == "updated":
            updated += 1
    return {"created": created, "updated": updated, "total_candidates": len(guardians)}


def refresh_staff() -> dict:
    extra = _user_extra_fields()
    fields = ["name", "full_name", "employee_code"] + extra
    users = frappe.get_all(
        "User",
        filters={"enabled": 1, "employee_code": ["is", "set"]},
        fields=fields,
        limit=10000,
    )
    created = updated = 0
    for u in users:
        if not u.employee_code:
            continue
        position = ""
        if hasattr(u, "job_title") and u.job_title:
            position = u.job_title
        elif hasattr(u, "designation") and u.designation:
            position = u.designation
        department = getattr(u, "department", None) or ""
        photo_url = getattr(u, "user_image", None) or get_user_photo_url(u.name)
        _, action = _upsert_person(
            {
                "person_type": "staff",
                "external_code": u.employee_code,
                "display_name": u.full_name or u.name,
                "position": position,
                "department": department,
                "photo_url": photo_url,
                "user": u.name,
            }
        )
        if action == "created":
            created += 1
        elif action == "updated":
            updated += 1
    return {"created": created, "updated": updated, "total_candidates": len(users)}


def refresh_persons_from_source(
    person_type: str,
    campus_id: str | None = None,
    class_id: str | None = None,
) -> dict:
    if person_type == "student":
        return refresh_students(campus_id, class_id)
    if person_type == "guardian":
        return refresh_guardians(campus_id)
    if person_type == "staff":
        return refresh_staff()
    frappe.throw(f"person_type không hợp lệ: {person_type}")
