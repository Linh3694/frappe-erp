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
    for col in ("job_title", "designation", "department", "user_image", "username", "employee_code"):
        if frappe.db.has_column("User", col):
            cols.append(col)
    return cols


def _load_staff_user_row(user_name: str) -> dict | None:
    """Đọc User kèm custom field (defensive)."""
    try:
        doc = frappe.get_cached_doc("User", user_name)
    except Exception:
        return None
    row = {
        "name": doc.name,
        "full_name": doc.full_name or doc.name,
        "email": getattr(doc, "email", None) or doc.name,
    }
    for col in _user_extra_fields():
        if hasattr(doc, col):
            row[col] = getattr(doc, col)
    return row


def _resolve_staff_external_code(user_name: str, user_row: dict | None = None) -> str | None:
    """
    Suy mã nhân viên để đồng bộ FaceID.
    Ưu tiên: User.employee_code → Employee → username → local-part email.
    """
    row = user_row or _load_staff_user_row(user_name)
    if not row:
        return None

    code = (row.get("employee_code") or "").strip()
    if code:
        return code

    if frappe.db.table_exists("Employee"):
        emp = frappe.db.get_value(
            "Employee",
            {"user_id": user_name},
            ["employee_number", "name"],
            as_dict=True,
        )
        if emp:
            emp_code = (emp.get("employee_number") or emp.get("name") or "").strip()
            if emp_code:
                return emp_code

    username = (row.get("username") or "").strip()
    if username:
        return username

    email = (row.get("email") or user_name).strip()
    if "@" in email:
        local = email.split("@", 1)[0].strip()
        if local:
            return local

    return email or user_name


def _iter_staff_users() -> list[dict]:
    """User hệ thống (loại trừ portal phụ huynh) — nguồn nhân viên FaceID."""
    return frappe.db.sql(
        """
        SELECT u.name, u.full_name, u.email
        FROM `tabUser` u
        WHERE u.enabled = 1
          AND u.user_type = 'System User'
          AND u.name NOT IN ('Guest', 'Administrator')
          AND u.email NOT LIKE %s
          AND u.email NOT LIKE %s
        ORDER BY u.full_name
        LIMIT 10000
        """,
        ("%@parent.%", "%@parent-portal.%"),
        as_dict=True,
    )


def _find_existing_person(values: dict) -> str | None:
    """Tìm FaceID Person theo link nguồn, tránh đè chéo loại (HS/NV/PH)."""
    person_type = values.get("person_type")
    if person_type == "student" and values.get("crm_student"):
        found = frappe.db.get_value(
            "FaceID Person",
            {"person_type": "student", "crm_student": values["crm_student"]},
            "name",
        )
        if found:
            return found
    if person_type == "guardian" and values.get("crm_guardian"):
        found = frappe.db.get_value(
            "FaceID Person",
            {"person_type": "guardian", "crm_guardian": values["crm_guardian"]},
            "name",
        )
        if found:
            return found
    if person_type == "staff" and values.get("user"):
        found = frappe.db.get_value(
            "FaceID Person",
            {"person_type": "staff", "user": values["user"]},
            "name",
        )
        if found:
            return found
    return frappe.db.get_value(
        "FaceID Person",
        {"person_type": person_type, "external_code": values["external_code"]},
        "name",
    )


def _resolve_external_code_for_insert(values: dict) -> str:
    """Nếu mã đã dùng bởi loại khác thì thêm prefix để không đè bản ghi."""
    code = values["external_code"]
    existing_type = frappe.db.get_value("FaceID Person", {"external_code": code}, "person_type")
    if not existing_type or existing_type == values["person_type"]:
        return code
    prefixes = {"student": "HS", "staff": "NV", "guardian": "PH"}
    prefix = prefixes.get(values["person_type"], "FID")
    return f"{prefix}-{code}"


def _upsert_person(values: dict) -> tuple[str, str]:
    """
    Upsert FaceID Person theo link nguồn + (person_type, external_code).
    Trả (name, action) với action = 'created' | 'updated' | 'unchanged' | 'skipped_conflict'.
    """
    external_code = values["external_code"]
    person_type = values["person_type"]
    existing = _find_existing_person(values)
    now = frappe.utils.now()

    if existing:
        doc = frappe.get_doc("FaceID Person", existing)
        if doc.person_type != person_type:
            return doc.name, "skipped_conflict"
        changed = False
        if doc.external_code != external_code:
            # Cập nhật mã nếu nguồn đổi (vd employee_code)
            resolved = _resolve_external_code_for_insert(values)
            if doc.external_code != resolved:
                doc.external_code = resolved
                changed = True
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

    insert_code = _resolve_external_code_for_insert(values)
    doc = frappe.get_doc(
        {
            "doctype": "FaceID Person",
            "person_type": person_type,
            "external_code": insert_code,
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
    action = "created_prefixed" if insert_code != external_code else "created"
    return doc.name, action


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

    created = updated = conflicts = 0
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
        if action in ("created", "created_prefixed"):
            created += 1
        elif action == "updated":
            updated += 1
        elif action == "skipped_conflict":
            conflicts += 1

    return {
        "created": created,
        "updated": updated,
        "conflicts": conflicts,
        "total_candidates": len(students),
    }


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
    created = updated = conflicts = 0
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
        if action in ("created", "created_prefixed"):
            created += 1
        elif action == "updated":
            updated += 1
        elif action == "skipped_conflict":
            conflicts += 1
    return {
        "created": created,
        "updated": updated,
        "conflicts": conflicts,
        "total_candidates": len(guardians),
    }


def refresh_staff() -> dict:
    users = _iter_staff_users()
    created = updated = conflicts = skipped = 0
    for u in users:
        row = _load_staff_user_row(u.name)
        if not row:
            skipped += 1
            continue
        external_code = _resolve_staff_external_code(u.name, row)
        if not external_code:
            skipped += 1
            continue
        position = ""
        if row.get("job_title"):
            position = str(row["job_title"])
        elif row.get("designation"):
            position = str(row["designation"])
        department = (row.get("department") or "").strip()
        photo_url = row.get("user_image") or get_user_photo_url(u.name)
        _, action = _upsert_person(
            {
                "person_type": "staff",
                "external_code": external_code,
                "display_name": row.get("full_name") or u.name,
                "position": position,
                "department": department,
                "photo_url": photo_url,
                "user": u.name,
            }
        )
        if action in ("created", "created_prefixed"):
            created += 1
        elif action == "updated":
            updated += 1
        elif action == "skipped_conflict":
            conflicts += 1
    return {
        "created": created,
        "updated": updated,
        "conflicts": conflicts,
        "skipped": skipped,
        "total_candidates": len(users),
    }


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
