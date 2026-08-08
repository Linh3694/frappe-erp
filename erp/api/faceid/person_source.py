"""Lấy dữ liệu person từ nguồn CRM/SIS/User và upsert vào FaceID Person."""

from __future__ import annotations

import frappe
from frappe.utils import cint

from erp.api.faceid.photo import (
    get_guardian_photo_url,
    get_student_photo_url,
    get_user_photo_url,
)


SCHOOL_PRIMARY = "Trường Tiểu học"
SCHOOL_MIDDLE = "Trường Trung học Cơ sở"
SCHOOL_HIGH = "Trường Trung học Phổ thông"

# HS đã enrolled nhưng chưa được xếp lớp regular — chưa suy được Trường.
PENDING_CLASS_DEPARTMENT = "Chờ xếp lớp"


def school_label(grade_code: str | None = None, stage_title: str | None = None) -> str:
    """Map sang tên Trường (Tiểu học / THCS / THPT).

    Ưu tiên title của SIS Education Stage (dữ liệu chuẩn, đặt tên tự do theo campus),
    fallback suy từ grade_code (1-5 / 6-9 / 10-12) khi grade chưa gắn stage.
    """
    t = (stage_title or "").strip().lower()
    if t:
        if "tiểu học" in t or "tieu hoc" in t or "primary" in t or "elementary" in t:
            return SCHOOL_PRIMARY
        if "cơ sở" in t or "co so" in t or "thcs" in t or "middle" in t or "secondary" in t:
            return SCHOOL_MIDDLE
        if "phổ thông" in t or "pho thong" in t or "thpt" in t or "high" in t:
            return SCHOOL_HIGH
    if not grade_code:
        return ""
    try:
        n = int(str(grade_code).strip())
    except (TypeError, ValueError):
        return ""
    if 1 <= n <= 5:
        return SCHOOL_PRIMARY
    if 6 <= n <= 9:
        return SCHOOL_MIDDLE
    if 10 <= n <= 12:
        return SCHOOL_HIGH
    return ""


def _active_school_year(campus_id: str | None = None) -> str | None:
    filters = {"is_enable": 1}
    if campus_id:
        filters["campus_id"] = campus_id
    return frappe.db.get_value("SIS School Year", filters, "name", order_by="creation desc")


def _student_school_map(student_ids: list[str], school_year: str | None) -> dict[str, str]:
    """student_id -> tên Trường (suy từ lớp regular → grade → education stage)."""
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
        SELECT cs.student_id, eg.grade_code, st.title_vn AS stage_title
        FROM `tabSIS Class Student` cs
        INNER JOIN `tabSIS Class` c ON c.name = cs.class_id AND c.class_type = 'regular'
        INNER JOIN `tabSIS Education Grade` eg ON eg.name = c.education_grade
        LEFT JOIN `tabSIS Education Stage` st ON st.name = eg.education_stage_id
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
        if r.student_id in result:
            continue
        label = school_label(r.grade_code, r.stage_title)
        if label:
            result[r.student_id] = label
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
        ORDER BY {year_order}
                 (SELECT sy.start_date FROM `tabSIS School Year` sy WHERE sy.name = school_year_id) DESC,
                 upload_date DESC, creation DESC
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
    """User hệ thống — cùng tiêu chí user_management.get_users (không lọc campus).

    Lấy CẢ tài khoản đã tắt: trạng thái tài khoản (enabled) được đồng bộ thẳng
    sang trạng thái kích hoạt của person (xem _sync_staff_active_state).
    """
    return frappe.db.sql(
        """
        SELECT u.name, u.full_name, u.email, u.enabled
        FROM `tabUser` u
        WHERE u.user_type = 'System User'
          AND u.name NOT IN ('Guest', 'Administrator')
          AND u.email NOT LIKE %s
        ORDER BY u.full_name
        LIMIT 10000
        """,
        ("%@parent.wellspring.edu.vn",),
        as_dict=True,
    )


