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
    not_found_response, validation_error_response
)
import json


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
            return validation_error_response("school_year_id là bắt buộc")
        
        # Lấy campus từ context
        from erp.utils.campus_utils import get_current_campus_from_context
        campus_id = get_current_campus_from_context()
        
        # Kiểm tra xem doctype SIS Student Health Checkup đã tồn tại chưa
        checkup_table_exists = frappe.db.sql(
            "SHOW TABLES LIKE 'tabSIS Student Health Checkup'"
        )
        
        # Build query - lấy tất cả học sinh Regular class theo năm học
        campus_filter = "AND cs.campus_id = %(campus_id)s" if campus_id else ""
        
        if checkup_table_exists:
            # LEFT JOIN với SIS Student Health Checkup để biết đã có data chưa
            sql = f"""
                SELECT 
                    s.name as student_id,
                    s.student_name,
                    s.student_code,
                    s.gender,
                    c.name as class_id,
                    c.class_name,
                    shc.name as checkup_id
                FROM `tabSIS Class Student` cs
                INNER JOIN `tabCRM Student` s ON s.name = cs.student_id
                INNER JOIN `tabSIS Class` c ON c.name = cs.class_id
                LEFT JOIN `tabSIS Student Health Checkup` shc 
                    ON shc.student_id = cs.student_id 
                    AND shc.school_year_id = cs.school_year_id
                WHERE cs.school_year_id = %(school_year_id)s
                    AND c.class_type = 'Regular'
                    {campus_filter}
                ORDER BY c.class_name ASC, s.student_name ASC
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
                    c.class_name,
                    NULL as checkup_id
                FROM `tabSIS Class Student` cs
                INNER JOIN `tabCRM Student` s ON s.name = cs.student_id
                INNER JOIN `tabSIS Class` c ON c.name = cs.class_id
                WHERE cs.school_year_id = %(school_year_id)s
                    AND c.class_type = 'Regular'
                    {campus_filter}
                ORDER BY c.class_name ASC, s.student_name ASC
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
        
        if not student_id:
            return validation_error_response("student_id là bắt buộc")
        if not school_year_id:
            return validation_error_response("school_year_id là bắt buộc")
        
        # Lấy thông tin học sinh cơ bản
        student = frappe.get_doc("CRM Student", student_id)
        
        # Lấy thông tin lớp của học sinh trong năm học này
        class_info = frappe.db.sql("""
            SELECT c.name as class_id, c.class_name
            FROM `tabSIS Class Student` cs
            INNER JOIN `tabSIS Class` c ON c.name = cs.class_id
            WHERE cs.student_id = %(student_id)s
                AND cs.school_year_id = %(school_year_id)s
                AND c.class_type = 'Regular'
            LIMIT 1
        """, {"student_id": student_id, "school_year_id": school_year_id}, as_dict=True)
        
        class_name = class_info[0].class_name if class_info else None
        class_id = class_info[0].class_id if class_info else None
        
        # Lấy dữ liệu khám sức khoẻ nếu có (kiểm tra table tồn tại trước)
        checkup_data = None
        checkup_table_exists = frappe.db.sql(
            "SHOW TABLES LIKE 'tabSIS Student Health Checkup'"
        )
        if checkup_table_exists:
            checkup_data = frappe.db.get_value(
                "SIS Student Health Checkup",
                {"student_id": student_id, "school_year_id": school_year_id},
                ["*"],
                as_dict=True
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
            "checkup_data": checkup_data
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
        # Lấy từ params
        if not student_id:
            student_id = frappe.form_dict.get("student_id")
        if not school_year_id:
            school_year_id = frappe.form_dict.get("school_year_id")
        if not data:
            data = frappe.form_dict.get("data")
        
        if not student_id:
            return validation_error_response("student_id là bắt buộc")
        if not school_year_id:
            return validation_error_response("school_year_id là bắt buộc")
        
        # Parse data nếu là string
        if isinstance(data, str):
            data = json.loads(data)
        
        if not data:
            data = {}
        
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
        
        # Kiểm tra xem đã có record chưa
        existing = frappe.db.get_value(
            "SIS Student Health Checkup",
            {"student_id": student_id, "school_year_id": school_year_id},
            "name"
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
            "disease_condition", "health_classification"
        ]
        
        if existing:
            # Update existing record
            doc = frappe.get_doc("SIS Student Health Checkup", existing)
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
                "checkup_date": data.get("checkup_date") or today()
            }
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
            return validation_error_response("school_year_id là bắt buộc")
        
        # Lấy campus từ context
        from erp.utils.campus_utils import get_current_campus_from_context
        campus_id = get_current_campus_from_context()
        
        campus_filter = "AND cs.campus_id = %(campus_id)s" if campus_id else ""
        
        # Kiểm tra xem doctype đã tồn tại chưa
        checkup_table_exists = frappe.db.sql(
            "SHOW TABLES LIKE 'tabSIS Student Health Checkup'"
        )
        
        # Query tất cả học sinh kèm data khám (nếu có)
        if checkup_table_exists:
            sql = f"""
                SELECT 
                    s.student_code,
                    s.student_name,
                    s.gender,
                    c.class_name,
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
                    shc.health_classification
                FROM `tabSIS Class Student` cs
                INNER JOIN `tabCRM Student` s ON s.name = cs.student_id
                INNER JOIN `tabSIS Class` c ON c.name = cs.class_id
                LEFT JOIN `tabSIS Student Health Checkup` shc 
                    ON shc.student_id = cs.student_id 
                    AND shc.school_year_id = cs.school_year_id
                WHERE cs.school_year_id = %(school_year_id)s
                    AND c.class_type = 'Regular'
                    {campus_filter}
                ORDER BY c.class_name ASC, s.student_name ASC
            """
        else:
            # Nếu chưa có table health checkup, chỉ lấy danh sách học sinh với các cột NULL
            sql = f"""
                SELECT 
                    s.student_code,
                    s.student_name,
                    s.gender,
                    c.class_name,
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
                    NULL as health_classification
                FROM `tabSIS Class Student` cs
                INNER JOIN `tabCRM Student` s ON s.name = cs.student_id
                INNER JOIN `tabSIS Class` c ON c.name = cs.class_id
                WHERE cs.school_year_id = %(school_year_id)s
                    AND c.class_type = 'Regular'
                    {campus_filter}
                ORDER BY c.class_name ASC, s.student_name ASC
            """
        
        params = {"school_year_id": school_year_id}
        if campus_id:
            params["campus_id"] = campus_id
        
        data = frappe.db.sql(sql, params, as_dict=True)
        
        return success_response(
            data=data,
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
        # Lấy từ params
        if not school_year_id:
            school_year_id = frappe.form_dict.get("school_year_id")
        if not data:
            data = frappe.form_dict.get("data")
        
        if not school_year_id:
            return validation_error_response("school_year_id là bắt buộc")
        if not data:
            return validation_error_response("data là bắt buộc")
        
        # Parse data nếu là string
        if isinstance(data, str):
            data = json.loads(data)
        
        if not isinstance(data, list):
            return validation_error_response("data phải là danh sách")
        
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
            "disease_condition", "health_classification"
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
                
                # Kiểm tra xem đã có record chưa
                existing = frappe.db.get_value(
                    "SIS Student Health Checkup",
                    {"student_id": student_id, "school_year_id": school_year_id},
                    "name"
                )
                
                if existing:
                    # Update
                    doc = frappe.get_doc("SIS Student Health Checkup", existing)
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
                        "checkup_date": today()
                    }
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
