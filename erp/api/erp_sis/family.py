import frappe
from frappe import _
from frappe.utils import nowdate, get_datetime
import json
import pandas as pd
import re
import unicodedata
from erp.utils.api_response import (
    success_response, error_response, list_response,
    single_item_response, validation_error_response,
    not_found_response, forbidden_response, paginated_response
)
from erp.utils.campus_utils import get_current_campus_from_context
from erp.utils.search import build_search_condition
from erp.utils.relationship_types import (
    RELATIONSHIP_CODES,
    is_known_code as is_known_relationship_code,
    normalize as normalize_relationship,
)
from erp.utils.family_relationship import (
    canonical_relationship_rows,
    rebuild_guardian_relationship_mirror,
    rebuild_student_relationship_mirror,
)


def _find_existing_family_for_student(student_id: str, exclude_family: str | None = None):
    if not student_id:
        return None
    params = [student_id]
    query = """
        SELECT f.name, f.family_code
        FROM `tabCRM Family Relationship` fr
        INNER JOIN `tabCRM Family` f ON f.name = fr.parent
        WHERE fr.student = %s
    """
    if exclude_family:
        query += " AND f.name != %s"
        params.append(exclude_family)

    result = frappe.db.sql(query, params, as_dict=True)
    return result[0] if result else None


def _canonical_rows_with_family(student=None, guardian=None):
    """Dòng quan hệ CHUẨN kèm GIA ĐÌNH đang giữ dòng đó.

    Cùng vị từ với `erp.utils.family_relationship.canonical_relationship_rows`
    (parentfield='relationships' + family docstatus<2) nhưng trả thêm cột gia đình:
    helper dùng chung chỉ phục vụ dựng mirror nên cố tình không trả `fr.parent`, còn API
    màn Gia đình cần biết dòng thuộc gia đình nào để nhóm/định vị bản ghi cần sửa.
    KHÔNG đọc `CRM Student.family_relationships` / `CRM Guardian.student_relationships`:
    hai bảng đó là mirror, có thể cũ.

    Phải truyền ít nhất một trong student/guardian — không thì trả [] để tránh quét cả bảng.
    """
    if not student and not guardian:
        return []

    conds = ["fr.parentfield = 'relationships'", "f.docstatus < 2"]
    params = {}
    if student:
        conds.append("fr.student = %(student)s")
        params["student"] = student
    if guardian:
        conds.append("fr.guardian = %(guardian)s")
        params["guardian"] = guardian

    return frappe.db.sql(
        """
        SELECT
            f.name AS family_id,
            f.family_code,
            f.campus_id,
            f.creation,
            f.modified,
            fr.student,
            fr.guardian,
            fr.relationship_type,
            fr.key_person,
            fr.access,
            fr.display_order
        FROM `tabCRM Family Relationship` fr
        INNER JOIN `tabCRM Family` f ON fr.parent = f.name
        WHERE {conds}
        ORDER BY f.family_code ASC, fr.display_order ASC, fr.idx ASC
        """.format(conds=" AND ".join(conds)),
        params,
        as_dict=True,
    ) or []


def _relationship_view(row):
    """Một dòng quan hệ theo shape frontend đang dùng.

    `key_person` / `access` trả BOOLEAN (không phải 0/1): schema validate ở frontend
    (`FamilySchema.relationships[]`) khai `z.boolean()`, nhận số sẽ ném ZodError.
    """
    return {
        "student": row.get("student"),
        "guardian": row.get("guardian"),
        "relationship_type": row.get("relationship_type"),
        "key_person": bool(row.get("key_person")),
        "access": bool(row.get("access")),
    }


def _iso_or_none(value):
    """datetime -> ISO string cho JSON response; None/rỗng -> None."""
    if not value:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _parse_bool_flag(value):
    """Cờ 0/1 từ payload HTTP (form gửi chuỗi, JSON gửi bool/số).

    Bản cũ dùng `int(value) if str(value).lower() in ['1','true','yes'] else 0` —
    với value='true' thì `int('true')` ném ValueError, tức nhánh 'true' luôn lỗi.
    """
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        # 1.0 / 1 đều là bật; str(1.0) == '1.0' nên không so chuỗi được.
        return 1 if value else 0
    return 1 if str(value).strip().lower() in ("1", "true", "yes", "y", "on") else 0


def _param_from_request(*keys):
    """Đọc tham số theo thứ tự form_dict -> query args -> JSON body (idiom sẵn có trong file)."""
    form = frappe.local.form_dict or {}
    for key in keys:
        value = form.get(key)
        if value not in (None, ""):
            return value

    try:
        args = getattr(frappe.request, "args", None)
        if args:
            for key in keys:
                value = args.get(key)
                if value not in (None, ""):
                    return value
    except Exception:
        pass

    try:
        if frappe.request and frappe.request.data:
            body = frappe.request.data
            if isinstance(body, bytes):
                body = body.decode("utf-8")
            json_body = json.loads(body or "{}")
            if isinstance(json_body, dict):
                for key in keys:
                    value = json_body.get(key)
                    if value not in (None, ""):
                        return value
    except Exception:
        pass

    return None


def _contact_emails_by_guardian(guardian_names):
    """Email liên lạc THẬT của PH — bảng con `CRM Guardian Email` (ưu tiên is_primary).

    `CRM Guardian.email` là email định danh/đăng nhập: PH tạo từ CRM Lead mà không khai email
    sẽ mang địa chỉ sinh tự động (vd `no-id-crm-lead-6199805@parent.wellspring.edu.vn`) —
    không được dùng để hiển thị. Trả {guardian_docname: email} cho PH có email hợp lệ.
    """
    guardian_names = [name for name in (guardian_names or []) if name]
    if not guardian_names:
        return {}

    rows = frappe.db.sql(
        """
        SELECT parent, email_address, is_primary, idx
        FROM `tabCRM Guardian Email`
        WHERE parent IN %(guardian_names)s AND IFNULL(email_address, '') != ''
        ORDER BY is_primary DESC, idx ASC
        """,
        {"guardian_names": tuple(guardian_names)},
        as_dict=True,
    ) or []

    emails = {}
    for row in rows:
        parent = row.get("parent")
        email = (row.get("email_address") or "").strip()
        # ORDER BY đã đưa email chính lên đầu → dòng đầu tiên của mỗi PH là email cần lấy.
        if parent and email and parent not in emails:
            emails[parent] = email
    return emails


def build_guardians_by_student_ids(student_ids, access_only=False):
    """
    Nội bộ server: cùng cấu trúc với get_guardians_by_students.data.guardians.
    Dùng cho Parent Portal / social-service (tránh whitelist + permission Resource).

    access_only=True: chỉ lấy quan hệ có cờ `access` (UI hiển thị "Xem thông tin") = 1.
    PH không được tích cờ thì không xem được hồ sơ HS (xem parent_portal/student_profile.py)
    nên cũng không được vào nhóm chat lớp. Lọc theo TỪNG QUAN HỆ chứ không theo PH: PH có
    2 con mà chỉ 1 con được cấp quyền thì `students` chỉ còn con đó — subtitle nhóm chat
    ("Phụ huynh của …") không lộ tên HS mà PH không có quyền xem.

    Mặc định False: các consumer khác (màn hình Gia đình bên SIS, danh bạ PH) vẫn cần thấy
    đủ mọi quan hệ, đừng bật cờ này ở đó.
    """
    student_ids = [student_id for student_id in (student_ids or []) if student_id]
    if not student_ids:
        return []

    access_filter = "AND fr.access = 1" if access_only else ""

    # CHỈ đọc dòng CHUẨN (dưới CRM Family còn sống). Trước đây query không lọc
    # parentfield nên đọc lẫn 2 bản mirror (dưới CRM Student/CRM Guardian) có thể cũ:
    # PH đã bị tắt `access` ở bản chuẩn vẫn lọt vào nhóm chat lớp qua mirror sót, và
    # cột family_code nhận cả docname của guardian/student (parent của dòng mirror).
    rows = frappe.db.sql(
        f"""
        SELECT
            fr.parent AS family_code,
            fr.student AS student_id,
            fr.relationship_type,
            fr.key_person,
            fr.access,
            fr.display_order,
            s.student_name,
            s.student_code,
            s.family_code AS student_family_code,
            g.name,
            g.guardian_id,
            g.guardian_name,
            g.email,
            g.guardian_image,
            g.phone_number
        FROM `tabCRM Family Relationship` fr
        INNER JOIN `tabCRM Family` f ON f.name = fr.parent AND f.docstatus < 2
        INNER JOIN `tabCRM Guardian` g ON g.name = fr.guardian
        LEFT JOIN `tabCRM Student` s ON s.name = fr.student
        WHERE fr.student IN %(student_ids)s
          AND fr.parentfield = 'relationships'
          {access_filter}
        ORDER BY fr.display_order ASC, fr.key_person DESC, g.guardian_name ASC
        """,
        {"student_ids": tuple(student_ids)},
        as_dict=True,
    ) or []

    contact_emails = _contact_emails_by_guardian([row.get("name") for row in rows])

    guardian_map = {}
    for row in rows:
        key = row.get("name") or row.get("guardian_id") or row.get("email")
        if not key:
            continue

        portal_email = (
            f"{row.get('guardian_id')}@parent.wellspring.edu.vn"
            if row.get("guardian_id")
            else None
        )
        guardian = guardian_map.setdefault(key, {
            "name": row.get("name"),
            "guardian_id": row.get("guardian_id"),
            "guardian_name": row.get("guardian_name"),
            # `email` giữ nguyên vai trò ĐỊNH DANH (matchKeys / participant matching);
            # `contact_email` mới là email hiển thị cho người dùng.
            "email": row.get("email"),
            "contact_email": contact_emails.get(row.get("name")),
            "portalEmail": portal_email,
            "guardian_image": row.get("guardian_image"),
            "phone_number": row.get("phone_number"),
            "students": [],
            "matchKeys": [],
        })

        student_id = row.get("student_id")
        if student_id and not any(item.get("student_id") == student_id for item in guardian["students"]):
            guardian["students"].append({
                "student_id": student_id,
                "student_name": row.get("student_name"),
                "student_code": row.get("student_code"),
                "family_code": row.get("student_family_code") or row.get("family_code"),
                "relationship_type": row.get("relationship_type"),
                "key_person": row.get("key_person"),
                "access": row.get("access"),
                "display_order": row.get("display_order"),
            })

        guardian["matchKeys"] = list({
            str(value).strip().lower()
            for value in [
                guardian.get("name"),
                guardian.get("guardian_id"),
                guardian.get("email"),
                guardian.get("portalEmail"),
            ]
            if value
        })

    # Tổng hợp cờ là Người liên hệ chính cho ít nhất 1 con — dùng cho FE lọc nhanh.
    for guardian in guardian_map.values():
        guardian["is_key_person_any"] = any(
            bool(student.get("key_person")) for student in guardian.get("students", [])
        )

    return list(guardian_map.values())