def _sync_staff_active_state(person_name: str, enabled: int) -> str | None:
    """Đồng bộ User.enabled → FaceID Person.is_active.

    Tắt tài khoản → tắt person + gỡ khỏi máy ngay (an ninh: NV nghỉ việc).
    Bật lại → bật person + đẩy lại theo các nhóm hiện có.
    Trả về 'deactivated' / 'reactivated' / None (không đổi).
    """
    from erp.api.faceid.access_engine import deactivate_person

    is_active = frappe.db.get_value("FaceID Person", person_name, "is_active")
    if enabled and not is_active:
        frappe.db.set_value("FaceID Person", person_name, "is_active", 1)
        frappe.enqueue(
            "erp.api.faceid.access_engine.refresh_persons",
            queue="short",
            enqueue_after_commit=True,
            person_names=[person_name],
        )
        return "reactivated"
    if not enabled and is_active:
        deactivate_person(person_name, reason="User: tài khoản bị tắt")
        return "deactivated"
    return None


def _staff_campus_id(user_name: str) -> str | None:
    """Campus của nhân sự — theo DỮ LIỆU, không theo session.

    Hàm này được gọi từ hook User và từ job nền (session = Administrator), nên tuyệt đối
    không dùng campus của session: `get_user_campuses()[0]` cho Administrator trả campus
    tuỳ ý theo thứ tự `modified desc` — đúng cơ chế đã đóng dấu sai 76.201 dòng.

    Ưu tiên hồ sơ SIS Teacher; nếu không có thì chỉ nhận role campus khi user có ĐÚNG một
    campus. Nhiều campus thì trả None (để trống còn hơn gán sai).
    """
    campus = frappe.db.get_value("SIS Teacher", {"user_id": user_name}, "campus_id")
    if campus:
        return campus
    try:
        from erp.sis.utils.campus_permissions import get_user_campuses

        campuses = get_user_campuses(user_name)
        if len(campuses) == 1:
            return campuses[0]
        if len(campuses) > 1:
            frappe.logger().info(
                f"[FaceID] {user_name} thuoc {len(campuses)} campus — de trong campus_id"
            )
    except Exception:
        pass
    return None


def sync_staff_user(user_name: str) -> str | None:
    """Upsert person cho MỘT user (hook User tạo mới / bật-tắt tài khoản)."""
    user_type = frappe.db.get_value("User", user_name, "user_type")
    if (
        user_type != "System User"
        or user_name in ("Guest", "Administrator")
        or user_name.endswith("@parent.wellspring.edu.vn")
    ):
        return None
    row = _load_staff_user_row(user_name)
    if not row:
        return None
    external_code = _resolve_staff_external_code(user_name, row)
    if not external_code:
        return None
    name, _ = _upsert_person(
        {
            "person_type": "staff",
            "external_code": external_code,
            "display_name": row.get("full_name") or user_name,
            "position": str(row.get("job_title") or row.get("designation") or ""),
            "department": (row.get("department") or "").strip(),
            "photo_url": row.get("user_image") or get_user_photo_url(user_name),
            "user": user_name,
            "campus_id": _staff_campus_id(user_name),
        }
    )
    enabled = cint(frappe.db.get_value("User", user_name, "enabled"))
    _sync_staff_active_state(name, enabled)
    return name


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
        if not changed:
            # Không ghi gì khi dữ liệu nguồn không đổi — save thừa × hàng nghìn
            # bản ghi là thứ làm refresh toàn trường vượt timeout request.
            return doc.name, "unchanged"
        doc.sync_status = "pending"
        doc.source_synced_at = now
        doc.flags.faceid_refresh = 1
        doc.save(ignore_permissions=True)
        return doc.name, "updated"

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


# SSOT của học sinh là CRM Lead: person chỉ tồn tại khi còn lead Enrolled
# (CRM Student.enrollment_status do lead_student_sync tính từ TOÀN BỘ lead).
#   - "Nghi hoc"      = mọi lead đã Nghỉ học (chuyển trường / tốt nghiệp / bảo lưu)
#   - "Chua nhap hoc"  = có lead nhưng chưa Enrolled — chưa được vào danh sách person
# Bản ghi cũ để trống enrollment_status vẫn coi là đang học (grandfather, như trước).
INACTIVE_ENROLLMENT_STATUSES = ("Nghi hoc", "Chua nhap hoc")


def _student_person_values(s, school_map: dict, photo_map: dict) -> dict:
    return {
        "person_type": "student",
        "external_code": s.student_code,
        "display_name": s.student_name,
        "position": "Học sinh",
        "department": school_map.get(s.name) or PENDING_CLASS_DEPARTMENT,
        "photo_url": photo_map.get(s.name) or get_student_photo_url(s.name),
        "campus_id": s.campus_id,
        "crm_student": s.name,
    }


