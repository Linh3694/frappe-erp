# Copyright (c) 2025, Wellspring International School and contributors
# For license information, please see license.txt

"""
Health Checkup API - Khám sức khoẻ định kỳ
API endpoints cho việc quản lý và xem kết quả khám sức khoẻ định kỳ của học sinh.
"""

import frappe
from frappe import _
from frappe.utils import today
from erp.utils.api_response import (
    success_response, error_response, paginated_response,
    not_found_response
)
import json


def _get_request_data():
    """Lấy request data từ nhiều nguồn khác nhau (query params, form_dict, JSON body)"""
    data = {}
    
    # 1. Lấy từ URL query params (GET request)
    if hasattr(frappe, 'request') and hasattr(frappe.request, 'args') and frappe.request.args:
        data.update(dict(frappe.request.args))
    
    # 2. Lấy từ form_dict (query params và form data)
    if frappe.local.form_dict:
        data.update(dict(frappe.local.form_dict))
    
    # 3. Merge với JSON body nếu có (POST request)
    if hasattr(frappe.request, 'is_json') and frappe.request.is_json:
        json_data = frappe.request.json or {}
        data.update(json_data)
    else:
        try:
            if hasattr(frappe.request, 'data') and frappe.request.data:
                raw = frappe.request.data
                body = raw.decode('utf-8') if isinstance(raw, (bytes, bytearray)) else raw
                if body and body.strip():
                    json_data = json.loads(body)
                    if isinstance(json_data, dict):
                        data.update(json_data)
        except (json.JSONDecodeError, ValueError):
            pass
    
    return data


def _normalize_checkup_phase(phase):
    """Chuẩn hoá đợt khám: beginning | end. None nếu không hợp lệ."""
    if phase is None or str(phase).strip() == "":
        return "beginning"
    p = str(phase).strip().lower()
    if p in ("beginning", "end"):
        return p
    return None


def _session_campus_key():
    """Mã cơ sở lưu kèm phiên khám (rỗng khi không có campus trong context)."""
    from erp.utils.campus_utils import get_current_campus_from_context
    campus_id = get_current_campus_from_context()
    return campus_id or ""


def _health_checkup_session_table_exists():
    return bool(
        frappe.db.sql("SHOW TABLES LIKE 'tabSIS Health Checkup Session'")
    )


def _sis_health_checkup_has_approval_status_column():
    """
    Có cột approval_status trên bảng khám SK định kỳ hay không.
    Phải dùng tên DocType "SIS Student Health Checkup" (không prefix tab) — has_column tự nối tab.
    Bọc try/except: bảng/cột chưa migrate thì trả False, không làm sập API.
    """
    try:
        return frappe.db.has_column("SIS Student Health Checkup", "approval_status")
    except Exception:
        return False


@frappe.whitelist(allow_guest=False)
def get_health_checkup_session_meta(school_year_id=None, checkup_phase=None):
    """
    Lấy meta phiên khám theo năm học + đợt (vd: Đơn vị khám), theo campus context.
    """
    try:
        data = _get_request_data()
        if not school_year_id:
            school_year_id = data.get("school_year_id") or frappe.form_dict.get(
                "school_year_id"
            ) or frappe.request.args.get("school_year_id")
        if checkup_phase is None:
            checkup_phase = data.get("checkup_phase") or frappe.form_dict.get(
                "checkup_phase"
            ) or frappe.request.args.get("checkup_phase")
        checkup_phase = _normalize_checkup_phase(checkup_phase)
        if not school_year_id:
            return error_response(
                message="school_year_id là bắt buộc", code="VALIDATION_ERROR"
            )
        if checkup_phase is None:
            return error_response(
                message="checkup_phase phải là beginning hoặc end",
                code="VALIDATION_ERROR",
            )
        if not _health_checkup_session_table_exists():
            return success_response(
                data={"exam_unit": ""},
                message="Chưa có bảng phiên khám (migrate để lưu Đơn vị khám)",
            )
        campus_key = _session_campus_key()
        rows = frappe.get_all(
            "SIS Health Checkup Session",
            filters={
                "school_year_id": school_year_id,
                "checkup_phase": checkup_phase,
                "campus_id": campus_key,
            },
            fields=["exam_unit"],
            limit=1,
        )
        exam_unit = (rows[0].get("exam_unit") or "") if rows else ""
        return success_response(
            data={"exam_unit": exam_unit},
            message="Lấy meta phiên khám thành công",
        )
    except Exception as e:
        import traceback
        frappe.log_error(
            f"get_health_checkup_session_meta: {str(e)}\n{traceback.format_exc()}"
        )
        return error_response(
            message=f"Có lỗi khi lấy meta phiên khám: {str(e)}",
            code="SESSION_META_ERROR",
        )