@frappe.whitelist(allow_guest=False, methods=["POST"])
def get_guardians_by_students(student_ids=None):
    """Lấy danh sách phụ huynh theo danh sách học sinh từ CRM Family Relationship."""
    try:
        if student_ids is None and getattr(frappe, "request", None) and frappe.request.data:
            try:
                body = json.loads(
                    frappe.request.data.decode("utf-8")
                    if isinstance(frappe.request.data, bytes)
                    else frappe.request.data
                )
                student_ids = body.get("student_ids")
            except Exception:
                student_ids = None

        if isinstance(student_ids, str):
            try:
                student_ids = json.loads(student_ids)
            except Exception:
                student_ids = [student_ids]

        student_ids = [student_id for student_id in (student_ids or []) if student_id]
        if not student_ids:
            return success_response(data={"guardians": []}, message="No students provided")

        guardians = build_guardians_by_student_ids(student_ids)

        return success_response(
            data={"guardians": guardians},
            message="Guardians fetched successfully",
        )
    except Exception as e:
        frappe.log_error(f"get_guardians_by_students error: {str(e)}")
        return error_response(
            message="Error fetching guardians by students",
            code="FETCH_GUARDIANS_BY_STUDENTS_ERROR",
        )


def _normalize_column_name(column: str) -> str:
    if not column:
        return ""
    value = column.strip().lower().replace('-', '_')
    value = re.sub(r"[^a-z0-9_]+", "_", value)
    value = re.sub(r"__+", "_", value)
    return value.strip('_')