def refresh_students(campus_id: str | None = None, class_id: str | None = None) -> dict:
    filters = {}
    if campus_id:
        filters["campus_id"] = campus_id
    filters["enrollment_status"] = ["not in", INACTIVE_ENROLLMENT_STATUSES]
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
    school_map = _student_school_map(student_ids, school_year)
    photo_map = _student_photo_map(student_ids, school_year)

    created = updated = conflicts = 0
    for s in students:
        if not s.student_code:
            continue
        _, action = _upsert_person(_student_person_values(s, school_map, photo_map))
        if action in ("created", "created_prefixed"):
            created += 1
        elif action == "updated":
            updated += 1
        elif action == "skipped_conflict":
            conflicts += 1

    removed = _offboard_withdrawn_students(campus_id)

    return {
        "created": created,
        "updated": updated,
        "conflicts": conflicts,
        "removed": removed,
        "total_candidates": len(students),
    }


def _offboard_withdrawn_students(campus_id: str | None = None) -> int:
    """Lưới chắn: HS không còn diện đang học mà vẫn còn trong danh sách person
    → gỡ khỏi máy + xoá khỏi danh sách (chuyển trường / tốt nghiệp / chưa nhập học)."""
    withdrawn = frappe.get_all(
        "CRM Student",
        filters={"enrollment_status": ["in", INACTIVE_ENROLLMENT_STATUSES]},
        pluck="name",
        limit=20000,
    )
    if not withdrawn:
        return 0

    person_filters = {"crm_student": ["in", withdrawn], "person_type": "student"}
    if campus_id:
        person_filters["campus_id"] = campus_id
    count = 0
    for name in frappe.get_all("FaceID Person", filters=person_filters, pluck="name"):
        if offboard_person(name, reason="CRM Student: không còn diện đang học"):
            count += 1
    return count


def sync_student_person(crm_student: str) -> str | None:
    """Upsert person cho MỘT học sinh (hook: lead chuyển Enrolled → enrollment_status
    thành 'Dang hoc'). Trả về tên FaceID Person hoặc None nếu không thuộc diện."""
    s = frappe.db.get_value(
        "CRM Student",
        crm_student,
        ["name", "student_name", "student_code", "campus_id", "enrollment_status"],
        as_dict=True,
    )
    if not s or not s.student_code:
        return None
    if (s.enrollment_status or "").strip() in INACTIVE_ENROLLMENT_STATUSES:
        return None
    school_year = _active_school_year(s.campus_id)
    school_map = _student_school_map([s.name], school_year)
    photo_map = _student_photo_map([s.name], school_year)
    name, _ = _upsert_person(_student_person_values(s, school_map, photo_map))
    # Mặc định HS enrolled là Kích hoạt (kể cả bản ghi cũ từng bị tắt tay).
    if frappe.db.get_value("FaceID Person", name, "is_active") == 0:
        frappe.db.set_value("FaceID Person", name, "is_active", 1)
    return name


def refresh_student_department(crm_student: str) -> None:
    """Xếp lớp xong → phòng ban của person đổi thành Trường tương ứng."""
    person = frappe.db.get_value(
        "FaceID Person",
        {"person_type": "student", "crm_student": crm_student},
        ["name", "department", "campus_id"],
        as_dict=True,
    )
    if not person:
        return
    school_year = _active_school_year(person.campus_id)
    school_map = _student_school_map([crm_student], school_year)
    new_dept = school_map.get(crm_student) or PENDING_CLASS_DEPARTMENT
    if new_dept != (person.department or ""):
        frappe.db.set_value(
            "FaceID Person",
            person.name,
            {"department": new_dept, "sync_status": "pending"},
        )


