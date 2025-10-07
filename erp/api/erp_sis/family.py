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

                relationship_map = {
                    'bố': 'dad', 'bo': 'dad', 'cha': 'dad', 'father': 'dad',
                    'mẹ': 'mom', 'me': 'mom', 'mother': 'mom',
                    'ông': 'grandparent', 'ba': 'grandparent', 'bà': 'grandparent', 'grandparent': 'grandparent',
                    'anh': 'sibling', 'chị': 'sibling', 'em': 'sibling', 'sibling': 'sibling',
                    'cô': 'uncle_aunt', 'chú': 'uncle_aunt', 'dì': 'uncle_aunt', 'bác': 'uncle_aunt', 'uncle': 'uncle_aunt', 'aunt': 'uncle_aunt',
                    'nuôi': 'foster_parent', 'foster': 'foster_parent', 'cha nuôi': 'foster_parent', 'mẹ nuôi': 'foster_parent',
                }
                key = relationship_value.lower().strip()
                relationship_code = relationship_map.get(key, relationship_value)

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
                        "access": view_flag
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

            for student_id in student_ids:
                student_doc = frappe.get_doc("CRM Student", student_id)
                student_doc.family_code = family_doc.family_code
                student_doc.set("family_relationships", [])
                for rel in relationships:
                    if rel['student'] == student_id:
                        student_doc.append("family_relationships", rel)
                student_doc.flags.ignore_validate = True
                student_doc.save(ignore_permissions=True)

            for guardian_id in guardians:
                guardian_doc = frappe.get_doc("CRM Guardian", guardian_id)
                guardian_doc.family_code = family_doc.family_code
                guardian_doc.set("student_relationships", [])
                for rel in relationships:
                    if rel['guardian'] == guardian_id:
                        guardian_doc.append("student_relationships", rel)
                guardian_doc.flags.ignore_validate = True
                guardian_doc.save(ignore_permissions=True)

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
        frappe.log_error(f"Error fetching family details: {str(e)}")
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
        # Validate key person: must have at least 1
        key_person_count = sum(1 for rel in relationships if rel.get("key_person"))
        if key_person_count == 0:
            return validation_error_response(
                message="Phải chọn ít nhất 1 người liên lạc chính",
                errors={"key_person": ["Required"]}
            )

        # Log key person count for debugging
        frappe.logger().info(f"Key person count for family: {key_person_count}")
        frappe.logger().info(f"Total relationships: {len(relationships)}")

        # Note: Allow multiple key persons for flexibility in family structures
        # Previously enforced "Only one key person allowed" but removed for business flexibility
        # if key_person_count > 1:
        #     return validation_error_response(
        #         message="Chỉ được chọn 1 người liên lạc chính",
        #         errors={"key_person": ["Only one key person allowed"]}
        #     )
        
        # Reset relationships
        family_doc.set("relationships", [])
        for rel in relationships:
            family_doc.append("relationships", {
                "student": rel.get("student"),
                "guardian": rel.get("guardian"),
                "relationship_type": rel.get("relationship_type", ""),
                "key_person": int(rel.get("key_person", False)),
                "access": int(rel.get("access", True)),
            })
        family_doc.flags.ignore_validate = True
        family_doc.save(ignore_permissions=True)

        # Update students and guardians docs similar to create_family
        family_code = getattr(family_doc, 'family_code', family_doc.name)

        for student_id in students:
            if frappe.db.exists("CRM Student", student_id):
                existing_fam = _find_existing_family_for_student(student_id, exclude_family=family_id)
                if existing_fam:
                    return validation_error_response(
                        message=f"Student already belongs to family {existing_fam['family_code']}",
                        errors={"student": [existing_fam['family_code']]}
                    )
                student_doc = frappe.get_doc("CRM Student", student_id)
                student_doc.family_code = family_code
                student_doc.set("family_relationships", [])
                for rel in relationships:
                    if rel.get("student") == student_id:
                        student_doc.append("family_relationships", {
                            "student": student_id,
                            "guardian": rel.get("guardian"),
                            "relationship_type": rel.get("relationship_type", ""),
                            "key_person": int(rel.get("key_person", False)),
                            "access": int(rel.get("access", False)),
                        })
                student_doc.flags.ignore_validate = True
                student_doc.save(ignore_permissions=True)

        for guardian_id in guardians:
            if frappe.db.exists("CRM Guardian", guardian_id):
                guardian_doc = frappe.get_doc("CRM Guardian", guardian_id)
                guardian_doc.family_code = family_code
                guardian_doc.set("student_relationships", [])
                for rel in relationships:
                    if rel.get("guardian") == guardian_id:
                        guardian_doc.append("student_relationships", {
                            "student": rel.get("student"),
                            "guardian": guardian_id,
                            "relationship_type": rel.get("relationship_type", ""),
                            "key_person": int(rel.get("key_person", False)),
                            "access": int(rel.get("access", False)),
                        })
                guardian_doc.flags.ignore_validate = True
                guardian_doc.save(ignore_permissions=True)

        frappe.db.commit()

        return success_response(
            data={"family_id": family_doc.name},
            message="Family members updated successfully"
        )
    except Exception as e:
        frappe.log_error(f"Error updating family members: {str(e)}")
        return error_response(
            message="Error updating family members",
            code="UPDATE_FAMILY_ERROR"
        )
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
def get_family_data():
    """Get a specific family by ID"""
    try:
        # Get parameters from form_dict
        family_id = frappe.local.form_dict.get("family_id")
        student_id = frappe.local.form_dict.get("student_id")
        guardian_id = frappe.local.form_dict.get("guardian_id")
        
        frappe.logger().info(f"get_family_data called - family_id: {family_id}, student_id: {student_id}, guardian_id: {guardian_id}")
        frappe.logger().info(f"form_dict: {frappe.local.form_dict}")
        
        if not family_id and not student_id and not guardian_id:
            return error_response(
                message="Family ID, Student ID, or Guardian ID is required",
                code="MISSING_FAMILY_ID"
            )
        
        # Build filters based on what parameter we have
        if family_id:
            family = frappe.get_doc("CRM Family", family_id)
        elif student_id and guardian_id:
            # Search by both student and guardian
            families = frappe.get_all("CRM Family", 
                filters={
                    "student_id": student_id,
                    "guardian_id": guardian_id
                }, 
                fields=["name"], 
                limit=1)
            
            if not families:
                return not_found_response(
                    message="Family not found",
                    code="FAMILY_NOT_FOUND"
                )
            
            family = frappe.get_doc("CRM Family", families[0].name)
        elif student_id:
            # Search by student only
            families = frappe.get_all("CRM Family", 
                filters={"student_id": student_id}, 
                fields=["name"])
            
            if not families:
                return not_found_response(
                    message="No families found for this student",
                    code="FAMILY_NOT_FOUND"
                )
            
            # Return multiple families for this student
            family_data = []
            for f in families:
                doc = frappe.get_doc("CRM Family", f.name)
                family_data.append({
                    "name": doc.name,
                    "student_id": doc.student_id,
                    "guardian_id": doc.guardian_id,
                    "relationship": doc.relationship,
                    "key_person": doc.key_person,
                    "access": doc.access
                })
            
            return list_response(
                data=family_data,
                message="Families fetched successfully"
            )
        elif guardian_id:
            # Search by guardian only
            families = frappe.get_all("CRM Family", 
                filters={"guardian_id": guardian_id}, 
                fields=["name"])
            
            if not families:
                return not_found_response(
                    message="No families found for this guardian",
                    code="FAMILY_NOT_FOUND"
                )
            
            # Return multiple families for this guardian
            family_data = []
            for f in families:
                doc = frappe.get_doc("CRM Family", f.name)
                family_data.append({
                    "name": doc.name,
                    "student_id": doc.student_id,
                    "guardian_id": doc.guardian_id,
                    "relationship": doc.relationship,
                    "key_person": doc.key_person,
                    "access": doc.access
                })
            
            return list_response(
                data=family_data,
                message="Families fetched successfully"
            )
        
        if not family:
            return not_found_response(
                message="Family not found",
                code="FAMILY_NOT_FOUND"
            )
        
        return single_item_response(
            data={
                "name": family.name,
                "family_code": getattr(family, "family_code", None),
                "creation": family.creation.isoformat() if family.creation else None,
                "modified": family.modified.isoformat() if family.modified else None
            },
            message="Family fetched successfully"
        )
        
    except Exception as e:
        frappe.log_error(f"Error fetching family data: {str(e)}")
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
        
        # Validate key person: must have at least 1
        key_person_count = sum(1 for rel in relationships if rel.get("key_person"))
        if key_person_count == 0:
            return validation_error_response(
                message="Phải chọn ít nhất 1 người liên lạc chính",
                errors={"key_person": ["Required"]}
            )

        # Log key person count for debugging
        frappe.logger().info(f"Key person count for family: {key_person_count}")
        frappe.logger().info(f"Total relationships: {len(relationships)}")

        # Note: Allow multiple key persons for flexibility in family structures
        # Previously enforced "Only one key person allowed" but removed for business flexibility
        # if key_person_count > 1:
        #     return validation_error_response(
        #         message="Chỉ được chọn 1 người liên lạc chính",
        #         errors={"key_person": ["Only one key person allowed"]}
        #     )
        
        # Add relationships to the existing family_doc
        for rel in relationships:
            family_doc.append("relationships", {
                "student": rel.get("student"),
                "guardian": rel.get("guardian"),
                "relationship_type": rel.get("relationship_type", ""),
                "key_person": int(rel.get("key_person", False)),
                "access": int(rel.get("access", True))
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
                frappe.logger().info(f"Student doc after setting: family_code = {student_doc.family_code}")

                # Reset and append family relationships for this student (use child table API)
                student_doc.set("family_relationships", [])
                for rel in relationships:
                    if rel.get("student") == student_id:
                        student_doc.append("family_relationships", {
                            "student": student_id,
                            "guardian": rel.get("guardian"),
                            "relationship_type": rel.get("relationship_type", ""),
                            "key_person": int(rel.get("key_person", False)),
                            "access": int(rel.get("access", False))
                        })

                student_doc.flags.ignore_validate = True
                student_doc.save(ignore_permissions=True)
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
                frappe.logger().info(f"Guardian doc after setting: family_code = {guardian_doc.family_code}")

                # Reset and append student relationships for this guardian (use child table API)
                guardian_doc.set("student_relationships", [])
                for rel in relationships:
                    if rel.get("guardian") == guardian_id:
                        guardian_doc.append("student_relationships", {
                            "student": rel.get("student"),
                            "guardian": guardian_id,
                            "relationship_type": rel.get("relationship_type", ""),
                            "key_person": int(rel.get("key_person", False)),
                            "access": int(rel.get("access", False))
                        })

                guardian_doc.flags.ignore_validate = True
                guardian_doc.save(ignore_permissions=True)
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
def update_family(family_id=None, relationship=None, key_person=None, access=None):
    """Update an existing family relationship"""
    try:
        # Get parameters from multiple sources for flexibility
        if not family_id:
            family_id = frappe.local.form_dict.get("family_id")
        if not relationship:
            relationship = frappe.local.form_dict.get("relationship")
        if key_person is None:
            key_person = frappe.local.form_dict.get("key_person")
        if access is None:
            access = frappe.local.form_dict.get("access")
        
        # Fallback to JSON data if form_dict is empty
        if not family_id and frappe.request.data:
            try:
                import json
                json_data = json.loads(frappe.request.data.decode('utf-8'))
                family_id = json_data.get("family_id")
                relationship = json_data.get("relationship")
                key_person = json_data.get("key_person")
                access = json_data.get("access")
            except Exception:
                pass
        
        if not family_id:
            return error_response(
                message="Family ID is required",
                code="MISSING_FAMILY_ID"
            )
        
        # Get existing document
        try:
            family_doc = frappe.get_doc("CRM Family", family_id)
        except frappe.DoesNotExistError:
            return not_found_response(
                message="Family not found",
                code="FAMILY_NOT_FOUND"
            )
        
        # Track if any changes were made
        changes_made = False
        
        # Helper function to normalize values for comparison
        def normalize_value(val):
            """Convert None/null/empty to empty string for comparison"""
            if val is None or val == "null" or val == "":
                return ""
            return str(val).strip()
        
        # Update fields if provided
        if relationship and normalize_value(relationship) != normalize_value(family_doc.relationship):
            # Validate relationship
            valid_relationships = ["dad", "mom", "foster_parent", "grandparent", "uncle_aunt", "sibling", "other"]
            if relationship not in valid_relationships:
                return validation_error_response(
                    message=f"Relationship must be one of: {', '.join(valid_relationships)}",
                    errors={"relationship": ["Invalid relationship type"]}
                )
            family_doc.relationship = relationship
            changes_made = True
        
        if key_person is not None:
            new_key_person = int(key_person) if str(key_person).lower() in ['1', 'true', 'yes'] else 0
            if new_key_person != family_doc.key_person:
                family_doc.key_person = new_key_person
                changes_made = True

        if access is not None:
            new_access = int(access) if str(access).lower() in ['1', 'true', 'yes'] else 0
            if new_access != family_doc.access:
                family_doc.access = new_access
                changes_made = True
        
        # Save the document with validation disabled
        try:
            family_doc.flags.ignore_validate = True
            family_doc.save(ignore_permissions=True)
            frappe.db.commit()
        except Exception as save_error:
            return error_response(
                message=f"Failed to save family",
                code="SAVE_FAMILY_ERROR"
            )
        
        # Reload to get the final saved data from database
        family_doc.reload()
        
        return single_item_response(
            data={
                "name": family_doc.name,
                "student_id": family_doc.student_id,
                "guardian_id": family_doc.guardian_id,
                "relationship": family_doc.relationship,
                "key_person": family_doc.key_person,
                "access": family_doc.access
            },
            message="Family updated successfully"
        )
        
    except Exception as e:
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
        
        # Delete the document
        frappe.delete_doc("CRM Family", family_id)
        frappe.db.commit()
        
        return success_response(
            message="Family relationship deleted successfully"
        )
        
    except Exception as e:
        frappe.log_error(f"Error deleting family: {str(e)}")
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
        if search_term and str(search_term).strip():
            like = f"%{str(search_term).strip()}%"
            where_clauses.append("(LOWER(f.family_code) LIKE LOWER(%s) OR LOWER(s.student_name) LIKE LOWER(%s) OR LOWER(g.guardian_name) LIKE LOWER(%s))")
            params.extend([like, like, like])
        
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