def _get_raw_value(row: pd.Series, column_map: dict[str, str], keys: list[str]) -> object | None:
    for key in keys:
        normalized_key = _normalize_column_name(key)
        actual_col = column_map.get(normalized_key)
        if not actual_col:
            continue
        value = row.get(actual_col)
        if value is None:
            continue
        if isinstance(value, float) and pd.isna(value):
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def _stringify_cell(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    text = str(value).strip()
    if text.lower() in {"nan", "none", "null"}:
        return None
    return text or None


def _guardian_key_variants(index: int, field: str) -> list[str]:
    base = f"guardian_{index}_{field}"
    variants = {
        base,
        base.replace('_', ' '),
        f"guardian {index} {field}".replace('  ', ' '),
        f"Guardian {index} {field.replace('_', ' ').title()}"
    }

    if field == "phone":
        variants.update({
            f"guardian_{index}_phone_number",
            f"guardian_phone_{index}",
            f"guardian{index}phone",
            f"phone_{index}",
            f"phone_number_{index}"
        })
    elif field == "relationship":
        variants.update({
            f"guardian_{index}_relationship",
            f"relationship_{index}",
            f"relationship_type_{index}"
        })
    elif field == "main":
        variants.update({
            f"guardian_{index}_is_main_contact",
            f"is_main_contact_{index}",
            f"main_contact_{index}",
            f"guardian_is_main_{index}"
        })
    elif field == "view":
        variants.update({
            f"guardian_{index}_can_view_information",
            f"can_view_information_{index}",
            f"view_information_{index}"
        })
    elif field == "name":
        variants.update({
            f"guardian_{index}_name",
            f"guardian_{index}_full_name",
            f"guardian_name_{index}",
            f"guardian_full_name_{index}",
            f"guardian{index}name"
        })
    elif field == "id":
        variants.update({
            f"guardian_{index}_id",
            f"guardian_{index}_code",
            f"guardian_{index}_guardian_id",
            f"guardian_id_{index}",
            f"guardian_code_{index}",
            f"guardian{index}id"
        })
    elif field == "email":
        variants.update({
            f"guardian_{index}_email",
            f"guardian_email_{index}",
            f"guardian_{index}_email_address",
            f"email_{index}",
            f"guardian{index}email"
        })

    normalized_variants = []
    for variant in variants:
        if variant:
            normalized_variants.append(variant)
    return list(dict.fromkeys(normalized_variants))


def _normalize_text_for_identifier(value: str) -> str:
    if not value:
        return ""
    text = unicodedata.normalize("NFD", value)
    text = ''.join(ch for ch in text if unicodedata.category(ch) != 'Mn')
    text = text.replace('đ', 'd').replace('Đ', 'D')
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip('-')


def _generate_guardian_identifier(preferred: str | None = None) -> str:
    base = _normalize_text_for_identifier(preferred or "guardian") or "guardian"
    base = base[:40]
    candidate = base
    counter = 1
    while frappe.db.exists("CRM Guardian", {"guardian_id": candidate}):
        counter += 1
        candidate = f"{base}-{counter}"
    return candidate


def _get_or_create_guardian(
    formatted_phone: str,
    guardian_name: str | None = None,
    guardian_identifier: str | None = None,
    guardian_email: str | None = None
) -> dict[str, object]:
    guardian_doc = frappe.db.get_value(
        "CRM Guardian",
        {"phone_number": formatted_phone},
        ["name", "guardian_name", "guardian_id", "family_code", "email"],
        as_dict=True,
    )

    def _resolve_name() -> str:
        return guardian_name or (guardian_doc.get("guardian_name") if guardian_doc else None) or formatted_phone

    def _resolve_identifier() -> str:
        existing_identifier = guardian_doc.get("guardian_id") if guardian_doc else None
        if guardian_identifier:
            hit = frappe.db.get_value("CRM Guardian", {"guardian_id": guardian_identifier}, "name")
            if hit and (not guardian_doc or hit != guardian_doc.get("name")):
                raise frappe.ValidationError(_(f"Guardian ID {guardian_identifier} đã được sử dụng cho người khác"))
            return guardian_identifier
        if existing_identifier:
            return existing_identifier
        return _generate_guardian_identifier(_resolve_name())

    if guardian_doc:
        if guardian_doc.get("family_code"):
            raise frappe.ValidationError(_(f"Người giám hộ với SĐT {formatted_phone} đã thuộc gia đình {guardian_doc['family_code']}"))

        updates: dict[str, object] = {}

        resolved_name = _resolve_name()
        if guardian_doc.get("guardian_name") != resolved_name:
            updates["guardian_name"] = resolved_name

        resolved_identifier = _resolve_identifier()
        if guardian_doc.get("guardian_id") != resolved_identifier:
            updates["guardian_id"] = resolved_identifier

        if guardian_email and guardian_doc.get("email") != guardian_email:
            updates["email"] = guardian_email

        if updates:
            frappe.db.set_value("CRM Guardian", guardian_doc["name"], updates)
            guardian_doc.update(updates)

        return guardian_doc

    resolved_name = _resolve_name()
    resolved_identifier = _resolve_identifier()

    guardian_rec = frappe.get_doc({
        "doctype": "CRM Guardian",
        "guardian_id": resolved_identifier,
        "guardian_name": resolved_name,
        "phone_number": formatted_phone,
        "email": guardian_email or ""
    })
    guardian_rec.flags.ignore_validate = True
    guardian_rec.flags.ignore_permissions = True
    guardian_rec.flags.ignore_mandatory = True
    guardian_rec.insert(ignore_permissions=True)

    return {
        "name": guardian_rec.name,
        "guardian_name": guardian_rec.guardian_name,
        "guardian_id": guardian_rec.guardian_id,
        "family_code": guardian_rec.family_code,
        "email": guardian_rec.email,
    }


def process_family_import_rows(df: pd.DataFrame, campus_id: str) -> dict:
    df = df.replace({pd.NA: None})
    for col in df.columns:
        df[col] = df[col].apply(
            lambda value: value.decode('utf-8', 'ignore') if isinstance(value, bytes) else value
        )
    df = df.where(pd.notnull(df), None)

    required_student_cols = [f"student_code_{i}" for i in range(1, 5)]
    guardian_cols = [
        {
            "index": i,
            "phone": f"guardian_{i}_phone",
            "relationship": f"relationship_{i}",
            "main": f"is_main_contact_{i}",
            "view": f"can_view_information_{i}"
        }
        for i in range(1, 4)
    ]

    if df.empty:
        raise frappe.ValidationError("File không có dữ liệu")

    normalized_columns = {_normalize_column_name(col): col for col in df.columns}

    missing_cols = [
        col
        for col in [guardian_cols[0]["phone"], guardian_cols[0]["relationship"], guardian_cols[0]["main"], guardian_cols[0]["view"]]
        if _normalize_column_name(col) not in normalized_columns
    ]
    if missing_cols:
        raise frappe.ValidationError(f"Thiếu cột bắt buộc: {', '.join(missing_cols)}")

    success_count = 0
    errors: list[dict[str, object]] = []

    for idx, row in df.iterrows():
        excel_row = idx + 2
        row_dict = {col: row.get(col) for col in df.columns}
        try:
            student_ids: list[str] = []
            for col in required_student_cols:
                value_raw = _get_raw_value(row, normalized_columns, [col, col.replace('_', ' '), col.replace('_', '')])
                if value_raw is not None:
                    student_code_str = _stringify_cell(value_raw)
                    if isinstance(value_raw, (int, float)) and student_code_str and not student_code_str.isalpha():
                        student_code_str = str(int(value_raw)) if float(value_raw).is_integer() else student_code_str
                    if student_code_str:
                        student_doc = frappe.db.get_value("CRM Student", {"student_code": student_code_str}, ["name"], as_dict=True)
                        if not student_doc:
                            raise frappe.ValidationError(_(f"Không tìm thấy học sinh có mã {student_code_str}"))
                        existing_family = _find_existing_family_for_student(student_doc['name'])
                        if existing_family:
                            raise frappe.ValidationError(_(f"Học sinh {student_code_str} đã thuộc gia đình {existing_family['family_code']}"))
                        student_ids.append(student_doc['name'])

            if not student_ids:
                raise frappe.ValidationError(_("Cần ít nhất một học sinh"))

            guardians: list[str] = []
            relationships: list[dict[str, object]] = []
            main_contact_count = 0

            for info in guardian_cols:
                idx = info["index"]
                phone_raw = _get_raw_value(row, normalized_columns, _guardian_key_variants(idx, "phone"))
                relationship_type = _get_raw_value(row, normalized_columns, _guardian_key_variants(idx, "relationship"))
                if not phone_raw and not relationship_type:
                    continue

                if not phone_raw:
                    raise frappe.ValidationError(_(f"{info['phone']} bắt buộc"))

                phone_str = _stringify_cell(phone_raw) or ""
                if isinstance(phone_raw, (int, float)) and not str(phone_raw).strip().startswith("+"):
                    phone_str = str(int(phone_raw)) if float(phone_raw).is_integer() else str(phone_raw).rstrip(".0")

                try:
                    formatted_phone = frappe.get_attr('erp.api.erp_sis.guardian.validate_vietnamese_phone_number')(phone_str)
                except Exception as phone_err:
                    raise frappe.ValidationError(_(f"SĐT không hợp lệ {phone_str}: {phone_err}"))

                guardian_name_value = _stringify_cell(_get_raw_value(row, normalized_columns, _guardian_key_variants(idx, "name")))
                guardian_identifier_value = _stringify_cell(_get_raw_value(row, normalized_columns, _guardian_key_variants(idx, "id")))
                guardian_email_value = _stringify_cell(_get_raw_value(row, normalized_columns, _guardian_key_variants(idx, "email")))

                guardian_doc = _get_or_create_guardian(
                    formatted_phone=formatted_phone,
                    guardian_name=guardian_name_value,
                    guardian_identifier=guardian_identifier_value,
                    guardian_email=guardian_email_value,
                )

                if guardian_doc['name'] not in guardians:
                    guardians.append(guardian_doc['name'])

                relationship_value = (_stringify_cell(relationship_type) or '').strip()
                if not relationship_value:
                    raise frappe.ValidationError(_(f"{info['relationship']} bắt buộc"))

                relationship_code = normalize_relationship(relationship_value)

                main_flag = (_stringify_cell(_get_raw_value(row, normalized_columns, _guardian_key_variants(idx, "main"))) or '').lower() == 'y'
                view_flag = (_stringify_cell(_get_raw_value(row, normalized_columns, _guardian_key_variants(idx, "view"))) or '').lower() != 'n'

                if main_flag:
                    main_contact_count += 1

                for student_id in student_ids:
                    relationships.append({
                        "student": student_id,
                        "guardian": guardian_doc['name'],
                        "relationship_type": relationship_code,
                        "key_person": main_flag,
                        "access": view_flag,
                        # Quyền ĐÓN độc lập với quyền XEM: file import chưa có cột riêng
                        # nên mặc định cho đón. Phải ghi tường minh — append() không áp
                        # default doctype (xem ghi chú ở update_family_members).
                        "can_pickup": 1,
                    })

            if not guardians:
                raise frappe.ValidationError(_("Cần ít nhất một người giám hộ"))

            if main_contact_count == 0:
                raise frappe.ValidationError(_("Phải chọn 1 người liên lạc chính"))
            if main_contact_count > 1:
                raise frappe.ValidationError(_("Chỉ được phép 1 người liên lạc chính"))

            family_doc = frappe.get_doc({
                "doctype": "CRM Family",
                "relationships": [],
                "campus_id": campus_id
            })
            family_doc.flags.ignore_validate = True
            family_doc.insert(ignore_permissions=True, ignore_mandatory=True)
            family_doc.family_code = family_doc.name
            family_doc.flags.ignore_validate = True
            family_doc.save(ignore_permissions=True)

            for rel in relationships:
                family_doc.append("relationships", rel)
            family_doc.flags.ignore_validate = True
            family_doc.save(ignore_permissions=True)

            # Mirror dựng từ dòng CHUẨN vừa save ở trên (helper tự gom mọi family của
            # guardian) — tránh mirror thiếu cột và tránh xoá quan hệ ở family khác.
            for student_id in student_ids:
                frappe.db.set_value(
                    "CRM Student", student_id, "family_code", family_doc.family_code,
                    update_modified=False,
                )
                rebuild_student_relationship_mirror(student_id)

            for guardian_id in guardians:
                frappe.db.set_value(
                    "CRM Guardian", guardian_id, "family_code", family_doc.family_code,
                    update_modified=False,
                )
                rebuild_guardian_relationship_mirror(guardian_id)

            frappe.db.commit()
            success_count += 1

        except Exception as row_error:
            frappe.db.rollback()
            errors.append({
                "row": excel_row,
                "error": str(row_error),
                "data": row_dict
            })

    return {
        "success_count": success_count,
        "total_rows": len(df),
        "errors": errors
    }


def generate_family_import_error_file(errors: list[dict[str, object]]) -> str | None:
    if not errors:
        return None

    try:
        import pandas as pd
        from frappe.utils.file_manager import save_file
        from frappe.utils import touch_file
        from pathlib import Path

        error_data = []
        for err in errors:
            row_info = {
                "__row_number": err.get("row"),
                "__error": err.get("error")
            }
            row_dict = err.get("data") or {}
            for key, value in row_dict.items():
                row_info[key] = value
            error_data.append(row_info)

        error_df = pd.DataFrame(error_data)
        temp_file_path = f"/tmp/family_import_errors_{frappe.generate_hash(length=6)}.xlsx"
        error_df.to_excel(temp_file_path, index=False)

        bulk_folder_path = Path(frappe.get_site_path("private", "files", "Bulk Import"))
        bulk_folder_path.mkdir(parents=True, exist_ok=True)
        try:
            touch_file(str(bulk_folder_path / ".keep"))
        except Exception:
            pass
        try:
            frappe.get_doc({
                "doctype": "File",
                "file_name": "Bulk Import",
                "is_folder": 1,
                "folder": "Home",
            }).insert(ignore_permissions=True, ignore_if_duplicate=True)
        except Exception:
            pass

        with open(temp_file_path, "rb") as f:
            file_doc = save_file(
                fname=f"family_import_errors_{frappe.generate_hash(length=4)}.xlsx",
                content=f.read(),
                dt=None,
                dn=None,
                folder="Home/Bulk Import",
                is_private=1
            )
        return file_doc.file_url
    except Exception as e:
        frappe.log_error(f"Failed to generate family import error file: {str(e)}")
        return None


@frappe.whitelist(allow_guest=False)
def get_family_details(family_id=None, family_code=None):
    """Get a family with full relationships (students and guardians)."""
    try:
        # Accept params from multiple sources: function args, form/query params, JSON body
        form = frappe.local.form_dict or {}
        if not family_id:
            family_id = form.get("family_id") or form.get("id") or form.get("name")
        if not family_code:
            family_code = form.get("family_code") or form.get("code")
        # Also check request.args (GET query)
        try:
            args = getattr(frappe.request, 'args', None)
            if args:
                if not family_id:
                    family_id = args.get('family_id') or args.get('id') or args.get('name')
                if not family_code:
                    family_code = args.get('family_code') or args.get('code')
        except Exception:
            pass

        if (not family_id and not family_code) and frappe.request and frappe.request.data:
            try:
                body = frappe.request.data
                if isinstance(body, bytes):
                    body = body.decode("utf-8")
                json_body = json.loads(body or "{}")
                family_id = json_body.get("family_id") or family_id
                family_code = json_body.get("family_code") or family_code
            except Exception:
                pass

        if not family_id and not family_code:
            return error_response(
                message="Family ID or code is required",
                code="MISSING_FAMILY_ID"
            )

        if family_code and not family_id:
            # Resolve by code
            res = frappe.get_all("CRM Family", filters={"family_code": family_code}, fields=["name"], limit=1)
            if res:
                family_id = res[0].name

        # Fetch family basic info using db API to avoid permission issues
        fam_row = None
        if family_id:
            fam_row = frappe.db.get_value("CRM Family", family_id, ["name", "family_code"], as_dict=True)
        if not fam_row and family_code:
            fam_row = frappe.db.get_value("CRM Family", {"family_code": family_code}, ["name", "family_code"], as_dict=True)
        if not fam_row:
            return not_found_response(
                message="Family not found",
                code="FAMILY_NOT_FOUND"
            )
        family_name = fam_row.get("name")

        rels = frappe.get_all(
            "CRM Family Relationship",
            filters={"parent": family_name},
            fields=["student", "guardian", "relationship_type", "key_person", "access"],
        )

        # Fetch student/guardian display
        student_names = {}
        guardian_names = {}
        if rels:
            student_ids = list({r["student"] for r in rels if r.get("student")})
            guardian_ids = list({r["guardian"] for r in rels if r.get("guardian")})
            if student_ids:
                for s in frappe.get_all(
                    "CRM Student",
                    filters={"name": ["in", student_ids]},
                    fields=["name", "student_name", "student_code", "dob", "gender", "family_code"],
                ):
                    student_names[s.name] = s
            if guardian_ids:
                for g in frappe.get_all("CRM Guardian", filters={"name": ["in", guardian_ids]}, fields=["name", "guardian_name", "guardian_id", "family_code", "phone_number", "email"]):
                    guardian_names[g.name] = g

        return single_item_response(
            data={
                "name": family_name,
                "family_code": fam_row.get("family_code"),
                "relationships": rels,
                "students": student_names,
                "guardians": guardian_names,
            },
            message="Family details fetched successfully"
        )
    except Exception as e:
        frappe.log_error("get_family_details failed", frappe.get_traceback(with_context=True))
        return error_response(
            message="Error fetching family details",
            code="FETCH_FAMILY_ERROR"
        )


@frappe.whitelist(allow_guest=False, methods=['POST'])
def update_family_members(family_id=None, students=None, guardians=None, relationships=None):
    """Replace students/guardians and relationships of an existing family."""
    try:
        # Accept params from multiple sources
        form = frappe.local.form_dict or {}
        if not family_id:
            family_id = form.get("family_id") or form.get("id") or form.get("name")
        # Parse JSON strings if sent as form
        def parse_json(value):
            if isinstance(value, str):
                try:
                    return json.loads(value)
                except Exception:
                    return []
            return value or []

        if frappe.request.data and (students is None or guardians is None or relationships is None or not family_id):
            try:
                body = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
                students = body.get("students", students)
                guardians = body.get("guardians", guardians)
                relationships = body.get("relationships", relationships)
                family_id = body.get("family_id", family_id)
            except Exception:
                pass

        students = parse_json(students)
        guardians = parse_json(guardians)
        relationships = parse_json(relationships)

        if not family_id:
            return error_response(
                message="Family ID is required",
                code="MISSING_FAMILY_ID"
            )

        family_doc = frappe.get_doc("CRM Family", family_id)

        # ------------------------------------------------------------------
        # VALIDATE XONG HẾT RỒI MỚI GHI.
        # Handler này báo lỗi bằng response 200 (không raise) nên Frappe vẫn COMMIT
        # transaction ở cuối request (sync_database, frappe/app.py) — validate SAU câu
        # DELETE bên dưới sẽ để lại gia đình rỗng mà API vẫn báo thất bại.
        # ------------------------------------------------------------------
        # MÀN GIA ĐÌNH CHỈ QUẢN THÀNH VIÊN (nhóm) — thuộc tính của CẶP (student,
        # guardian): relationship_type / key_person / access / can_pickup được sửa ở
        # màn của TỪNG CHÁU (lead FamilySection, set_lead_guardian_flags...).
        # Vì vậy khi lưu lại family: cặp ĐÃ CÓ dòng chuẩn thì KẾ THỪA nguyên giá trị cũ
        # (không được ghi đè quyết định đã đặt per-cháu); cặp MỚI dùng default
        # (relationship_type "other" — chỉnh sau ở màn cháu, key_person 0, access 1,
        # can_pickup 1). Client vẫn ĐƯỢC gửi tường minh để override (API compat).
        has_pickup_col = bool(frappe.db.has_column("CRM Family Relationship", "can_pickup"))
        old_pair_cols = "student, guardian, relationship_type, key_person, access" + (
            ", can_pickup" if has_pickup_col else ""
        )
        old_pairs = {
            (r["student"], r["guardian"]): r
            for r in frappe.db.sql(
                f"""
                SELECT {old_pair_cols}
                FROM `tabCRM Family Relationship`
                WHERE parent = %s AND parentfield = 'relationships'
                """,
                (family_id,),
                as_dict=True,
            )
        }

        normalized_relationships = []
        for idx, rel in enumerate(relationships):
            if not isinstance(rel, dict):
                return validation_error_response(
                    message=f"Dữ liệu quan hệ không hợp lệ ở dòng {idx + 1}",
                    errors={"relationships": [f"Row {idx + 1} is not an object"]}
                )

            student_id = str(rel.get("student") or "").strip()
            guardian_id = str(rel.get("guardian") or "").strip()

            # student / guardian `reqd: 1` trên child doctype. `ignore_validate` KHÔNG
            # tắt _validate_mandatory, nên thiếu là `save()` ném MandatoryError sau khi
            # dữ liệu cũ đã bị xoá.
            missing = [
                field
                for field, value in (("student", student_id), ("guardian", guardian_id))
                if not value
            ]
            if missing:
                return validation_error_response(
                    message=f"Thiếu thông tin quan hệ ở dòng {idx + 1}",
                    errors={field: ["Required"] for field in missing}
                )

            old = old_pairs.get((student_id, guardian_id)) or {}

            # relationship_type reqd=1: payload → giá trị cũ của cặp → "other"
            relationship_type = (
                normalize_relationship(rel.get("relationship_type"))
                or old.get("relationship_type")
                or "other"
            )

            def _flag(field, default):
                # Client gửi tường minh (kể cả 0/false) → tôn trọng; không gửi/null →
                # kế thừa cặp cũ; cặp mới → default. Ép bool trước int vì int(None) ném.
                if rel.get(field) is not None:
                    return int(bool(rel.get(field)))
                if field in old and old.get(field) is not None:
                    return int(bool(old.get(field)))
                return default

            row = {
                "student": student_id,
                "guardian": guardian_id,
                "relationship_type": relationship_type,
                "key_person": _flag("key_person", 0),
                "access": _flag("access", 1),
            }
            # PHẢI ghi tường minh: Document.append() KHÔNG áp default của doctype
            # (base_document.py::_init_child), rồi get_valid_dict ép Check thiếu key
            # thành 0 — nên bỏ trống là cả nhà mất quyền đón và sync_family_pickup
            # sẽ THU HỒI uỷ quyền vì tưởng nhà trường chủ ý bỏ tick.
            if has_pickup_col:
                row["can_pickup"] = _flag("can_pickup", 1)
            normalized_relationships.append(row)

        # KHÔNG validate "phải có ≥1 người liên lạc chính" ở mức family nữa:
        # key_person là thuộc tính per-cháu, đặt ở màn lead (set_primary_contact).
        # Cháu mới thêm vào family sẽ chưa có key_person cho tới khi đặt ở màn cháu.

        # HS không được thuộc gia đình khác — kiểm tra TRƯỚC khi xoá quan hệ cũ.
        for student_id in students:
            if not frappe.db.exists("CRM Student", student_id):
                continue
            existing_fam = _find_existing_family_for_student(student_id, exclude_family=family_id)
            if existing_fam:
                return validation_error_response(
                    message=f"Student already belongs to family {existing_fam['family_code']}",
                    errors={"student": [existing_fam['family_code']]}
                )

        # CRITICAL: Get old guardians BEFORE deleting relationships
        # để có thể cleanup những guardians bị remove khỏi family
        old_guardians = set()
        old_students = set()
        for rel in family_doc.relationships:
            if rel.guardian:
                old_guardians.add(rel.guardian)
            if rel.student:
                old_students.add(rel.student)

        # Toàn bộ phần ghi nằm trong savepoint: exception giữa chừng phải rollback, nếu
        # không Frappe vẫn commit trạng thái nửa vời (đã xoá quan hệ cũ, chưa ghi quan hệ
        # mới) vì handler trả lỗi bằng response 200 chứ không raise.
        savepoint = "update_family_members"
        frappe.db.savepoint(savepoint)
        try:
            # CRITICAL: Delete ALL old relationships from database first
            # This prevents deleted guardians from still receiving notifications
            frappe.db.sql("""
                DELETE FROM `tabCRM Family Relationship`
                WHERE parent = %s
            """, (family_id,))

            # Reset relationships in doc and add new ones
            family_doc.set("relationships", [])
            for rel in normalized_relationships:
                family_doc.append("relationships", dict(rel))
            family_doc.flags.ignore_validate = True
            family_doc.save(ignore_permissions=True)

            # Update students and guardians docs similar to create_family
            family_code = getattr(family_doc, 'family_code', family_doc.name)

            # Dựng lại mirror từ các dòng CHUẨN đã ghi ở trên, KHÔNG dựng từ
            # normalized_relationships: bộ đó chỉ chứa quan hệ của family này, nên với
            # guardian còn con ở family khác thì dựng kiểu cũ sẽ xoá mất các quan hệ đó
            # khỏi mirror (gãy consumer chỉ đọc mirror, vd menu_registration.py).
            for student_id in students:
                if frappe.db.exists("CRM Student", student_id):
                    frappe.db.set_value(
                        "CRM Student", student_id, "family_code", family_code,
                        update_modified=False,
                    )
                    rebuild_student_relationship_mirror(student_id)

            for guardian_id in guardians:
                if frappe.db.exists("CRM Guardian", guardian_id):
                    frappe.db.set_value(
                        "CRM Guardian", guardian_id, "family_code", family_code,
                        update_modified=False,
                    )
                    rebuild_guardian_relationship_mirror(guardian_id)

            # CRITICAL FIX: Cleanup guardians đã bị remove khỏi family
            # Clear family_code và student_relationships của họ
            new_guardians = set(guardians)
            removed_guardians = old_guardians - new_guardians

            if removed_guardians:
                frappe.logger().info(f"🧹 Cleaning up {len(removed_guardians)} removed guardians from family {family_id}")
                for removed_guardian_id in removed_guardians:
                    if frappe.db.exists("CRM Guardian", removed_guardian_id):
                        try:
                            # Guardian có thể còn con ở family KHÁC: chỉ dựng lại mirror
                            # từ dòng chuẩn (helper tự gom mọi family), và chỉ xoá
                            # family_code khi thật sự không còn dòng chuẩn nào.
                            remaining = canonical_relationship_rows(
                                guardian=removed_guardian_id
                            )
                            if not remaining:
                                frappe.db.set_value(
                                    "CRM Guardian", removed_guardian_id, "family_code",
                                    None, update_modified=False,
                                )
                            rebuild_guardian_relationship_mirror(removed_guardian_id)
                            frappe.logger().info(f"✅ Cleaned up guardian {removed_guardian_id}")
                        except Exception as cleanup_error:
                            frappe.logger().error(f"❌ Error cleaning up guardian {removed_guardian_id}: {str(cleanup_error)}")
        except Exception:
            frappe.db.rollback(save_point=savepoint)
            raise

        # Sync thành viên nhóm chat lớp. KHÔNG dựa được vào doc-event `on_family_change`:
        # child rows đã bị DELETE thẳng bằng SQL TRƯỚC `family_doc.save()` nên
        # `get_doc_before_save()` đọc lại từ DB ra rỗng ⇒ hook không thấy HS/PH bị gỡ.
        # Truyền HỢP (HS cũ ∪ HS mới) để lớp của HS bị gỡ khỏi gia đình cũng được reconcile.
        try:
            from erp.api.erp_sis.chat_membership_hooks import (
                enqueue_chat_membership_sync_for_students,
            )

            new_students = {rel["student"] for rel in normalized_relationships}
            enqueue_chat_membership_sync_for_students(old_students | new_students | set(students or []))
        except Exception as sync_error:
            # Sync là side-effect — không được chặn luồng lưu gia đình.
            frappe.logger().warning(
                f"[Family] enqueue chat membership sync failed for {family_id}: {str(sync_error)}"
            )

        # `frappe.db.commit()` chạy after_commit callbacks (realtime `notify_update`,
        # `frappe.enqueue(enqueue_after_commit=True)` của hook chat) SAU khi SQL COMMIT
        # đã xong. Lỗi ở đó nghĩa là dữ liệu ĐÃ lưu — không được báo "cập nhật thất bại".
        try:
            frappe.db.commit()
        except Exception as commit_error:
            frappe.logger().warning(
                f"[Family] post-commit side effect failed for {family_id}: {str(commit_error)}"
            )
            frappe.log_error(
                "update_family_members post-commit",
                frappe.get_traceback(with_context=True),
            )

        return success_response(
            data={"family_id": family_doc.name},
            message="Family members updated successfully"
        )
    except Exception as e:
        # Title phải ngắn và cố định: `Error Log.method` chỉ chứa 140 ký tự, nhét str(e)
        # vào title có thể làm chính câu log_error ném CharacterLengthExceededError.
        frappe.log_error("update_family_members failed", frappe.get_traceback(with_context=True))
        return error_response(
            message="Error updating family members",
            code="UPDATE_FAMILY_ERROR",
            debug_info={"exception": type(e).__name__, "detail": str(e)[:500]}
            if frappe.conf.get("developer_mode")
            else None
        )
def _resolve_guardian_phone(guardian_id, scalar_phone, phone_map):
    """SĐT giám hộ: ưu tiên child table CRM Guardian Phone, fallback trường phẳng."""
    if guardian_id and phone_map.get(guardian_id):
        return phone_map[guardian_id]
    return (scalar_phone or "").strip() or None


def _enrich_families_with_members(families):
    """
    Gắn students[] / guardians[] (có relationship_types) cho danh sách gia đình.
    Batch query — tránh N+1 khi list V2 cần mã HS, SĐT, quan hệ.
    """
    if not families:
        return families

    family_names = [f.get("name") for f in families if f.get("name")]
    empty_members = {"students": [], "guardians": []}
    if not family_names:
        for family in families:
            family.update(empty_members)
        return families

    rows = frappe.db.sql(
        """
        SELECT
            fr.parent AS family_id,
            fr.student AS student_id,
            fr.guardian AS guardian_id,
            fr.relationship_type,
            s.student_code,
            s.student_name,
            g.guardian_name,
            g.phone_number AS guardian_phone_scalar
        FROM `tabCRM Family Relationship` fr
        LEFT JOIN `tabCRM Student` s ON fr.student = s.name
        LEFT JOIN `tabCRM Guardian` g ON fr.guardian = g.name
        WHERE fr.parent IN %(family_names)s
        ORDER BY fr.parent ASC, s.student_name ASC, g.guardian_name ASC
        """,
        {"family_names": tuple(family_names)},
        as_dict=True,
    ) or []

    guardian_ids = list({row.get("guardian_id") for row in rows if row.get("guardian_id")})
    phone_map = {}
    if guardian_ids:
        phone_rows = frappe.db.sql(
            """
            SELECT parent, phone_number, is_primary
            FROM `tabCRM Guardian Phone`
            WHERE parent IN %(guardian_ids)s
              AND phone_number IS NOT NULL
              AND phone_number != ''
            ORDER BY parent ASC, is_primary DESC, name ASC
            """,
            {"guardian_ids": tuple(guardian_ids)},
            as_dict=True,
        ) or []
        for phone_row in phone_rows:
            parent = phone_row.get("parent")
            phone_value = (phone_row.get("phone_number") or "").strip()
            if not parent or not phone_value:
                continue
            if parent not in phone_map or phone_row.get("is_primary") in (1, True):
                phone_map[parent] = phone_value

    students_by_family = {}
    guardians_by_family = {}

    for row in rows:
        family_id = row.get("family_id")
        if not family_id:
            continue

        student_id = row.get("student_id")
        if student_id:
            family_students = students_by_family.setdefault(family_id, {})
            if student_id not in family_students:
                family_students[student_id] = {
                    "student_code": row.get("student_code") or "",
                    "student_name": row.get("student_name") or "",
                }

        guardian_id = row.get("guardian_id")
        if guardian_id:
            family_guardians = guardians_by_family.setdefault(family_id, {})
            if guardian_id not in family_guardians:
                family_guardians[guardian_id] = {
                    "guardian_name": row.get("guardian_name") or "",
                    "phone_number": _resolve_guardian_phone(
                        guardian_id,
                        row.get("guardian_phone_scalar"),
                        phone_map,
                    ),
                    "relationship_types": [],
                }
            rel_type = (row.get("relationship_type") or "").strip()
            if rel_type:
                rel_list = family_guardians[guardian_id]["relationship_types"]
                if rel_type not in rel_list:
                    rel_list.append(rel_type)

    for family in families:
        family_id = family.get("name")
        family["students"] = list(students_by_family.get(family_id, {}).values())
        family["guardians"] = list(guardians_by_family.get(family_id, {}).values())

    return families


@frappe.whitelist(allow_guest=False)
def get_all_families():
    """Get all families without pagination - always returns full dataset"""
    try:
        frappe.logger().info("get_all_families called - fetching all families (no backend pagination)")
        
        filters = {}
        
        frappe.logger().info(f"Query filters: {filters}")
        frappe.logger().info("Fetching all families from database")
        
        # Get all families with relationships and student/guardian details (no pagination)
        families = frappe.db.sql("""
            SELECT 
                f.name,
                f.family_code,
                f.creation,
                f.modified,
                COUNT(DISTINCT fr.student) as student_count,
                COUNT(DISTINCT fr.guardian) as guardian_count,
                GROUP_CONCAT(DISTINCT s.student_name ORDER BY s.student_name SEPARATOR ', ') as student_names,
                GROUP_CONCAT(DISTINCT g.guardian_name ORDER BY g.guardian_name SEPARATOR ', ') as guardian_names
            FROM `tabCRM Family` f
            LEFT JOIN `tabCRM Family Relationship` fr ON f.name = fr.parent
            LEFT JOIN `tabCRM Student` s ON fr.student = s.name
            LEFT JOIN `tabCRM Guardian` g ON fr.guardian = g.name
            GROUP BY f.name, f.family_code, f.creation, f.modified
            ORDER BY f.family_code ASC
        """, as_dict=True)
        
        families = _enrich_families_with_members(families)
        
        frappe.logger().info(f"Total families fetched: {len(families)}")
        
        # Always return all families without pagination
        return success_response(
            data=families,
            message=f"Successfully fetched {len(families)} families"
        )
        
    except Exception as e:
        frappe.log_error(f"Error fetching families: {str(e)}")
        return error_response(
            message="Error fetching families",
            code="FETCH_FAMILIES_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def get_family_data(family_id=None, student_id=None, guardian_id=None):
    """Tra cứu gia đình theo family_id, hoặc theo học sinh / người giám hộ.

    ĐỔI SHAPE (frontend phải sửa theo — xem ghi chú cuối docstring). Bản cũ đọc
    `CRM Family.student_id / guardian_id / relationship / key_person / access`.
    Những field đó KHÔNG còn tồn tại: CRM Family giờ chỉ có campus_id / family_code /
    relationships (child table), vì `relationship_type`, `key_person`, `access` là thuộc
    tính của CẶP (student, guardian) — mỗi cháu một người liên lạc chính, quyền xem cấp
    riêng từng cháu — chứ không phải thuộc tính của cả gia đình. Gọi bản cũ chắc chắn lỗi
    (`frappe.get_all` với filter field không tồn tại).

    Nguồn đọc là bảng con CHUẨN `CRM Family.relationships`, KHÔNG dùng mirror ở
    `CRM Student.family_relationships` / `CRM Guardian.student_relationships`.

    Shape trả về:
      - family_id  -> single item: gia đình + TOÀN BỘ `relationships[]` của gia đình.
      - student_id + guardian_id -> single item: gia đình chứa cặp đó, `relationships[]`
        chỉ gồm cặp đó.
      - student_id (hoặc guardian_id) -> list: mỗi phần tử một gia đình, `relationships[]`
        chỉ gồm quan hệ của chính đối tượng được hỏi.
    Không còn field phẳng student_id/guardian_id/relationship/key_person/access ở cấp
    gia đình. Cần đủ students/guardians kèm tên hiển thị thì dùng `get_family_details`.
    """
    try:
        family_id = family_id or _param_from_request("family_id", "id", "name")
        student_id = student_id or _param_from_request("student_id", "student")
        guardian_id = guardian_id or _param_from_request("guardian_id", "guardian")

        frappe.logger().info(
            f"get_family_data called - family_id: {family_id}, "
            f"student_id: {student_id}, guardian_id: {guardian_id}"
        )

        if not family_id and not student_id and not guardian_id:
            return error_response(
                message="Family ID, Student ID, or Guardian ID is required",
                code="MISSING_FAMILY_ID"
            )

        # --- Theo family_id: trả gia đình + toàn bộ quan hệ của nó ---------------
        if family_id:
            fam_row = frappe.db.get_value(
                "CRM Family",
                family_id,
                ["name", "family_code", "campus_id", "creation", "modified"],
                as_dict=True,
            )
            if not fam_row:
                return not_found_response(
                    message="Family not found",
                    code="FAMILY_NOT_FOUND"
                )

            rels = frappe.get_all(
                "CRM Family Relationship",
                filters={"parent": family_id, "parentfield": "relationships"},
                fields=[
                    "student", "guardian", "relationship_type",
                    "key_person", "access", "display_order",
                ],
                order_by="display_order asc, idx asc",
            )

            return single_item_response(
                data={
                    "name": fam_row.get("name"),
                    "family_code": fam_row.get("family_code"),
                    "campus_id": fam_row.get("campus_id"),
                    "creation": _iso_or_none(fam_row.get("creation")),
                    "modified": _iso_or_none(fam_row.get("modified")),
                    "relationships": [_relationship_view(r) for r in rels],
                },
                message="Family fetched successfully"
            )

        # --- Theo học sinh / người giám hộ: nhóm dòng chuẩn theo gia đình --------
        rows = _canonical_rows_with_family(student=student_id, guardian=guardian_id)
        if not rows:
            if student_id and guardian_id:
                message = "Family not found"
            elif student_id:
                message = "No families found for this student"
            else:
                message = "No families found for this guardian"
            return not_found_response(message=message, code="FAMILY_NOT_FOUND")

        families_by_id = {}
        for row in rows:
            family = families_by_id.setdefault(
                row.get("family_id"),
                {
                    "name": row.get("family_id"),
                    "family_code": row.get("family_code"),
                    "campus_id": row.get("campus_id"),
                    "creation": _iso_or_none(row.get("creation")),
                    "modified": _iso_or_none(row.get("modified")),
                    "relationships": [],
                },
            )
            family["relationships"].append(_relationship_view(row))

        family_data = list(families_by_id.values())

        # Hỏi đúng một CẶP (student, guardian) thì bản cũ trả single item — giữ nguyên.
        if student_id and guardian_id:
            return single_item_response(
                data=family_data[0],
                message="Family fetched successfully"
            )

        return list_response(
            data=family_data,
            message="Families fetched successfully"
        )

    except Exception as e:
        frappe.log_error("get_family_data failed", frappe.get_traceback(with_context=True))
        return error_response(
            message="Error fetching family data",
            code="FETCH_FAMILY_DATA_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def create_family():
    """Create a new family with multiple students and guardians - NEW STRUCTURE"""
    try:
        # Get data from request
        data = {}
        
        # First try to get JSON data from request body
        if frappe.request.data:
            try:
                # Support both bytes and string payloads
                if isinstance(frappe.request.data, bytes):
                    json_data = json.loads(frappe.request.data.decode('utf-8'))
                else:
                    json_data = json.loads(frappe.request.data)

                if json_data:
                    data = json_data
                    frappe.logger().info(f"Received JSON data for create_family: {data}")
                else:
                    data = frappe.local.form_dict
                    frappe.logger().info(f"Received form data for create_family (empty JSON body): {data}")
            except (json.JSONDecodeError, TypeError, UnicodeDecodeError) as e:
                # If JSON parsing fails, use form_dict
                frappe.logger().error(f"JSON parsing failed in create_family: {str(e)}")
                data = frappe.local.form_dict
                frappe.logger().info(f"Using form data for create_family after JSON failure: {data}")
        else:
            # Fallback to form_dict
            data = frappe.local.form_dict
            frappe.logger().info(f"No request data, using form_dict for create_family: {data}")
        
        # Extract values from data - handle both JSON and form data
        # Try to get from main data first, then from form_dict
        students = data.get("students") or frappe.local.form_dict.get("students", [])
        guardians = data.get("guardians") or frappe.local.form_dict.get("guardians", [])
        relationships = data.get("relationships") or frappe.local.form_dict.get("relationships", [])
        
        frappe.logger().info(f"Raw students: {students} (type: {type(students)})")
        frappe.logger().info(f"Raw guardians: {guardians} (type: {type(guardians)})")
        frappe.logger().info(f"Raw relationships: {relationships} (type: {type(relationships)})")
        
        # Parse JSON strings if they come from form data
        if isinstance(students, str):
            try:
                students = json.loads(students)
                frappe.logger().info(f"Parsed students from JSON: {students}")
            except json.JSONDecodeError as e:
                frappe.logger().error(f"Failed to parse students JSON: {e}")
                students = []
                
        if isinstance(guardians, str):
            try:
                guardians = json.loads(guardians)
                frappe.logger().info(f"Parsed guardians from JSON: {guardians}")
            except json.JSONDecodeError as e:
                frappe.logger().error(f"Failed to parse guardians JSON: {e}")
                guardians = []
                
        if isinstance(relationships, str):
            try:
                relationships = json.loads(relationships)
                frappe.logger().info(f"Parsed relationships from JSON: {relationships}")
            except json.JSONDecodeError as e:
                frappe.logger().error(f"Failed to parse relationships JSON: {e}")
                relationships = []
        
        frappe.logger().info(f"Received data: {data}")
        frappe.logger().info(f"Students: {students}")
        frappe.logger().info(f"Guardians: {guardians}")
        frappe.logger().info(f"Relationships: {relationships}")
        
        # Input validation
        if not students or not guardians or not relationships:
            frappe.logger().error(f"Validation failed - students: {len(students) if students else 0}, guardians: {len(guardians) if guardians else 0}, relationships: {len(relationships) if relationships else 0}")
            return validation_error_response(
                message="Students, Guardians, and Relationships are required",
                errors={
                    "students": ["Required"] if not students else [],
                    "guardians": ["Required"] if not guardians else [],
                    "relationships": ["Required"] if not relationships else []
                }
            )
        
        if len(students) == 0 or len(guardians) == 0:
            return validation_error_response(
                message="At least one student and one guardian are required",
                errors={
                    "students": ["At least one student required"] if len(students) == 0 else [],
                    "guardians": ["At least one guardian required"] if len(guardians) == 0 else []
                }
            )
        
        # Create family first to get auto-generated FAM-xxx code
        family_doc = frappe.get_doc({
            "doctype": "CRM Family",
            "relationships": []
        })
        
        # Insert to get auto-generated name (FAM-1, FAM-2, etc.)
        family_doc.flags.ignore_validate = True
        # Bypass mandatory since family_code is required but will be set to name after insert
        family_doc.insert(ignore_permissions=True, ignore_mandatory=True)
        
        # Use the auto-generated name as family_code
        family_code = family_doc.name  # This will be FAM-1, FAM-2, etc.
        
        # Now update the family_code field to match the name (required field)
        family_doc.family_code = family_code
        family_doc.flags.ignore_validate = True
        family_doc.save(ignore_permissions=True)
        
        # Verify all students exist
        for student_id in students:
            if not frappe.db.exists("CRM Student", student_id):
                return not_found_response(
                    message=f"Student '{student_id}' not found",
                    code="STUDENT_NOT_FOUND"
                )
            existing_fam = _find_existing_family_for_student(student_id)
            if existing_fam:
                return validation_error_response(
                    message=f"Student already belongs to family {existing_fam['family_code']}",
                    errors={"student": [existing_fam['family_code']]}
                )
 
        # Verify all guardians exist
        for guardian_id in guardians:
            if not frappe.db.exists("CRM Guardian", guardian_id):
                return not_found_response(
                    message=f"Guardian '{guardian_id}' not found",
                    code="GUARDIAN_NOT_FOUND"
                )
        
        # KHÔNG validate "phải có ≥1 người liên lạc chính" ở mức family: key_person là
        # thuộc tính per-cháu, đặt ở màn lead của từng cháu (màn Gia đình chỉ quản
        # thành viên nên payload có thể không gửi key_person nào).

        # Add relationships to the existing family_doc
        for rel in relationships:
            family_doc.append("relationships", {
                "student": rel.get("student"),
                "guardian": rel.get("guardian"),
                # Màn Gia đình chỉ quản thành viên — quan hệ chỉnh ở màn từng cháu,
                # nên thiếu thì default "other" (relationship_type reqd=1).
                "relationship_type": normalize_relationship(rel.get("relationship_type")) or "other",
                "key_person": int(rel.get("key_person") or 0),
                "access": int(True if rel.get("access") is None else bool(rel.get("access"))),
                # Xem ghi chú ở update_family_members: append KHÔNG áp default doctype.
                "can_pickup": int(True if rel.get("can_pickup") is None else bool(rel.get("can_pickup"))),
            })
        
        # Save the family with relationships
        family_doc.save(ignore_permissions=True)
        
        # Update students with family_code and family_relationships
        for student_id in students:
            try:
                frappe.logger().info(f"Updating student {student_id} with family_code {family_code}")
                student_doc = frappe.get_doc("CRM Student", student_id)
                frappe.logger().info(f"Student doc before update: family_code = {student_doc.family_code}")
                student_doc.family_code = family_code
                student_doc.flags.ignore_validate = True
                student_doc.save(ignore_permissions=True)

                # Mirror dựng từ dòng CHUẨN đã ghi ở trên, không dựng lại từ `relationships`:
                # bản cũ mặc định access=False cho mirror trong khi dòng chuẩn là True, nên
                # mirror lệch access ngay lúc tạo; và thiếu can_pickup thì mirror về 0.
                rebuild_student_relationship_mirror(student_id)
                frappe.logger().info(f"Successfully updated student {student_id}")
            except Exception as e:
                frappe.logger().error(f"Error updating student {student_id}: {str(e)}")
                raise
        
        # Update guardians with family_code and student_relationships
        for guardian_id in guardians:
            try:
                frappe.logger().info(f"Updating guardian {guardian_id} with family_code {family_code}")
                guardian_doc = frappe.get_doc("CRM Guardian", guardian_id)
                frappe.logger().info(f"Guardian doc before update: family_code = {guardian_doc.family_code}")
                guardian_doc.family_code = family_code
                guardian_doc.flags.ignore_validate = True
                guardian_doc.save(ignore_permissions=True)

                # Mirror dựng từ dòng CHUẨN (helper tự gom mọi family của guardian) — xem
                # ghi chú ở vòng lặp student phía trên.
                rebuild_guardian_relationship_mirror(guardian_id)
                frappe.logger().info(f"Successfully updated guardian {guardian_id}")
            except Exception as e:
                frappe.logger().error(f"Error updating guardian {guardian_id}: {str(e)}")
                raise
        
        frappe.db.commit()
        
        # Return consistent API response format
        return single_item_response(
            data={
                "family_code": family_code,
                "students": students,
                "guardians": guardians,
                "relationships": relationships
            },
            message="Family created successfully"
        )
        
    except Exception as e:
        frappe.log_error(f"Error creating family: {str(e)}")
        return error_response(
            message="Error creating family",
            code="CREATE_FAMILY_ERROR"
        )


@frappe.whitelist(allow_guest=False, methods=['GET', 'POST'])
def update_family(
    family_id=None,
    student=None,
    guardian=None,
    relationship=None,
    relationship_type=None,
    key_person=None,
    access=None,
):
    """Sửa MỘT quan hệ: loại quan hệ / người liên lạc chính / quyền xem của một CẶP.

    ĐỔI THAM SỐ BẮT BUỘC (frontend phải sửa theo): nay phải truyền `student` + `guardian`.
    Bản cũ ghi thẳng `CRM Family.relationship / key_person / access` — schema đó đã bỏ,
    ba thuộc tính này là của CẶP (student, guardian): mỗi cháu một người liên lạc chính,
    quyền xem cấp riêng từng cháu. `family_id` một mình KHÔNG định vị được dòng nào phải
    sửa; ghi theo family_id chính là lớp bug clobber (sửa 1 cháu, hỏng cả nhà) đã bị cấm.
    `family_id` giờ là TUỲ CHỌN, chỉ dùng để khử nhập nhằng nếu cặp đó có ở nhiều gia đình.

    Thay toàn bộ thành viên/quan hệ của một gia đình -> dùng `update_family_members`.
    """
    try:
        # Tham số nhận từ arg, form_dict, query args hoặc JSON body.
        family_id = family_id or _param_from_request("family_id")
        student = student or _param_from_request("student", "student_id")
        guardian = guardian or _param_from_request("guardian", "guardian_id")
        if relationship in (None, ""):
            relationship = _param_from_request("relationship")
        if relationship_type in (None, ""):
            relationship_type = _param_from_request("relationship_type")
        if key_person is None:
            key_person = _param_from_request("key_person")
        if access is None:
            access = _param_from_request("access")

        student = (str(student).strip() if student else "")
        guardian = (str(guardian).strip() if guardian else "")

        if not student or not guardian:
            return validation_error_response(
                message=(
                    "Cần cả student và guardian: loại quan hệ, người liên lạc chính và "
                    "quyền xem là thuộc tính của từng cặp học sinh - người giám hộ, "
                    "không phải của cả gia đình"
                ),
                errors={
                    "student": ["Required"] if not student else [],
                    "guardian": ["Required"] if not guardian else [],
                },
                code="MISSING_RELATIONSHIP_GRAIN",
            )

        # Định vị dòng CHUẨN của cặp này (bảng con dưới CRM Family), không đọc mirror.
        rows = _canonical_rows_with_family(student=student, guardian=guardian)
        if family_id:
            rows = [row for row in rows if row.get("family_id") == family_id]
        if not rows:
            return not_found_response(
                message="Không tìm thấy quan hệ của cặp học sinh - người giám hộ này",
                code="RELATIONSHIP_NOT_FOUND",
            )

        target_families = {row.get("family_id") for row in rows}
        if len(target_families) > 1:
            return validation_error_response(
                message="Cặp này xuất hiện ở nhiều gia đình, cần truyền family_id",
                errors={"family_id": ["Required"]},
                code="AMBIGUOUS_FAMILY",
            )
        target_family = rows[0].get("family_id")

        # Gom các thay đổi được yêu cầu.
        changes = {}

        raw_relationship = relationship if relationship not in (None, "") else relationship_type
        if raw_relationship not in (None, "", "null"):
            new_relationship = normalize_relationship(raw_relationship)
            # normalize() trả nguyên giá trị gốc khi không nhận diện được -> phải chặn ở đây,
            # nếu không sẽ ghi mã rác vào relationship_type.
            if not is_known_relationship_code(new_relationship):
                return validation_error_response(
                    message=f"Loại quan hệ phải thuộc: {', '.join(RELATIONSHIP_CODES)}",
                    errors={"relationship": ["Invalid relationship type"]},
                )
            changes["relationship_type"] = new_relationship

        if key_person is not None:
            changes["key_person"] = _parse_bool_flag(key_person)
        if access is not None:
            changes["access"] = _parse_bool_flag(access)

        current = _relationship_view(rows[0])
        if not changes:
            return single_item_response(
                data={
                    "name": target_family,
                    "family_code": rows[0].get("family_code"),
                    "relationships": [current],
                },
                message="Không có thay đổi nào được yêu cầu",
            )

        # Bỏ cờ liên lạc chính thì cháu đó phải còn người liên lạc chính khác — cùng luật
        # "phải chọn ít nhất 1 người liên lạc chính" của update_family_members, nhưng xét ở
        # đúng grain HỌC SINH. Đọc lại dòng chuẩn của cháu qua helper dùng chung.
        # Chỉ chặn khi THẬT SỰ đang bỏ cờ: gửi key_person=0 cho dòng vốn đã 0 là no-op,
        # không được vì thế mà từ chối request (dữ liệu cũ có cháu chưa ai là liên lạc chính).
        currently_key_person = any(bool(row.get("key_person")) for row in rows)
        if changes.get("key_person") == 0 and currently_key_person:
            other_key_persons = [
                row
                for row in canonical_relationship_rows(student=student)
                if row.get("key_person") and row.get("guardian") != guardian
            ]
            if not other_key_persons:
                return validation_error_response(
                    message="Mỗi học sinh phải có ít nhất 1 người liên lạc chính",
                    errors={"key_person": ["Required"]},
                    code="KEY_PERSON_REQUIRED",
                )

        savepoint = "update_family_relationship"
        frappe.db.savepoint(savepoint)
        try:
            family_doc = frappe.get_doc("CRM Family", target_family)
            # CHỈ đụng dòng của đúng cặp (student, guardian). Dữ liệu xấu có thể có nhiều
            # dòng trùng cặp -> sửa hết, vẫn nằm trong grain của cặp đó.
            matched = [
                child
                for child in family_doc.relationships
                if child.student == student and child.guardian == guardian
            ]
            if not matched:
                frappe.db.rollback(save_point=savepoint)
                return not_found_response(
                    message="Không tìm thấy quan hệ của cặp học sinh - người giám hộ này",
                    code="RELATIONSHIP_NOT_FOUND",
                )

            for child in matched:
                for field, value in changes.items():
                    child.set(field, value)

            family_doc.flags.ignore_validate = True
            family_doc.save(ignore_permissions=True)

            # Mirror ở CRM Student / CRM Guardian dựng lại TỪ DÒNG CHUẨN vừa ghi
            # (helper tự gom mọi family của PH nên không xoá mất quan hệ ở family khác).
            rebuild_student_relationship_mirror(student)
            rebuild_guardian_relationship_mirror(guardian)
        except Exception:
            frappe.db.rollback(save_point=savepoint)
            raise

        # `access` quyết định PH có được vào nhóm chat lớp không (xem
        # build_guardians_by_student_ids(access_only=True)) nhưng KHÔNG nằm trong
        # _RELATIONSHIP_KEYS của chat_membership_hooks, nên doc-event on_family_change
        # không nhận ra thay đổi chỉ-đổi-access -> phải tự bắn sync.
        if "access" in changes:
            try:
                from erp.api.erp_sis.chat_membership_hooks import (
                    enqueue_chat_membership_sync_for_students,
                )

                enqueue_chat_membership_sync_for_students({student})
            except Exception as sync_error:
                frappe.logger().warning(
                    f"[Family] enqueue chat membership sync failed for {student}: {str(sync_error)}"
                )

        # after_commit callbacks (realtime, enqueue_after_commit) chạy SAU khi SQL đã
        # COMMIT — lỗi ở đó nghĩa là dữ liệu ĐÃ lưu, không được báo thất bại.
        try:
            frappe.db.commit()
        except Exception as commit_error:
            frappe.logger().warning(
                f"[Family] post-commit side effect failed for {target_family}: {str(commit_error)}"
            )
            frappe.log_error(
                "update_family post-commit",
                frappe.get_traceback(with_context=True),
            )

        updated = frappe.db.sql(
            """
            SELECT fr.student, fr.guardian, fr.relationship_type, fr.key_person, fr.access
            FROM `tabCRM Family Relationship` fr
            WHERE fr.parent = %(family)s AND fr.parentfield = 'relationships'
              AND fr.student = %(student)s AND fr.guardian = %(guardian)s
            """,
            {"family": target_family, "student": student, "guardian": guardian},
            as_dict=True,
        ) or []

        return single_item_response(
            data={
                "name": target_family,
                "family_code": rows[0].get("family_code"),
                # Cùng shape với get_family_data: gia đình + quan hệ (ở đây là cặp vừa sửa).
                "relationships": [
                    _relationship_view(updated[0]) if updated else current
                ],
            },
            message="Family relationship updated successfully"
        )

    except Exception as e:
        frappe.log_error("update_family failed", frappe.get_traceback(with_context=True))
        return error_response(
            message="Error updating family",
            code="UPDATE_FAMILY_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def delete_family():
    """Delete a family relationship"""
    try:
        # Get family ID from multiple sources
        form = frappe.local.form_dict or {}
        family_id = form.get("family_id") or form.get("id") or form.get("name")
        # Also from query string
        try:
            args = getattr(frappe.request, 'args', None)
            if args and not family_id:
                family_id = args.get('family_id') or args.get('id') or args.get('name')
        except Exception:
            pass
        if not family_id and frappe.request and frappe.request.data:
            try:
                body = frappe.request.data
                if isinstance(body, bytes):
                    body = body.decode('utf-8')
                json_body = json.loads(body or '{}')
                family_id = json_body.get('family_id') or family_id
            except Exception:
                pass
        
        frappe.logger().info(f"delete_family called - family_id: {family_id}")
        
        if not family_id:
            return error_response(
                message="Family ID is required",
                code="MISSING_FAMILY_ID"
            )
        
        # Get family document
        try:
            family_doc = frappe.get_doc("CRM Family", family_id)
        except frappe.DoesNotExistError:
            return not_found_response(
                message="Family not found",
                code="FAMILY_NOT_FOUND"
            )

        # SIS Menu Registration.family_id đang BỎ DẦN (suất ăn thuộc học sinh, đăng ký
        # mới không ghi field này nữa) — gỡ tham chiếu cũ thay vì chặn xóa. Bản ghi
        # đăng ký giữ nguyên, vẫn tra được theo student_id.
        frappe.db.sql(
            "UPDATE `tabSIS Menu Registration` SET family_id = NULL WHERE family_id = %s",
            (family_id,),
        )

        # Chốt danh sách người bị ảnh hưởng TRƯỚC khi xóa (dòng chuẩn chết cùng parent).
        affected = frappe.db.sql(
            """
            SELECT student, guardian FROM `tabCRM Family Relationship`
            WHERE parent = %s AND parentfield = 'relationships'
            """,
            (family_id,),
            as_dict=True,
        )
        affected_students = {r["student"] for r in affected if r.get("student")}
        affected_guardians = {r["guardian"] for r in affected if r.get("guardian")}

        # CRM Lead.linked_family là field đang khai tử (đường đọc đã resolve qua
        # linked_student) — gỡ tham chiếu để không vướng LinkExistsError.
        frappe.db.sql(
            "UPDATE `tabCRM Lead` SET linked_family = NULL WHERE linked_family = %s",
            (family_id,),
        )

        # Delete the document
        frappe.delete_doc("CRM Family", family_id)

        # Dọn hậu quả trên người liên quan:
        # - family_code phẳng: student hết family -> NULL; guardian có thể còn family
        #   khác -> trỏ sang family còn lại, không còn thì NULL.
        # - 2 bản mirror dựng lại từ dòng chuẩn (family vừa xóa tự biến mất khỏi mirror);
        #   không dọn thì guardian "ma" vẫn nhận thông báo/menu qua mirror cũ.
        fam_code = getattr(family_doc, "family_code", None) or family_id
        for sid in affected_students:
            if frappe.db.exists("CRM Student", sid):
                if frappe.db.get_value("CRM Student", sid, "family_code") in (family_id, fam_code):
                    frappe.db.set_value("CRM Student", sid, "family_code", None, update_modified=False)
                rebuild_student_relationship_mirror(sid)
        for gid in affected_guardians:
            if frappe.db.exists("CRM Guardian", gid):
                remaining = canonical_relationship_rows(guardian=gid)
                new_code = None
                if remaining:
                    fam_left = remaining[0].get("family")
                    new_code = frappe.db.get_value("CRM Family", fam_left, "family_code") or fam_left
                frappe.db.set_value("CRM Guardian", gid, "family_code", new_code, update_modified=False)
                rebuild_guardian_relationship_mirror(gid)

        # Gỡ PH khỏi nhóm chat lớp: doc-event on_family_change không chạy cho delete,
        # sync tay như update_family_members.
        if affected_students:
            try:
                from erp.api.erp_sis.chat_membership_hooks import (
                    enqueue_chat_membership_sync_for_students,
                )
                enqueue_chat_membership_sync_for_students(affected_students)
            except Exception:
                frappe.log_error("delete_family: loi enqueue chat sync", frappe.get_traceback())

        frappe.db.commit()

        return success_response(
            message="Family relationship deleted successfully"
        )
        
    except Exception as e:
        frappe.log_error("delete_family failed", frappe.get_traceback(with_context=True))
        return error_response(
            message="Error deleting family",
            code="DELETE_FAMILY_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def search_families(search_term=None, page=1, limit=20):
    """Search families with pagination"""
    try:
        # Normalize parameters: prefer form_dict values if provided
        form = frappe.local.form_dict or {}
        if 'search_term' in form and (search_term is None or str(search_term).strip() == ''):
            search_term = form.get('search_term')
        # Coerce page/limit from form if present
        page = int(form.get('page', page))
        limit = int(form.get('limit', limit))

        frappe.logger().info(f"search_families called with search_term: '{search_term}', page: {page}, limit: {limit}")
        
        # Build search terms (use parameterized queries)
        where_clauses = ["1=1"]  # Base condition
        params = []

        campus_id = get_current_campus_from_context()
        if campus_id:
            # Lọc family có student hoặc campus_id trùng campus đang chọn
            where_clauses.append(
                "(f.campus_id = %s OR s.campus_id = %s OR g.campus_id = %s)"
            )
            params.extend([campus_id, campus_id, campus_id])

        if search_term and str(search_term).strip():
            search_frag, search_params = build_search_condition(
                ["f.family_code", "s.student_name", "g.guardian_name"],
                search_term,
            )
            if search_frag:
                where_clauses.append(search_frag)
                params.extend(search_params)
        
        conditions = " AND ".join(where_clauses)
        frappe.logger().info(f"FINAL WHERE: {conditions} | params: {params}")
        
        # Calculate offset
        offset = (page - 1) * limit
        
        # Get families with search (parameterized) - join with student and guardian names
        sql_query = (
            """
            SELECT 
                f.name,
                f.family_code,
                f.creation,
                f.modified,
                COUNT(DISTINCT fr.student) as student_count,
                COUNT(DISTINCT fr.guardian) as guardian_count,
                GROUP_CONCAT(DISTINCT s.student_name SEPARATOR ', ') as student_names,
                GROUP_CONCAT(DISTINCT g.guardian_name SEPARATOR ', ') as guardian_names
            FROM `tabCRM Family` f
            LEFT JOIN `tabCRM Family Relationship` fr ON f.name = fr.parent
            LEFT JOIN `tabCRM Student` s ON fr.student = s.name
            LEFT JOIN `tabCRM Guardian` g ON fr.guardian = g.name
            WHERE {where}
            GROUP BY f.name, f.family_code, f.creation, f.modified
            ORDER BY f.family_code ASC
            LIMIT %s OFFSET %s
            """
        ).format(where=conditions)

        frappe.logger().info(f"EXECUTING SQL QUERY: {sql_query} | params={params + [limit, offset]}")

        families = frappe.db.sql(sql_query, params + [limit, offset], as_dict=True)

        frappe.logger().info(f"SQL QUERY RETURNED {len(families)} families")
        
        # Get total count (parameterized)
        count_query = (
            """
            SELECT COUNT(DISTINCT f.name) as count
            FROM `tabCRM Family` f
            LEFT JOIN `tabCRM Family Relationship` fr ON f.name = fr.parent
            LEFT JOIN `tabCRM Student` s ON fr.student = s.name
            LEFT JOIN `tabCRM Guardian` g ON fr.guardian = g.name
            WHERE {where}
            """
        ).format(where=conditions)
        
        frappe.logger().info(f"EXECUTING COUNT QUERY: {count_query} | params={params}")
        
        total_count = frappe.db.sql(count_query, params, as_dict=True)[0]['count']
        
        frappe.logger().info(f"COUNT QUERY RETURNED: {total_count}")
        
        total_pages = (total_count + limit - 1) // limit
        
        return paginated_response(
            data=families,
            current_page=page,
            total_count=total_count,
            per_page=limit,
            message="Family search completed successfully"
        )
        
    except Exception as e:
        frappe.log_error(f"Error searching families: {str(e)}")
        return error_response(
            message="Error searching families",
            code="SEARCH_FAMILIES_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def get_families_for_selection():
    """Get families for dropdown selection - NEW STRUCTURE"""
    try:
        families = frappe.db.sql("""
            SELECT 
                f.name,
                f.family_code,
                COUNT(DISTINCT fr.student) as student_count,
                COUNT(DISTINCT fr.guardian) as guardian_count,
                GROUP_CONCAT(DISTINCT s.student_name SEPARATOR ', ') as student_names,
                GROUP_CONCAT(DISTINCT g.guardian_name SEPARATOR ', ') as guardian_names
            FROM `tabCRM Family` f
            LEFT JOIN `tabCRM Family Relationship` fr ON f.name = fr.parent
            LEFT JOIN `tabCRM Student` s ON fr.student = s.name
            LEFT JOIN `tabCRM Guardian` g ON fr.guardian = g.name
            GROUP BY f.name, f.family_code
            ORDER BY f.family_code ASC
        """, as_dict=True)
        
        return success_response(
            data=families,
            message="Families fetched successfully"
        )
    except Exception as e:
        frappe.log_error(f"Error fetching families for selection: {str(e)}")
        return error_response(
            message="Error fetching families",
            code="FETCH_FAMILIES_SELECTION_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def get_family_codes(student_id=None, guardian_id=None):
    """Return list of families (name, family_code) for a given student or guardian.
    Accepts params from query args, form_dict, or JSON body.
    """
    try:
        form = frappe.local.form_dict or {}
        if not student_id and not guardian_id:
            student_id = form.get("student_id")
            guardian_id = form.get("guardian_id")
        # From query args
        try:
            args = getattr(frappe.request, 'args', None)
            if args and not (student_id or guardian_id):
                student_id = args.get('student_id')
                guardian_id = args.get('guardian_id')
        except Exception:
            pass
        # From JSON body
        if not (student_id or guardian_id) and frappe.request and frappe.request.data:
            try:
                body = frappe.request.data
                if isinstance(body, bytes):
                    body = body.decode('utf-8')
                json_body = json.loads(body or '{}')
                student_id = json_body.get('student_id') or student_id
                guardian_id = json_body.get('guardian_id') or guardian_id
            except Exception:
                pass

        if not student_id and not guardian_id:
            return error_response(
                message="student_id or guardian_id is required",
                code="MISSING_STUDENT_OR_GUARDIAN_ID"
            )

        if student_id:
            rows = frappe.db.sql(
                """
                SELECT f.name, f.family_code
                FROM `tabCRM Family` f
                INNER JOIN `tabCRM Family Relationship` fr ON fr.parent = f.name
                WHERE fr.student = %s
                GROUP BY f.name, f.family_code
                ORDER BY f.family_code ASC
                """,
                (student_id,),
                as_dict=True,
            )
        else:
            rows = frappe.db.sql(
                """
                SELECT f.name, f.family_code
                FROM `tabCRM Family` f
                INNER JOIN `tabCRM Family Relationship` fr ON fr.parent = f.name
                WHERE fr.guardian = %s
                GROUP BY f.name, f.family_code
                ORDER BY f.family_code ASC
                """,
                (guardian_id,),
                as_dict=True,
            )

        return success_response(
            data=rows,
            message="Family codes fetched"
        )
    except Exception as e:
        frappe.log_error(f"Error get_family_codes: {str(e)}")
        return error_response(
            message="Error fetching family codes",
            code="FETCH_FAMILY_CODES_ERROR"
        )


@frappe.whitelist(allow_guest=False, methods=['POST'])
def bulk_import_families():
    """Bulk import families from Excel template

    Required columns per row:
    - student_code_1..student_code_4 (at least 1 required)
    - guardian_1_phone (required)
    - relationship_1 (required)
    - is_main_contact_1 (Y/N)
    - can_view_information_1 (Y/N)
    Optional guardian_2/guardian_3 columns follow same pattern.
    """
    try:
        uploaded_file = frappe.request.files.get('file') if hasattr(frappe.request, 'files') else None
        if not uploaded_file:
            return validation_error_response(
                message="Missing file upload",
                errors={"file": ["Required"]}
            )

        try:
            df = pd.read_excel(uploaded_file, sheet_name=0)
        except Exception as e:
            frappe.log_error(f"bulk_import_families: failed to read excel - {str(e)}")
            return error_response(
                message="Không đọc được file Excel. Hãy dùng đúng mẫu.",
                code="FAMILY_IMPORT_READ_ERROR"
            )

        campus_id = get_current_campus_from_context()
        if not campus_id:
            return forbidden_response(
                message="Không xác định được campus của người dùng",
                code="NO_CAMPUS_ACCESS"
            )

        try:
            result = process_family_import_rows(df, campus_id)
        except frappe.ValidationError as ve:
            return validation_error_response(
                message=str(ve),
                errors={"row": [str(ve)]}
            )
        except Exception as e:
            frappe.log_error(f"bulk_import_families runtime error: {str(e)}")
            return error_response(
                message="Có lỗi xảy ra khi xử lý dữ liệu",
                code="FAMILY_IMPORT_PROCESS_ERROR"
            )

        success_count = result.get("success_count", 0)
        errors = result.get("errors", [])
        error_count = len(errors)

        if errors:
            try:
                error_file_url = generate_family_import_error_file(errors)
            except Exception as e:
                frappe.log_error(f"Failed to generate error file for family import: {str(e)}")
                error_file_url = None

            message = _(f"Import hoàn tất: {success_count} gia đình thành công, {error_count} lỗi")
            return error_response(
                data={
                    "success_count": success_count,
                    "error_count": error_count,
                    "errors": errors[:20],
                    "error_file_url": error_file_url
                },
                message=message,
                code="FAMILY_IMPORT_PARTIAL_FAIL"
            )

        return success_response(
            data={
                "success_count": success_count,
                "error_count": error_count
            },
            message=_("Import hoàn tất: {success_count} gia đình thành công")
        )

    except Exception as e:
        frappe.log_error(f"bulk_import_families error: {str(e)}")
        return error_response(
            message="Có lỗi xảy ra khi import gia đình",
            code="FAMILY_IMPORT_ERROR"
        )