@frappe.whitelist(allow_guest=False)
def save_health_checkup_session_meta(
    school_year_id=None, checkup_phase=None, exam_unit=None
):
    """
    Lưu Đơn vị khám (và meta tương lai) cho năm học + đợt + campus context.
    """
    try:
        data = _get_request_data()
        if not school_year_id:
            school_year_id = data.get("school_year_id")
        if checkup_phase is None:
            checkup_phase = data.get("checkup_phase")
        if exam_unit is None:
            exam_unit = data.get("exam_unit")
        checkup_phase = _normalize_checkup_phase(checkup_phase)
        if not school_year_id:
            return error_response(
                message="school_year_id là bắt buộc", code="VALIDATION_ERROR"
            )
        if checkup_phase is None:
            return error_response(
                message="checkup_phase phải là beginning hoặc end",
                code="VALIDATION_ERROR",
            )
        exam_unit = (exam_unit or "").strip() if isinstance(exam_unit, str) else ""
        if not _health_checkup_session_table_exists():
            return error_response(
                message="Chưa có DocType phiên khám trên server (cần migrate)",
                code="SESSION_TABLE_MISSING",
            )
        campus_key = _session_campus_key()
        rows = frappe.get_all(
            "SIS Health Checkup Session",
            filters={
                "school_year_id": school_year_id,
                "checkup_phase": checkup_phase,
                "campus_id": campus_key,
            },
            pluck="name",
            limit=1,
        )
        if rows:
            doc = frappe.get_doc("SIS Health Checkup Session", rows[0])
            doc.exam_unit = exam_unit
            doc.save(ignore_permissions=True)
        else:
            doc = frappe.get_doc(
                {
                    "doctype": "SIS Health Checkup Session",
                    "school_year_id": school_year_id,
                    "checkup_phase": checkup_phase,
                    "campus_id": campus_key,
                    "exam_unit": exam_unit,
                }
            )
            doc.insert(ignore_permissions=True)
        frappe.db.commit()
        return success_response(
            data={"exam_unit": exam_unit},
            message="Lưu Đơn vị khám thành công",
        )
    except Exception as e:
        import traceback
        frappe.log_error(
            f"save_health_checkup_session_meta: {str(e)}\n{traceback.format_exc()}"
        )
        return error_response(
            message=f"Có lỗi khi lưu meta phiên khám: {str(e)}",
            code="SESSION_META_SAVE_ERROR",
        )