def offboard_person(person_name: str, reason: str = "") -> bool:
    """Xoá person khỏi danh sách + gỡ khỏi hệ thống FaceID (HS chuyển trường/tốt nghiệp).

    Thứ tự an toàn:
      1. Ủy quyền đón liên quan: revoke best-effort xuống controller ngay rồi xoá doc
         (flag faceid_skip_sync để không sinh job mồ côi; reconcile 15' quét sạch phần lỡ).
      2. Rời mọi Access Group (flag skip_refresh — máy sẽ được dọn ở bước 4).
      3. Xoá Assignment (bảng vật chất hoá trạng thái person × máy).
      4. Xoá doc person → on_trash tự tạo job delete_person theo external_code,
         job này chạy được cả khi doc đã xoá (gỡ person + access grant khỏi gateway).
    """
    if not frappe.db.exists("FaceID Person", person_name):
        return False
    doc = frappe.get_doc("FaceID Person", person_name)

    from erp.utils.faceid_gateway import gateway_post

    auths = frappe.get_all(
        "FaceID Pickup Authorization",
        or_filters=[["student", "=", person_name], ["guardian", "=", person_name]],
        fields=["name", "controller_auth_id", "revoked"],
    )
    for a in auths:
        if a.controller_auth_id and not a.revoked:
            try:
                gateway_post(f"/api/pickup-auth/{a.controller_auth_id}/revoke", {})
            except Exception:
                pass  # controller offline → reconcile_pickup 15' dọn nốt
        auth_doc = frappe.get_doc("FaceID Pickup Authorization", a.name)
        auth_doc.flags.faceid_skip_sync = True
        auth_doc.delete(ignore_permissions=True)

    for m in frappe.get_all(
        "FaceID Access Group Member", filters={"person": person_name}, pluck="name"
    ):
        member = frappe.get_doc("FaceID Access Group Member", m)
        member.flags.faceid_skip_refresh = True
        member.delete(ignore_permissions=True)

    frappe.db.delete("FaceID Person Device Assignment", {"person": person_name})

    frappe.logger("faceid").info(
        f"[offboard] {person_name} ({doc.external_code}): {reason or 'không rõ lý do'}"
    )
    frappe.delete_doc("FaceID Person", person_name, ignore_permissions=True, force=1)
    return True


def _guardian_person_values(g, campus_id: str | None = None) -> dict:
    return {
        "person_type": "guardian",
        "external_code": g.guardian_id,
        "display_name": g.guardian_name,
        "position": "Phụ huynh",
        "department": "Giám hộ",
        "photo_url": g.guardian_image or get_guardian_photo_url(g.name),
        "campus_id": g.campus_id or campus_id,
        "crm_guardian": g.name,
    }


def sync_guardian_person(crm_guardian: str) -> str | None:
    """Upsert person cho MỘT guardian (hook CRM Guardian tạo mới / đổi tên-ảnh)."""
    g = frappe.db.get_value(
        "CRM Guardian",
        crm_guardian,
        ["name", "guardian_name", "guardian_id", "guardian_image", "campus_id"],
        as_dict=True,
    )
    if not g or not g.guardian_id:
        return None
    name, _ = _upsert_person(_guardian_person_values(g))
    return name


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
        _, action = _upsert_person(_guardian_person_values(g, campus_id))
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
    deactivated = reactivated = 0
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
        name, action = _upsert_person(
            {
                "person_type": "staff",
                "external_code": external_code,
                "display_name": row.get("full_name") or u.name,
                "position": position,
                "department": department,
                "photo_url": photo_url,
                "user": u.name,
                "campus_id": _staff_campus_id(u.name),
            }
        )
        if action in ("created", "created_prefixed"):
            created += 1
        elif action == "updated":
            updated += 1
        elif action == "skipped_conflict":
            conflicts += 1
        if action != "skipped_conflict":
            state = _sync_staff_active_state(name, cint(u.enabled))
            if state == "deactivated":
                deactivated += 1
            elif state == "reactivated":
                reactivated += 1
    return {
        "created": created,
        "updated": updated,
        "conflicts": conflicts,
        "skipped": skipped,
        "deactivated": deactivated,
        "reactivated": reactivated,
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


def refresh_all_sources() -> dict:
    """Cron đêm: lưới backstop kéo lại toàn bộ 3 nguồn.

    Đường phản ứng chính là hook (Lead/Student/Guardian/User/Class Student);
    cron này bắt các thay đổi đi đường db.set_value không chạy hook
    (vd. sync_enrollment_status_for_student khi xoá lead) và tự lành dữ liệu lệch.
    """
    result = {}
    for person_type in ("student", "guardian", "staff"):
        try:
            result[person_type] = refresh_persons_from_source(person_type)
        except Exception:
            frappe.log_error(
                title=f"FaceID refresh_all_sources: {person_type}",
                message=frappe.get_traceback(),
            )
            result[person_type] = {"error": True}
    return result