@frappe.whitelist(allow_guest=False)
def get_students_health_checkup(school_year_id=None):
    """
    Lấy danh sách tất cả học sinh lớp Regular theo năm học,
    kèm flag đã có dữ liệu khám sức khoẻ hay chưa.
    
    Params:
        - school_year_id: ID năm học (required)
    
    Returns:
        Danh sách học sinh với thông tin: name, student_name, student_code, 
        gender, class_name, class_id, checkup_id (null nếu chưa có data)
    """
    try:
        # Lấy từ params
        if not school_year_id:
            school_year_id = frappe.form_dict.get("school_year_id") or frappe.request.args.get("school_year_id")
        
        if not school_year_id:
            return error_response(message="school_year_id là bắt buộc", code="VALIDATION_ERROR")
        
        # Lấy campus từ context
        from erp.utils.campus_utils import get_current_campus_from_context
        campus_id = get_current_campus_from_context()
        
        # Kiểm tra xem doctype SIS Student Health Checkup đã tồn tại chưa
        checkup_table_exists = frappe.db.sql(
            "SHOW TABLES LIKE 'tabSIS Student Health Checkup'"
        )
        
        # Build query - lấy tất cả học sinh Regular class theo năm học
        campus_filter = "AND cs.campus_id = %(campus_id)s" if campus_id else ""
        
        approval_cols = ""
        if checkup_table_exists and _sis_health_checkup_has_approval_status_column():
            approval_cols = """
                    , shc_b.approval_status as checkup_beginning_status
                    , shc_e.approval_status as checkup_end_status
            """
        returned_cols = ""
        rejection_cols = ""
        if checkup_table_exists:
            try:
                if frappe.db.has_column(
                    "SIS Student Health Checkup", "returned_from_level"
                ):
                    returned_cols = """
                    , shc_b.returned_from_level as checkup_beginning_returned_from_level
                    , shc_e.returned_from_level as checkup_end_returned_from_level
                    """
            except Exception:
                returned_cols = ""
            try:
                if frappe.db.has_column(
                    "SIS Student Health Checkup", "last_rejection_comment"
                ):
                    rejection_cols = """
                    , shc_b.last_rejection_comment as checkup_beginning_last_rejection_comment
                    , shc_e.last_rejection_comment as checkup_end_last_rejection_comment
                    """
            except Exception:
                rejection_cols = ""

        if checkup_table_exists:
            # Hai LEFT JOIN theo đợt: đầu năm / cuối năm
            sql = f"""
                SELECT 
                    s.name as student_id,
                    s.student_name,
                    s.student_code,
                    s.gender,
                    c.name as class_id,
                    c.title as class_name,
                    shc_b.name as checkup_beginning_id,
                    shc_e.name as checkup_end_id
                    {approval_cols}
                    {returned_cols}
                    {rejection_cols}
                FROM `tabSIS Class Student` cs
                INNER JOIN `tabCRM Student` s ON s.name = cs.student_id
                INNER JOIN `tabSIS Class` c ON c.name = cs.class_id
                LEFT JOIN `tabSIS Student Health Checkup` shc_b 
                    ON shc_b.student_id = cs.student_id 
                    AND shc_b.school_year_id = cs.school_year_id
                    AND shc_b.checkup_phase = 'beginning'
                LEFT JOIN `tabSIS Student Health Checkup` shc_e 
                    ON shc_e.student_id = cs.student_id 
                    AND shc_e.school_year_id = cs.school_year_id
                    AND shc_e.checkup_phase = 'end'
                WHERE cs.school_year_id = %(school_year_id)s
                    AND c.class_type = 'regular'
                    {campus_filter}
                ORDER BY c.title ASC, s.student_name ASC
            """
        else:
            # Nếu chưa có table health checkup, chỉ lấy danh sách học sinh
            sql = f"""
                SELECT 
                    s.name as student_id,
                    s.student_name,
                    s.student_code,
                    s.gender,
                    c.name as class_id,
                    c.title as class_name,
                    NULL as checkup_beginning_id,
                    NULL as checkup_end_id
                FROM `tabSIS Class Student` cs
                INNER JOIN `tabCRM Student` s ON s.name = cs.student_id
                INNER JOIN `tabSIS Class` c ON c.name = cs.class_id
                WHERE cs.school_year_id = %(school_year_id)s
                    AND c.class_type = 'regular'
                    {campus_filter}
                ORDER BY c.title ASC, s.student_name ASC
            """
        
        params = {"school_year_id": school_year_id}
        if campus_id:
            params["campus_id"] = campus_id
        
        students = frappe.db.sql(sql, params, as_dict=True)
        
        return success_response(
            data=students,
            message=f"Lấy danh sách {len(students)} học sinh thành công"
        )
        
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        frappe.log_error(f"Error getting students health checkup: {str(e)}\n{error_trace}")
        return error_response(
            message=f"Có lỗi xảy ra khi lấy danh sách học sinh: {str(e)}",
            code="FETCH_STUDENTS_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def get_student_health_checkup(student_id=None, school_year_id=None):
    """
    Lấy chi tiết kết quả khám sức khoẻ của 1 học sinh theo năm học.
    
    Params:
        - student_id: ID học sinh (required)
        - school_year_id: ID năm học (required)
    
    Returns:
        Thông tin học sinh + dữ liệu khám sức khoẻ (null nếu chưa có)
    """
    try:
        # Lấy từ params
        if not student_id:
            student_id = frappe.form_dict.get("student_id") or frappe.request.args.get("student_id")
        if not school_year_id:
            school_year_id = frappe.form_dict.get("school_year_id") or frappe.request.args.get("school_year_id")
        checkup_phase = frappe.form_dict.get("checkup_phase") or frappe.request.args.get("checkup_phase")
        checkup_phase = _normalize_checkup_phase(checkup_phase)
        if checkup_phase is None:
            return error_response(message="checkup_phase phải là beginning hoặc end", code="VALIDATION_ERROR")
        
        if not student_id:
            return error_response(message="student_id là bắt buộc", code="VALIDATION_ERROR")
        if not school_year_id:
            return error_response(message="school_year_id là bắt buộc", code="VALIDATION_ERROR")
        
        # Lấy thông tin học sinh cơ bản
        student = frappe.get_doc("CRM Student", student_id)
        
        # Lấy thông tin lớp của học sinh trong năm học này
        class_info = frappe.db.sql("""
            SELECT c.name as class_id, c.title as class_name
            FROM `tabSIS Class Student` cs
            INNER JOIN `tabSIS Class` c ON c.name = cs.class_id
            WHERE cs.student_id = %(student_id)s
                AND cs.school_year_id = %(school_year_id)s
                AND c.class_type = 'regular'
            LIMIT 1
        """, {"student_id": student_id, "school_year_id": school_year_id}, as_dict=True)
        
        class_name = class_info[0].class_name if class_info else None
        class_id = class_info[0].class_id if class_info else None
        
        # Lấy dữ liệu khám sức khoẻ nếu có (kiểm tra table tồn tại trước)
        checkup_data = None
        checkup_table_exists = frappe.db.sql(
            "SHOW TABLES LIKE 'tabSIS Student Health Checkup'"
        )
        reference_checkup_data = None
        if checkup_table_exists:
            checkup_data = frappe.db.get_value(
                "SIS Student Health Checkup",
                {
                    "student_id": student_id,
                    "school_year_id": school_year_id,
                    "checkup_phase": checkup_phase,
                },
                ["*"],
                as_dict=True,
            )
            # Đợt cuối năm: trả thêm dữ liệu đầu năm để đối chiếu
            if checkup_phase == "end":
                reference_checkup_data = frappe.db.get_value(
                    "SIS Student Health Checkup",
                    {
                        "student_id": student_id,
                        "school_year_id": school_year_id,
                        "checkup_phase": "beginning",
                    },
                    ["*"],
                    as_dict=True,
                )
        
        # Build response
        response_data = {
            "student_id": student.name,
            "student_name": student.student_name,
            "student_code": student.student_code,
            "gender": student.gender,
            "class_id": class_id,
            "class_name": class_name,
            "school_year_id": school_year_id,
            "checkup_phase": checkup_phase,
            "checkup_data": checkup_data,
            "reference_checkup_data": reference_checkup_data,
        }
        
        return success_response(
            data=response_data,
            message="Lấy thông tin khám sức khoẻ thành công"
        )
        
    except frappe.DoesNotExistError:
        return not_found_response("Không tìm thấy học sinh")
    except Exception as e:
        frappe.log_error(f"Error getting student health checkup: {str(e)}")
        return error_response(
            message="Có lỗi xảy ra khi lấy thông tin khám sức khoẻ",
            code="FETCH_CHECKUP_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def save_student_health_checkup(student_id=None, school_year_id=None, data=None):
    """
    Tạo mới hoặc cập nhật kết quả khám sức khoẻ của học sinh (upsert).
    
    Params:
        - student_id: ID học sinh (required)
        - school_year_id: ID năm học (required)
        - data: Object chứa các field khám sức khoẻ
    
    Returns:
        Dữ liệu khám sức khoẻ đã lưu
    """
    try:
        # Lấy dữ liệu từ request (hỗ trợ cả query params, form_dict và JSON body)
        request_data = _get_request_data()
        
        # Ưu tiên params truyền trực tiếp, sau đó từ request_data
        if not student_id:
            student_id = request_data.get("student_id")
        if not school_year_id:
            school_year_id = request_data.get("school_year_id")
        if not data:
            data = request_data.get("data")
        
        # Log để debug
        frappe.logger().info(f"save_student_health_checkup called with: student_id={student_id}, school_year_id={school_year_id}, data_type={type(data)}, request_data_keys={list(request_data.keys())}")
        
        if not student_id:
            return error_response(message="student_id là bắt buộc", code="VALIDATION_ERROR")
        if not school_year_id:
            return error_response(message="school_year_id là bắt buộc", code="VALIDATION_ERROR")
        
        # Parse data nếu là string
        if isinstance(data, str):
            data = json.loads(data)
        
        if not data:
            data = {}
        
        # Đợt khám: body hoặc top-level request
        checkup_phase = request_data.get("checkup_phase")
        if isinstance(data, dict) and data.get("checkup_phase") is not None:
            checkup_phase = data.get("checkup_phase")
        checkup_phase = _normalize_checkup_phase(checkup_phase)
        if checkup_phase is None:
            return error_response(message="checkup_phase phải là beginning hoặc end", code="VALIDATION_ERROR")
        if isinstance(data, dict) and "checkup_phase" in data:
            data = {k: v for k, v in data.items() if k != "checkup_phase"}
        
        # Lấy campus từ context
        from erp.utils.campus_utils import get_current_campus_from_context
        campus_id = get_current_campus_from_context()
        
        # Kiểm tra xem doctype đã tồn tại chưa
        checkup_table_exists = frappe.db.sql(
            "SHOW TABLES LIKE 'tabSIS Student Health Checkup'"
        )
        if not checkup_table_exists:
            return error_response(
                message="Vui lòng chạy 'bench migrate' để tạo bảng dữ liệu khám sức khoẻ",
                code="TABLE_NOT_EXISTS"
            )

        # Phê duyệt: chỉ SIS Medical (hoặc System Manager) được nhập; chỉ sửa khi draft
        roles = frappe.get_roles()
        has_medical = "SIS Medical" in roles
        is_system = "System Manager" in roles
        if _sis_health_checkup_has_approval_status_column():
            if not has_medical and not is_system:
                return error_response(
                    message="Chỉ vai trò SIS Medical được nhập phiếu khám định kỳ",
                    code="FORBIDDEN",
                )
        
        # Kiểm tra xem đã có record chưa (theo đợt)
        existing = frappe.db.get_value(
            "SIS Student Health Checkup",
            {
                "student_id": student_id,
                "school_year_id": school_year_id,
                "checkup_phase": checkup_phase,
            },
            "name",
        )
        
        # Các fields được phép update
        allowed_fields = [
            "checkup_date",
            # Body metrics
            "height", "weight",
            "water_content", "water_range",
            "protein", "protein_range",
            "body_fat_mass", "body_fat_range",
            "mineral", "mineral_range",
            # Body targets
            "target_weight", "weight_control", "muscle_control", "fat_control",
            # Blood pressure
            "systolic_pressure", "diastolic_pressure", "heart_rate",
            # Eye exam
            "left_eye_no_glasses", "right_eye_no_glasses",
            "left_eye_with_glasses", "right_eye_with_glasses",
            "other_eye_disease", "refractive_error",
            # Specialist exam
            "ent_disease", "dental_disease", "musculoskeletal_disease",
            # Internal medicine
            "circulation", "respiratory", "digestive", "renal_urinary", "other_clinical",
            # Conclusion
            "bmi", "pbf", "body_score",
            "nutrition_conclusion", "nutrition_classification",
            "disease_condition", "health_classification",
            # Notes
            "doctor_recommendation", "reference_notes"
        ]
        
        if existing:
            # Update existing record
            doc = frappe.get_doc("SIS Student Health Checkup", existing)
            if (
                _sis_health_checkup_has_approval_status_column()
                and getattr(doc, "approval_status", None)
                and doc.approval_status != "draft"
                and not is_system
            ):
                return error_response(
                    message="Phiếu đang chờ phê duyệt hoặc đã công bố — không thể sửa",
                    code="READONLY_CHECKUP",
                )
            for field in allowed_fields:
                if field in data:
                    setattr(doc, field, data[field])
            doc.save()
        else:
            # Create new record
            doc_data = {
                "doctype": "SIS Student Health Checkup",
                "student_id": student_id,
                "school_year_id": school_year_id,
                "campus_id": campus_id,
                "checkup_phase": checkup_phase,
                "checkup_date": data.get("checkup_date") or today()
            }
            if _sis_health_checkup_has_approval_status_column():
                doc_data["approval_status"] = "draft"
            for field in allowed_fields:
                if field in data and data[field] is not None:
                    doc_data[field] = data[field]
            
            doc = frappe.get_doc(doc_data)
            doc.insert()
        
        frappe.db.commit()
        
        return success_response(
            data=doc.as_dict(),
            message="Lưu kết quả khám sức khoẻ thành công"
        )
        
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(f"Error saving student health checkup: {str(e)}")
        return error_response(
            message=f"Có lỗi xảy ra khi lưu kết quả khám sức khoẻ: {str(e)}",
            code="SAVE_CHECKUP_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def export_health_checkup(school_year_id=None):
    """
    Export toàn bộ dữ liệu khám sức khoẻ định kỳ theo năm học ra Excel.
    
    Params:
        - school_year_id: ID năm học (required)
    
    Returns:
        Danh sách dữ liệu (frontend sẽ tạo Excel từ đây)
    """
    try:
        # Lấy từ params
        if not school_year_id:
            school_year_id = frappe.form_dict.get("school_year_id") or frappe.request.args.get("school_year_id")
        
        if not school_year_id:
            return error_response(message="school_year_id là bắt buộc", code="VALIDATION_ERROR")
        
        checkup_phase = frappe.form_dict.get("checkup_phase") or frappe.request.args.get("checkup_phase")
        checkup_phase = _normalize_checkup_phase(checkup_phase)
        if checkup_phase is None:
            return error_response(message="checkup_phase phải là beginning hoặc end", code="VALIDATION_ERROR")
        
        # Lấy campus từ context
        from erp.utils.campus_utils import get_current_campus_from_context
        campus_id = get_current_campus_from_context()
        
        campus_filter = "AND cs.campus_id = %(campus_id)s" if campus_id else ""
        
        # Kiểm tra xem doctype đã tồn tại chưa
        checkup_table_exists = frappe.db.sql(
            "SHOW TABLES LIKE 'tabSIS Student Health Checkup'"
        )
        
        # Query tất cả học sinh kèm data khám (nếu có) — theo đợt khám
        if checkup_table_exists:
            sql = f"""
                SELECT 
                    s.student_code,
                    s.student_name,
                    s.gender,
                    c.title as class_name,
                    shc.height,
                    shc.weight,
                    shc.water_content,
                    shc.water_range,
                    shc.protein,
                    shc.protein_range,
                    shc.body_fat_mass,
                    shc.body_fat_range,
                    shc.mineral,
                    shc.mineral_range,
                    shc.target_weight,
                    shc.weight_control,
                    shc.muscle_control,
                    shc.fat_control,
                    shc.systolic_pressure,
                    shc.diastolic_pressure,
                    shc.heart_rate,
                    shc.left_eye_no_glasses,
                    shc.right_eye_no_glasses,
                    shc.left_eye_with_glasses,
                    shc.right_eye_with_glasses,
                    shc.other_eye_disease,
                    shc.refractive_error,
                    shc.ent_disease,
                    shc.dental_disease,
                    shc.musculoskeletal_disease,
                    shc.circulation,
                    shc.respiratory,
                    shc.digestive,
                    shc.renal_urinary,
                    shc.other_clinical,
                    shc.bmi,
                    shc.pbf,
                    shc.body_score,
                    shc.nutrition_conclusion,
                    shc.nutrition_classification,
                    shc.disease_condition,
                    shc.health_classification,
                    shc.doctor_recommendation,
                    shc.reference_notes
                FROM `tabSIS Class Student` cs
                INNER JOIN `tabCRM Student` s ON s.name = cs.student_id
                INNER JOIN `tabSIS Class` c ON c.name = cs.class_id
                LEFT JOIN `tabSIS Student Health Checkup` shc 
                    ON shc.student_id = cs.student_id 
                    AND shc.school_year_id = cs.school_year_id
                    AND shc.checkup_phase = %(checkup_phase)s
                WHERE cs.school_year_id = %(school_year_id)s
                    AND c.class_type = 'regular'
                    {campus_filter}
                ORDER BY c.title ASC, s.student_name ASC
            """
        else:
            # Nếu chưa có table health checkup, chỉ lấy danh sách học sinh với các cột NULL
            sql = f"""
                SELECT 
                    s.student_code,
                    s.student_name,
                    s.gender,
                    c.title as class_name,
                    NULL as height,
                    NULL as weight,
                    NULL as water_content,
                    NULL as water_range,
                    NULL as protein,
                    NULL as protein_range,
                    NULL as body_fat_mass,
                    NULL as body_fat_range,
                    NULL as mineral,
                    NULL as mineral_range,
                    NULL as target_weight,
                    NULL as weight_control,
                    NULL as muscle_control,
                    NULL as fat_control,
                    NULL as systolic_pressure,
                    NULL as diastolic_pressure,
                    NULL as heart_rate,
                    NULL as left_eye_no_glasses,
                    NULL as right_eye_no_glasses,
                    NULL as left_eye_with_glasses,
                    NULL as right_eye_with_glasses,
                    NULL as other_eye_disease,
                    NULL as refractive_error,
                    NULL as ent_disease,
                    NULL as dental_disease,
                    NULL as musculoskeletal_disease,
                    NULL as circulation,
                    NULL as respiratory,
                    NULL as digestive,
                    NULL as renal_urinary,
                    NULL as other_clinical,
                    NULL as bmi,
                    NULL as pbf,
                    NULL as body_score,
                    NULL as nutrition_conclusion,
                    NULL as nutrition_classification,
                    NULL as disease_condition,
                    NULL as health_classification,
                    NULL as doctor_recommendation,
                    NULL as reference_notes
                FROM `tabSIS Class Student` cs
                INNER JOIN `tabCRM Student` s ON s.name = cs.student_id
                INNER JOIN `tabSIS Class` c ON c.name = cs.class_id
                WHERE cs.school_year_id = %(school_year_id)s
                    AND c.class_type = 'regular'
                    {campus_filter}
                ORDER BY c.title ASC, s.student_name ASC
            """
        
        params = {"school_year_id": school_year_id, "checkup_phase": checkup_phase}
        if campus_id:
            params["campus_id"] = campus_id
        
        data = frappe.db.sql(sql, params, as_dict=True)
        
        # Lấy tên năm học để frontend tạo tên file
        school_year_name = frappe.db.get_value("SIS School Year", school_year_id, "title_vn") or school_year_id
        
        return success_response(
            data={
                "students": data,
                "school_year_name": school_year_name,
                "checkup_phase": checkup_phase,
            },
            message=f"Xuất dữ liệu {len(data)} học sinh thành công"
        )
        
    except Exception as e:
        frappe.log_error(f"Error exporting health checkup: {str(e)}")
        return error_response(
            message="Có lỗi xảy ra khi xuất dữ liệu",
            code="EXPORT_CHECKUP_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def import_health_checkup(school_year_id=None, data=None):
    """
    Import dữ liệu khám sức khoẻ từ Excel (đã được parse ở frontend).
    Mapping dựa trên student_code.
    
    Params:
        - school_year_id: ID năm học (required)
        - data: Array of objects với student_code và các fields khám
    
    Returns:
        Kết quả import: success_count, error_count, errors
    """
    try:
        # Lấy dữ liệu từ request (hỗ trợ cả query params, form_dict và JSON body)
        request_data = _get_request_data()
        
        # Ưu tiên params truyền trực tiếp, sau đó từ request_data
        if not school_year_id:
            school_year_id = request_data.get("school_year_id")
        if not data:
            data = request_data.get("data")
        
        if not school_year_id:
            return error_response(message="school_year_id là bắt buộc", code="VALIDATION_ERROR")
        if not data:
            return error_response(message="data là bắt buộc", code="VALIDATION_ERROR")
        
        # Parse data nếu là string
        if isinstance(data, str):
            data = json.loads(data)
        
        if not isinstance(data, list):
            return error_response(message="data phải là danh sách", code="VALIDATION_ERROR")
        
        checkup_phase = _normalize_checkup_phase(request_data.get("checkup_phase"))
        if checkup_phase is None:
            return error_response(message="checkup_phase phải là beginning hoặc end", code="VALIDATION_ERROR")
        
        # Lấy campus từ context
        from erp.utils.campus_utils import get_current_campus_from_context
        campus_id = get_current_campus_from_context()

        _ir = frappe.get_roles()
        if "SIS Medical" not in _ir and "System Manager" not in _ir:
            return error_response(
                message="Chỉ SIS Medical được import phiếu khám định kỳ",
                code="FORBIDDEN",
            )
        
        # Kiểm tra xem doctype đã tồn tại chưa
        checkup_table_exists = frappe.db.sql(
            "SHOW TABLES LIKE 'tabSIS Student Health Checkup'"
        )
        if not checkup_table_exists:
            return error_response(
                message="Vui lòng chạy 'bench migrate' để tạo bảng dữ liệu khám sức khoẻ",
                code="TABLE_NOT_EXISTS"
            )
        
        # Các fields được phép import
        allowed_fields = [
            "height", "weight",
            "water_content", "water_range",
            "protein", "protein_range",
            "body_fat_mass", "body_fat_range",
            "mineral", "mineral_range",
            "target_weight", "weight_control", "muscle_control", "fat_control",
            "systolic_pressure", "diastolic_pressure", "heart_rate",
            "left_eye_no_glasses", "right_eye_no_glasses",
            "left_eye_with_glasses", "right_eye_with_glasses",
            "other_eye_disease", "refractive_error",
            "ent_disease", "dental_disease", "musculoskeletal_disease",
            "circulation", "respiratory", "digestive", "renal_urinary", "other_clinical",
            "bmi", "pbf", "body_score",
            "nutrition_conclusion", "nutrition_classification",
            "disease_condition", "health_classification",
            "doctor_recommendation", "reference_notes"
        ]
        
        success_count = 0
        error_count = 0
        errors = []
        
        for idx, row in enumerate(data):
            try:
                student_code = row.get("student_code")
                if not student_code:
                    errors.append({"row": idx + 1, "error": "Thiếu mã học sinh"})
                    error_count += 1
                    continue
                
                # Tìm student_id từ student_code
                student_id = frappe.db.get_value("CRM Student", {"student_code": student_code}, "name")
                if not student_id:
                    errors.append({"row": idx + 1, "error": f"Không tìm thấy học sinh với mã {student_code}"})
                    error_count += 1
                    continue
                
                # Kiểm tra học sinh có trong năm học này không
                in_school_year = frappe.db.exists(
                    "SIS Class Student",
                    {"student_id": student_id, "school_year_id": school_year_id}
                )
                if not in_school_year:
                    errors.append({"row": idx + 1, "error": f"Học sinh {student_code} không thuộc năm học này"})
                    error_count += 1
                    continue
                
                # Kiểm tra xem đã có record chưa (theo đợt)
                existing = frappe.db.get_value(
                    "SIS Student Health Checkup",
                    {
                        "student_id": student_id,
                        "school_year_id": school_year_id,
                        "checkup_phase": checkup_phase,
                    },
                    "name",
                )
                
                if existing:
                    # Update
                    doc = frappe.get_doc("SIS Student Health Checkup", existing)
                    if (
                        _sis_health_checkup_has_approval_status_column()
                        and getattr(doc, "approval_status", None)
                        and doc.approval_status != "draft"
                        and "System Manager" not in frappe.get_roles()
                    ):
                        errors.append({"row": idx + 1, "error": "Phiếu không ở trạng thái nháp — bỏ qua"})
                        error_count += 1
                        continue
                    for field in allowed_fields:
                        if field in row and row[field] is not None and row[field] != "":
                            setattr(doc, field, row[field])
                    doc.save()
                else:
                    # Create
                    doc_data = {
                        "doctype": "SIS Student Health Checkup",
                        "student_id": student_id,
                        "school_year_id": school_year_id,
                        "campus_id": campus_id,
                        "checkup_phase": checkup_phase,
                        "checkup_date": today()
                    }
                    if _sis_health_checkup_has_approval_status_column():
                        doc_data["approval_status"] = "draft"
                    for field in allowed_fields:
                        if field in row and row[field] is not None and row[field] != "":
                            doc_data[field] = row[field]
                    
                    doc = frappe.get_doc(doc_data)
                    doc.insert()
                
                success_count += 1
                
            except Exception as e:
                errors.append({"row": idx + 1, "error": str(e)})
                error_count += 1
        
        frappe.db.commit()
        
        return success_response(
            data={
                "success_count": success_count,
                "error_count": error_count,
                "errors": errors[:20]  # Chỉ trả về 20 lỗi đầu tiên
            },
            message=f"Import hoàn tất: {success_count} thành công, {error_count} lỗi"
        )
        
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(f"Error importing health checkup: {str(e)}")
        return error_response(
            message=f"Có lỗi xảy ra khi import: {str(e)}",
            code="IMPORT_CHECKUP_ERROR"
        )


# Workflow phê duyệt (re-export từ module riêng)
from erp.api.erp_sis.health_checkup_workflow import (  # noqa: E402
    submit_student_health_checkup,
    submit_student_health_checkup_bulk,
    approve_health_checkup_l2,
    reject_health_checkup_l2,
    approve_health_checkup_l3,
    reject_health_checkup_l3,
    revoke_health_checkup_l3,
    get_health_checkup_approval_queue_l2,
    get_class_periodic_health_checkups,
)

# Ảnh phiếu khám gửi Parent Portal
from erp.api.erp_sis.health_checkup_images import (  # noqa: E402
    upload_health_checkup_images,
    delete_health_checkup_images,
    get_health_checkup_images,
)
