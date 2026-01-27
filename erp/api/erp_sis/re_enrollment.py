"""
Admin Re-enrollment API
Handles re-enrollment management for admin/admission staff

API endpoints cho admin quản lý cấu hình và đơn tái ghi danh.
"""

import frappe
from frappe import _
from frappe.utils import nowdate, getdate, now
import json
import os
import requests
import uuid
from erp.utils.api_response import (
    validation_error_response, 
    list_response, 
    error_response, 
    success_response, 
    single_item_response,
    not_found_response
)

# URL pdf-service (có thể cấu hình trong site_config.json)
PDF_SERVICE_URL = frappe.conf.get("pdf_service_url", "http://172.16.20.113:5020")


def _check_admin_permission():
    """Kiểm tra quyền admin"""
    user_roles = frappe.get_roles(frappe.session.user)
    # SIS Sales có full quyền trên module Re-enrollment
    allowed_roles = ['System Manager', 'SIS BOD', 'SIS Sales']
    
    if not any(role in user_roles for role in allowed_roles):
        return False
    return True


def _resolve_campus_id(campus_id):
    """
    Chuyển đổi campus_id từ format frontend (campus-1) sang format database (CAMPUS-00001)
    """
    if not campus_id:
        return None
    
    # Nếu đã đúng format CAMPUS-xxxxx thì return luôn
    if campus_id.startswith("CAMPUS-"):
        if frappe.db.exists("SIS Campus", campus_id):
            return campus_id
    
    # Nếu là format campus-1, campus-2, etc.
    if campus_id.startswith("campus-"):
        try:
            campus_index = int(campus_id.split("-")[1])
            mapped_campus = f"CAMPUS-{campus_index:05d}"
            if frappe.db.exists("SIS Campus", mapped_campus):
                return mapped_campus
        except (ValueError, IndexError):
            pass
    
    # Thử tìm theo name trực tiếp
    if frappe.db.exists("SIS Campus", campus_id):
        return campus_id
    
    # Thử tìm campus đầu tiên
    first_campus = frappe.db.get_value("SIS Campus", {}, "name", order_by="creation asc")
    if first_campus:
        return first_campus
    
    return None


def _auto_create_student_records(config_id, source_school_year_id, campus_id, logs=None, finance_year_id=None):
    """
    Tự động tạo re-enrollment records cho tất cả học sinh.
    Có thể lấy từ SIS Class Student hoặc SIS Finance Student.
    
    Args:
        config_id: ID của config tái ghi danh
        source_school_year_id: Năm học nguồn (năm học hiện tại của học sinh)
        campus_id: Campus ID
        logs: List để ghi log
        finance_year_id: (Optional) Nếu có, lấy học sinh từ SIS Finance Student thay vì SIS Class Student
    
    Điều kiện:
        - Nếu finance_year_id: lấy từ SIS Finance Student
        - Nếu không: lấy từ SIS Class Student với school_year = source_school_year_id
    """
    if logs is None:
        logs = []
    
    created_count = 0
    
    try:
        students = []
        
        # Nếu có finance_year_id thì lấy từ SIS Finance Student
        if finance_year_id:
            logs.append(f"Lấy học sinh từ Năm tài chính: {finance_year_id}")
            
            # Kiểm tra finance_year có tồn tại và thuộc đúng campus
            finance_year = frappe.db.get_value(
                "SIS Finance Year",
                finance_year_id,
                ["name", "campus_id", "school_year_id"],
                as_dict=True
            )
            
            if not finance_year:
                logs.append(f"Không tìm thấy năm tài chính: {finance_year_id}")
                return 0
            
            if finance_year.campus_id != campus_id:
                logs.append(f"Năm tài chính không thuộc campus {campus_id}")
                return 0
            
            # Lấy học sinh từ SIS Finance Student - loại trừ lớp 12
            # JOIN với SIS Class Student để kiểm tra grade_code
            students = frappe.db.sql("""
                SELECT DISTINCT 
                    fs.student_id,
                    s.student_name,
                    s.student_code,
                    fs.class_title,
                    fs.name as finance_student_id
                FROM `tabSIS Finance Student` fs
                INNER JOIN `tabCRM Student` s ON fs.student_id = s.name
                LEFT JOIN `tabSIS Class Student` cs ON fs.student_id = cs.student_id
                LEFT JOIN `tabSIS Class` c ON cs.class_id = c.name 
                    AND c.school_year_id = %(school_year_id)s
                LEFT JOIN `tabSIS Education Grade` eg ON c.education_grade = eg.name
                WHERE fs.finance_year_id = %(finance_year_id)s
                  AND (eg.grade_code IS NULL OR eg.grade_code != '12')
                  AND (fs.class_title IS NULL OR fs.class_title NOT LIKE '%%12%%')
            """, {
                "finance_year_id": finance_year_id,
                "school_year_id": finance_year.school_year_id or source_school_year_id
            }, as_dict=True)
            
            logs.append(f"Tìm thấy {len(students)} học sinh từ năm tài chính (đã loại bỏ lớp 12)")
        else:
            # Lấy từ SIS Class Student như cũ
            logs.append(f"Lấy học sinh từ năm học nguồn: {source_school_year_id}, Campus: {campus_id}")
            
            # Lấy danh sách học sinh đã xếp lớp REGULAR trong năm học nguồn tại campus này
            # Chỉ lấy lớp regular, không lấy lớp mixed
            # Loại bỏ học sinh lớp 12 (grade_code = '12') vì sẽ tốt nghiệp
            students = frappe.db.sql("""
                SELECT DISTINCT 
                    cs.student_id,
                    s.student_name,
                    s.student_code,
                    c.name as class_name,
                    c.title as class_title
                FROM `tabSIS Class Student` cs
                INNER JOIN `tabSIS Class` c ON cs.class_id = c.name
                INNER JOIN `tabCRM Student` s ON cs.student_id = s.name
                LEFT JOIN `tabSIS Education Grade` eg ON c.education_grade = eg.name
                WHERE c.school_year_id = %(school_year_id)s
                  AND c.campus_id = %(campus_id)s
                  AND (c.class_type = 'regular' OR c.class_type IS NULL OR c.class_type = '')
                  AND (eg.grade_code IS NULL OR eg.grade_code != '12')
                  AND c.title NOT LIKE '%%12%%'
            """, {
                "school_year_id": source_school_year_id,
                "campus_id": campus_id
            }, as_dict=True)
            
            logs.append(f"Tìm thấy {len(students)} học sinh đã xếp lớp (đã loại bỏ lớp 12)")
        
        # Xóa học sinh lớp 12 đã có trong config (chưa submit)
        # Chỉ xóa những record chưa có decision để không mất dữ liệu đã submit
        deleted_count = 0
        grade12_records = frappe.db.sql("""
            SELECT re.name, re.student_code, re.current_class
            FROM `tabSIS Re-enrollment` re
            WHERE re.config_id = %(config_id)s
              AND (re.decision IS NULL OR re.decision = '')
              AND (
                  re.current_class LIKE '%%12%%'
                  OR EXISTS (
                      SELECT 1 FROM `tabSIS Class Student` cs
                      INNER JOIN `tabSIS Class` c ON cs.class_id = c.name
                      LEFT JOIN `tabSIS Education Grade` eg ON c.education_grade = eg.name
                      WHERE cs.student_id = re.student_id
                        AND c.school_year_id = %(school_year_id)s
                        AND eg.grade_code = '12'
                  )
              )
        """, {
            "config_id": config_id,
            "school_year_id": source_school_year_id
        }, as_dict=True)
        
        for record in grade12_records:
            try:
                frappe.delete_doc("SIS Re-enrollment", record.name, ignore_permissions=True, force=True)
                deleted_count += 1
            except Exception as e:
                logs.append(f"Lỗi xóa record lớp 12 {record.student_code}: {str(e)}")
        
        if deleted_count > 0:
            logs.append(f"Đã xóa {deleted_count} học sinh lớp 12 (chưa submit)")
        
        # Tạo records cho từng học sinh
        for student in students:
            try:
                # Kiểm tra đã có record chưa
                existing = frappe.db.exists("SIS Re-enrollment", {
                    "config_id": config_id,
                    "student_id": student.student_id
                })
                
                if existing:
                    continue
                
                # Tạo record mới (chưa có decision, chưa submit)
                re_doc = frappe.get_doc({
                    "doctype": "SIS Re-enrollment",
                    "config_id": config_id,
                    "student_id": student.student_id,
                    "student_name": student.student_name,
                    "student_code": student.student_code,
                    "current_class": student.class_title or student.class_name,
                    "campus_id": campus_id,
                    "status": "pending"
                    # decision và submitted_at để trống = chưa làm đơn
                })
                # Skip validation thời gian khi admin tạo records
                re_doc.flags.skip_config_validation = True
                re_doc.insert(ignore_permissions=True)
                created_count += 1
                
            except Exception as e:
                logs.append(f"Lỗi tạo record cho {student.student_code}: {str(e)}")
                continue
        
        frappe.db.commit()
        
    except Exception as e:
        logs.append(f"Lỗi auto-create records: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Auto Create Re-enrollment Records Error")
        deleted_count = 0
    
    return {"created_count": created_count, "deleted_count": deleted_count}


# ==================== CONFIG APIs ====================

@frappe.whitelist()
def get_configs():
    """
    Lấy danh sách tất cả cấu hình tái ghi danh.
    Có thể filter theo campus_id.
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền truy cập", logs=logs)
        
        # Lấy filter từ query params
        campus_id = frappe.request.args.get('campus_id')
        
        filters = {}
        if campus_id:
            filters["campus_id"] = campus_id
        
        configs = frappe.get_all(
            "SIS Re-enrollment Config",
            filters=filters,
            fields=["*"],  # Lấy tất cả fields để tránh lỗi khi chưa migrate
            order_by="modified desc"
        )
        
        # Thêm thông tin bổ sung cho mỗi config
        for config in configs:
            # Tên năm học
            school_year = frappe.db.get_value(
                "SIS School Year",
                config.get("school_year_id"),
                ["title_vn", "title_en"],
                as_dict=True
            )
            config["school_year_name"] = school_year.title_vn if school_year else None
            
            # Tên campus (SIS Campus dùng title_vn, không phải title)
            campus_info = frappe.db.get_value(
                "SIS Campus", 
                config.get("campus_id"), 
                ["title_vn", "title_en"],
                as_dict=True
            )
            config["campus_name"] = campus_info.title_vn if campus_info else None
            
            # Đếm số đơn
            submission_count = frappe.db.count(
                "SIS Re-enrollment",
                {"config_id": config.name}
            )
            config["submission_count"] = submission_count
            
            # Số mức ưu đãi
            discount_count = frappe.db.count(
                "SIS Re-enrollment Discount",
                {"parent": config.name}
            )
            config["discount_count"] = discount_count
        
        logs.append(f"Tìm thấy {len(configs)} cấu hình")
        
        return list_response(configs)
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Admin Get Re-enrollment Configs Error")
        return error_response(
            message=f"Lỗi khi lấy danh sách cấu hình: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def get_config(config_id=None):
    """
    Lấy chi tiết một cấu hình tái ghi danh.
    Bao gồm bảng ưu đãi.
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền truy cập", logs=logs)
        
        if not config_id:
            config_id = frappe.request.args.get('config_id')
        
        if not config_id:
            return validation_error_response(
                "Thiếu config_id",
                {"config_id": ["Config ID là bắt buộc"]}
            )
        
        # Kiểm tra config tồn tại
        if not frappe.db.exists("SIS Re-enrollment Config", config_id):
            return not_found_response("Không tìm thấy cấu hình tái ghi danh")
        
        config = frappe.get_doc("SIS Re-enrollment Config", config_id)
        
        # Lấy bảng ưu đãi
        discounts = frappe.get_all(
            "SIS Re-enrollment Discount",
            filters={"parent": config_id},
            fields=["name", "deadline", "description", "annual_discount", "semester_discount"],
            order_by="deadline asc"
        )
        
        # Convert deadline sang string để đảm bảo format nhất quán
        for discount in discounts:
            if discount.get("deadline"):
                discount["deadline"] = str(discount["deadline"])
        
        # Lấy câu hỏi khảo sát từ config document
        questions = []
        for q in config.questions:
            # Parse options từ JSON
            options = []
            if q.options_json:
                try:
                    options = json.loads(q.options_json)
                except:
                    options = []
            
            questions.append({
                "name": q.name,
                "question_vn": q.question_vn,
                "question_en": q.question_en,
                "question_type": q.question_type,
                "is_required": q.is_required,
                "sort_order": q.sort_order,
                "options": options
            })
        
        # Tên năm học
        school_year = frappe.db.get_value(
            "SIS School Year",
            config.school_year_id,
            ["title_vn", "title_en"],
            as_dict=True
        )
        
        # Tên campus
        # SIS Campus dùng title_vn thay vì title
        campus_info = frappe.db.get_value("SIS Campus", config.campus_id, ["title_vn", "title_en"], as_dict=True)
        campus_name = campus_info.title_vn if campus_info else None
        
        logs.append(f"Lấy config: {config_id}")
        
        return single_item_response(
            data={
                "name": config.name,
                "title": config.title,
                "source_school_year_id": config.source_school_year_id,
                "school_year_id": config.school_year_id,
                "school_year_name_vn": school_year.title_vn if school_year else None,
                "school_year_name_en": school_year.title_en if school_year else None,
                "campus_id": config.campus_id,
                "campus_name": campus_name,
                "is_active": config.is_active,
                "start_date": str(config.start_date) if config.start_date else None,
                "end_date": str(config.end_date) if config.end_date else None,
                "service_document": config.service_document,
                "service_document_images": json.loads(config.service_document_images) if config.service_document_images else [],
                "agreement_text": config.agreement_text,
                "agreement_text_en": config.agreement_text_en,
                "discounts": discounts,
                "questions": questions,
                "created_by": config.created_by,
                "created_at": str(config.created_at) if config.created_at else None
            },
            message="Lấy cấu hình thành công"
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Admin Get Re-enrollment Config Error")
        return error_response(
            message=f"Lỗi khi lấy cấu hình: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def create_config():
    """
    Tạo cấu hình tái ghi danh mới.
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền truy cập", logs=logs)
        
        # Lấy data từ request
        if frappe.request.is_json:
            data = frappe.request.json or {}
        else:
            data = frappe.form_dict
        
        logs.append(f"Tạo config mới: {json.dumps(data, default=str)}")
        
        # Validate required fields
        required_fields = ['title', 'source_school_year_id', 'school_year_id', 'campus_id', 'start_date', 'end_date']
        for field in required_fields:
            if field not in data or not data[field]:
                return validation_error_response(
                    f"Thiếu trường bắt buộc: {field}",
                    {field: [f"Trường {field} là bắt buộc"]}
                )
        
        # Resolve campus_id từ format frontend sang format database
        resolved_campus_id = _resolve_campus_id(data['campus_id'])
        if not resolved_campus_id:
            return validation_error_response(
                f"Không tìm thấy Campus: {data['campus_id']}",
                {"campus_id": ["Campus không tồn tại trong hệ thống"]}
            )
        data['campus_id'] = resolved_campus_id
        logs.append(f"Resolved campus_id: {resolved_campus_id}")
        
        # Xử lý service_document_images
        service_document_images = data.get('service_document_images')
        if service_document_images and isinstance(service_document_images, list):
            service_document_images = json.dumps(service_document_images)
        elif service_document_images and isinstance(service_document_images, str):
            # Đã là JSON string rồi
            pass
        else:
            service_document_images = None
        
        # Tạo document
        config_doc = frappe.get_doc({
            "doctype": "SIS Re-enrollment Config",
            "title": data['title'],
            "source_school_year_id": data['source_school_year_id'],
            "school_year_id": data['school_year_id'],
            "campus_id": data['campus_id'],
            "is_active": data.get('is_active', 0),
            "start_date": data['start_date'],
            "end_date": data['end_date'],
            "service_document": data.get('service_document'),
            "service_document_images": service_document_images,
            "agreement_text": data.get('agreement_text'),
            "agreement_text_en": data.get('agreement_text_en'),
            "finance_year_id": data.get('finance_year_id')  # Năm tài chính (optional)
        })
        
        # Thêm bảng ưu đãi nếu có
        discounts = data.get('discounts', [])
        if isinstance(discounts, str):
            discounts = json.loads(discounts)
        
        for discount in discounts:
            config_doc.append("discounts", {
                "deadline": discount.get('deadline'),
                "description": discount.get('description'),
                "annual_discount": discount.get('annual_discount', 0),
                "semester_discount": discount.get('semester_discount', 0)
            })
        
        # Thêm câu hỏi khảo sát nếu có
        questions_data = data.get('questions', [])
        if isinstance(questions_data, str):
            questions_data = json.loads(questions_data)
        
        # Thêm questions với options (lưu dưới dạng JSON)
        for idx, question in enumerate(questions_data):
            options_data = question.get('options', [])
            
            config_doc.append("questions", {
                "question_vn": question.get('question_vn'),
                "question_en": question.get('question_en'),
                "question_type": question.get('question_type', 'single_choice'),
                "is_required": question.get('is_required', 1),
                "sort_order": question.get('sort_order', idx),
                "options_json": json.dumps(options_data) if options_data else None
            })
        
        config_doc.insert()
        frappe.db.commit()
        
        logs.append(f"Đã tạo config: {config_doc.name}")
        
        # Auto-create re-enrollment records cho tất cả học sinh
        # Ưu tiên lấy từ Finance Year nếu có, không thì lấy từ SIS Class Student
        result = _auto_create_student_records(
            config_doc.name, 
            data['source_school_year_id'],  # Dùng năm học nguồn để lấy danh sách học sinh
            resolved_campus_id,
            logs,
            finance_year_id=data.get('finance_year_id')  # Nếu có thì lấy từ Finance Year
        )
        
        created_count = result.get("created_count", 0)
        deleted_count = result.get("deleted_count", 0)
        
        logs.append(f"Đã tạo {created_count} records cho học sinh")
        if deleted_count > 0:
            logs.append(f"Đã xóa {deleted_count} học sinh lớp 12")
        
        return success_response(
            data={
                "name": config_doc.name,
                "title": config_doc.title,
                "student_records_created": created_count,
                "grade12_deleted": deleted_count
            },
            message=f"Tạo cấu hình tái ghi danh thành công. Đã tạo {created_count} đơn cho học sinh.",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Admin Create Re-enrollment Config Error")
        return error_response(
            message=f"Lỗi khi tạo cấu hình: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def update_config():
    """
    Cập nhật cấu hình tái ghi danh.
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền truy cập", logs=logs)
        
        # Lấy data từ request
        if frappe.request.is_json:
            data = frappe.request.json or {}
        else:
            data = frappe.form_dict
        
        config_id = data.get('name') or data.get('config_id')
        if not config_id:
            return validation_error_response(
                "Thiếu config_id",
                {"config_id": ["Config ID là bắt buộc"]}
            )
        
        logs.append(f"Cập nhật config: {config_id}")
        
        # Lấy document
        if not frappe.db.exists("SIS Re-enrollment Config", config_id):
            return not_found_response("Không tìm thấy cấu hình")
        
        config_doc = frappe.get_doc("SIS Re-enrollment Config", config_id)
        
        # Resolve campus_id nếu có
        if 'campus_id' in data and data['campus_id']:
            resolved_campus_id = _resolve_campus_id(data['campus_id'])
            if resolved_campus_id:
                data['campus_id'] = resolved_campus_id
                logs.append(f"Resolved campus_id: {resolved_campus_id}")
        
        # Update các trường
        update_fields = ['title', 'source_school_year_id', 'school_year_id', 'campus_id', 'is_active', 
                        'start_date', 'end_date', 'service_document', 'agreement_text', 'agreement_text_en']
        
        for field in update_fields:
            if field in data:
                config_doc.set(field, data[field])
        
        # Xử lý riêng service_document_images vì cần convert từ list sang JSON string
        if 'service_document_images' in data:
            service_document_images = data['service_document_images']
            if isinstance(service_document_images, list):
                config_doc.service_document_images = json.dumps(service_document_images)
            elif isinstance(service_document_images, str):
                config_doc.service_document_images = service_document_images
            else:
                config_doc.service_document_images = None
        
        # Update bảng ưu đãi nếu có
        if 'discounts' in data:
            discounts = data['discounts']
            if isinstance(discounts, str):
                discounts = json.loads(discounts)
            
            # Xóa discounts cũ
            config_doc.discounts = []
            
            # Thêm discounts mới
            for discount in discounts:
                config_doc.append("discounts", {
                    "deadline": discount.get('deadline'),
                    "description": discount.get('description'),
                    "annual_discount": discount.get('annual_discount', 0),
                    "semester_discount": discount.get('semester_discount', 0)
                })
        
        # Update câu hỏi khảo sát nếu có
        if 'questions' in data:
            questions_data = data['questions']
            if isinstance(questions_data, str):
                questions_data = json.loads(questions_data)
            
            logs.append(f"Updating {len(questions_data)} questions")
            
            # Xóa questions cũ
            config_doc.questions = []
            
            # Thêm questions mới với options (lưu dưới dạng JSON)
            for idx, question in enumerate(questions_data):
                options_data = question.get('options', [])
                logs.append(f"Question {idx}: {len(options_data)} options")
                
                config_doc.append("questions", {
                    "question_vn": question.get('question_vn'),
                    "question_en": question.get('question_en'),
                    "question_type": question.get('question_type', 'single_choice'),
                    "is_required": question.get('is_required', 1),
                    "sort_order": question.get('sort_order', idx),
                    "options_json": json.dumps(options_data) if options_data else None
                })
        
        config_doc.save()
        frappe.db.commit()
        
        logs.append(f"Đã cập nhật config: {config_id}")
        
        return success_response(
            data={"name": config_doc.name},
            message="Cập nhật cấu hình thành công",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Admin Update Re-enrollment Config Error")
        return error_response(
            message=f"Lỗi khi cập nhật cấu hình: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def toggle_config_active():
    """
    Bật/tắt cấu hình tái ghi danh.
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền truy cập", logs=logs)
        
        # Lấy data
        if frappe.request.is_json:
            data = frappe.request.json or {}
        else:
            data = frappe.form_dict
        
        config_id = data.get('config_id')
        is_active = data.get('is_active')
        
        if not config_id:
            return validation_error_response(
                "Thiếu config_id",
                {"config_id": ["Config ID là bắt buộc"]}
            )
        
        logs.append(f"Toggle config {config_id} -> is_active={is_active}")
        
        config_doc = frappe.get_doc("SIS Re-enrollment Config", config_id)
        config_doc.is_active = 1 if is_active else 0
        config_doc.save()
        
        frappe.db.commit()
        
        status_text = "đã mở" if is_active else "đã đóng"
        
        return success_response(
            data={"name": config_id, "is_active": config_doc.is_active},
            message=f"Đợt tái ghi danh {status_text}",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Admin Toggle Config Active Error")
        return error_response(
            message=f"Lỗi: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def delete_config():
    """
    Xóa cấu hình tái ghi danh.
    Chỉ xóa được nếu chưa có đơn nào, trừ khi:
    - User có role System Manager VÀ force_delete=true
    - Khi đó sẽ xóa tất cả đơn trước khi xóa config
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền truy cập", logs=logs)
        
        # Lấy data
        if frappe.request.is_json:
            data = frappe.request.json or {}
        else:
            data = frappe.form_dict
        
        config_id = data.get('config_id')
        force_delete = data.get('force_delete', False)
        
        # Chuyển đổi force_delete sang boolean nếu là string
        if isinstance(force_delete, str):
            force_delete = force_delete.lower() in ('true', '1', 'yes')
        
        if not config_id:
            return validation_error_response(
                "Thiếu config_id",
                {"config_id": ["Config ID là bắt buộc"]}
            )
        
        # Kiểm tra có đơn nào không
        submission_count = frappe.db.count(
            "SIS Re-enrollment",
            {"config_id": config_id}
        )
        
        if submission_count > 0:
            # Kiểm tra nếu user là System Manager và force_delete=true
            is_system_manager = "System Manager" in frappe.get_roles(frappe.session.user)
            
            if force_delete and is_system_manager:
                # Xóa tất cả đơn tái ghi danh của config này
                logs.append(f"System Manager đang xóa {submission_count} đơn tái ghi danh...")
                
                submissions = frappe.get_all(
                    "SIS Re-enrollment",
                    filters={"config_id": config_id},
                    pluck="name"
                )
                
                for submission_name in submissions:
                    frappe.delete_doc("SIS Re-enrollment", submission_name, force=True)
                
                logs.append(f"Đã xóa {len(submissions)} đơn tái ghi danh")
            else:
                # Không có quyền force delete
                if not is_system_manager:
                    return error_response(
                        f"Không thể xóa vì đã có {submission_count} đơn tái ghi danh. Chỉ System Manager mới có quyền xóa.",
                        logs=logs
                    )
                else:
                    return error_response(
                        f"Không thể xóa vì đã có {submission_count} đơn tái ghi danh",
                        logs=logs
                    )
        
        # Xóa config
        frappe.delete_doc("SIS Re-enrollment Config", config_id)
        frappe.db.commit()
        
        logs.append(f"Đã xóa config: {config_id}")
        
        return success_response(
            message="Xóa cấu hình thành công" + (f" (bao gồm {submission_count} đơn)" if submission_count > 0 else ""),
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Admin Delete Config Error")
        return error_response(
            message=f"Lỗi khi xóa: {str(e)}",
            logs=logs
        )


# ==================== SUBMISSION APIs ====================

@frappe.whitelist()
def get_submissions():
    """
    Lấy danh sách đơn tái ghi danh.
    Có thể filter theo config_id, status, decision.
    Nếu config có finance_year_id, payment_status được lấy từ SIS Finance Student.
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền truy cập", logs=logs)
        
        # Lấy filters từ query params
        config_id = frappe.request.args.get('config_id')
        status = frappe.request.args.get('status')
        decision = frappe.request.args.get('decision')
        adjustment_status = frappe.request.args.get('adjustment_status')
        search = frappe.request.args.get('search')
        page = int(frappe.request.args.get('page', 1))
        page_size = int(frappe.request.args.get('page_size', 50))
        
        # Kiểm tra config có finance_year_id không
        finance_year_id = None
        if config_id:
            finance_year_id = frappe.db.get_value(
                "SIS Re-enrollment Config",
                config_id,
                "finance_year_id"
            )
        
        logs.append(f"Config {config_id}, Finance Year: {finance_year_id or 'None'}")
        
        # Build query
        conditions = []
        values = {}
        
        if config_id:
            conditions.append("re.config_id = %(config_id)s")
            values["config_id"] = config_id
        
        # Xử lý status đặc biệt: not_submitted = decision IS NULL hoặc rỗng
        if status == 'not_submitted':
            conditions.append("(re.decision IS NULL OR re.decision = '')")
        elif status:
            conditions.append("re.status = %(status)s")
            values["status"] = status
        
        if decision:
            conditions.append("re.decision = %(decision)s")
            values["decision"] = decision
        
        # Filter theo adjustment_status
        if adjustment_status:
            conditions.append("re.adjustment_status = %(adjustment_status)s")
            values["adjustment_status"] = adjustment_status
        
        # Search by student name or code
        if search:
            conditions.append("(re.student_name LIKE %(search)s OR re.student_code LIKE %(search)s)")
            values["search"] = f"%{search}%"
        
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        
        # Count total
        total_query = f"""
            SELECT COUNT(*) as total
            FROM `tabSIS Re-enrollment` re
            WHERE {where_clause}
        """
        total = frappe.db.sql(total_query, values, as_dict=True)[0].total
        
        # Get submissions with pagination
        # Nếu có finance_year_id, join với Finance Student để lấy payment_status
        offset = (page - 1) * page_size
        
        if finance_year_id:
            # JOIN với Finance Student để lấy payment_status từ đó
            values["finance_year_id"] = finance_year_id
            query = f"""
                SELECT 
                    re.name, re.config_id, re.student_id, re.student_name, re.student_code,
                    re.guardian_id, re.guardian_name, g.phone_number as guardian_phone, g.email as guardian_email, 
                    re.current_class, re.campus_id,
                    re.decision, re.payment_type, re.not_re_enroll_reason,
                    COALESCE(fs.payment_status, re.payment_status) as payment_status,
                    fs.total_amount as finance_total_amount,
                    fs.paid_amount as finance_paid_amount,
                    fs.outstanding_amount as finance_outstanding_amount,
                    re.selected_discount_id, re.selected_discount_name, re.selected_discount_percent,
                    re.selected_discount_deadline,
                    re.adjustment_status, re.adjustment_requested_at,
                    re.submitted_at, re.modified_by_admin, re.admin_modified_at
                FROM `tabSIS Re-enrollment` re
                LEFT JOIN `tabCRM Guardian` g ON re.guardian_id = g.name
                LEFT JOIN `tabSIS Finance Student` fs ON fs.student_id = re.student_id 
                    AND fs.finance_year_id = %(finance_year_id)s
                WHERE {where_clause}
                ORDER BY re.submitted_at DESC
                LIMIT {page_size} OFFSET {offset}
            """
        else:
            # Không có finance_year_id, dùng query cũ
            query = f"""
                SELECT 
                    re.name, re.config_id, re.student_id, re.student_name, re.student_code,
                    re.guardian_id, re.guardian_name, g.phone_number as guardian_phone, g.email as guardian_email, 
                    re.current_class, re.campus_id,
                    re.decision, re.payment_type, re.not_re_enroll_reason,
                    re.payment_status, re.selected_discount_id, re.selected_discount_name, re.selected_discount_percent,
                    re.selected_discount_deadline,
                    re.adjustment_status, re.adjustment_requested_at,
                    re.submitted_at, re.modified_by_admin, re.admin_modified_at
                FROM `tabSIS Re-enrollment` re
                LEFT JOIN `tabCRM Guardian` g ON re.guardian_id = g.name
                WHERE {where_clause}
                ORDER BY re.submitted_at DESC
                LIMIT {page_size} OFFSET {offset}
            """
        
        submissions = frappe.db.sql(query, values, as_dict=True)
        
        # Thêm display values và answers
        for sub in submissions:
            # Decision display
            decision_map = {
                "re_enroll": "Tái ghi danh",
                "considering": "Cân nhắc",
                "not_re_enroll": "Không tái ghi danh"
            }
            sub["decision_display"] = decision_map.get(sub.decision, "Chưa làm đơn")
            
            # Payment type display
            if sub.payment_type:
                sub["payment_display"] = "Đóng theo năm" if sub.payment_type == 'annual' else "Đóng theo kỳ"
            
            # Payment status display
            payment_status_map = {
                "unpaid": "Chưa đóng",
                "paid": "Đã đóng",
                "refunded": "Hoàn tiền"
            }
            sub["payment_status_display"] = payment_status_map.get(sub.payment_status, "-")
            
            # Convert selected_discount_deadline sang string nếu có
            if sub.get("selected_discount_deadline"):
                sub["selected_discount_deadline"] = str(sub["selected_discount_deadline"])
            
            # Lấy answers (câu trả lời khảo sát)
            answers = frappe.get_all(
                "SIS Re-enrollment Answer",
                filters={"parent": sub.name},
                fields=["question_id", "question_text_vn", "question_text_en", 
                        "selected_options", "selected_options_text_vn", "selected_options_text_en"]
            )
            sub["answers"] = answers
            
            # Lấy notes (lịch sử log)
            notes = frappe.get_all(
                "SIS Re-enrollment Note",
                filters={"parent": sub.name},
                fields=["note_type", "note", "created_by_user", "created_by_name", "created_at"],
                order_by="created_at asc"
            )
            sub["notes"] = notes
        
        logs.append(f"Tìm thấy {len(submissions)} / {total} đơn")
        
        return success_response(
            data={
                "items": submissions,
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": (total + page_size - 1) // page_size
            },
            message="Lấy danh sách đơn thành công",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Admin Get Submissions Error")
        return error_response(
            message=f"Lỗi: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def get_submission(submission_id=None):
    """
    Lấy chi tiết một đơn tái ghi danh.
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền truy cập", logs=logs)
        
        if not submission_id:
            submission_id = frappe.request.args.get('submission_id')
        
        if not submission_id:
            return validation_error_response(
                "Thiếu submission_id",
                {"submission_id": ["Submission ID là bắt buộc"]}
            )
        
        if not frappe.db.exists("SIS Re-enrollment", submission_id):
            return not_found_response("Không tìm thấy đơn tái ghi danh")
        
        submission = frappe.get_doc("SIS Re-enrollment", submission_id)
        
        # Lấy thông tin config
        config_info = frappe.db.get_value(
            "SIS Re-enrollment Config",
            submission.config_id,
            ["title", "school_year_id"],
            as_dict=True
        )
        
        # Lấy thông tin guardian (phone, email) từ CRM Guardian
        guardian_info = frappe.db.get_value(
            "CRM Guardian",
            submission.guardian_id,
            ["phone_number", "email"],
            as_dict=True
        ) if submission.guardian_id else None
        
        return single_item_response(
            data={
                "name": submission.name,
                "config_id": submission.config_id,
                "config_title": config_info.title if config_info else None,
                "student_id": submission.student_id,
                "student_name": submission.student_name,
                "student_code": submission.student_code,
                "guardian_id": submission.guardian_id,
                "guardian_name": submission.guardian_name,
                "guardian_phone": guardian_info.phone_number if guardian_info else None,
                "guardian_email": guardian_info.email if guardian_info else None,
                "current_class": submission.current_class,
                "decision": submission.decision,
                "decision_display": "Tái ghi danh" if submission.decision == 're_enroll' else "Không tái ghi danh",
                "payment_type": submission.payment_type,
                "payment_display": "Đóng theo năm" if submission.payment_type == 'annual' else ("Đóng theo kỳ" if submission.payment_type == 'semester' else None),
                "selected_discount_deadline": str(submission.selected_discount_deadline) if submission.selected_discount_deadline else None,
                "not_re_enroll_reason": submission.not_re_enroll_reason,
                "agreement_accepted": submission.agreement_accepted,
                "status": submission.status,
                "submitted_at": str(submission.submitted_at) if submission.submitted_at else None,
                "modified_by_admin": submission.modified_by_admin,
                "admin_modified_at": str(submission.admin_modified_at) if submission.admin_modified_at else None,
                "admin_notes": submission.admin_notes
            },
            message="Lấy thông tin đơn thành công"
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Admin Get Submission Error")
        return error_response(
            message=f"Lỗi: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def update_submission():
    """
    Admin sửa đơn tái ghi danh cho phụ huynh.
    Ghi nhận admin đã sửa.
    
    POST body:
    {
        "submission_id": "SIS-REENROLL-00001",
        "decision": "re_enroll" | "considering" | "not_re_enroll",
        "payment_type": "annual" | "semester",
        "selected_discount_id": "...",
        "not_re_enroll_reason": "...",
        "payment_status": "unpaid" | "paid" | "refunded",
        "notes": [{"note": "...", "created_by_name": "..."}]
    }
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền truy cập", logs=logs)
        
        # Lấy data
        if frappe.request.is_json:
            data = frappe.request.json or {}
        else:
            data = frappe.form_dict
        
        submission_id = data.get('submission_id') or data.get('name')
        if not submission_id:
            return validation_error_response(
                "Thiếu submission_id",
                {"submission_id": ["Submission ID là bắt buộc"]}
            )
        
        logs.append(f"Admin sửa đơn: {submission_id}")
        
        if not frappe.db.exists("SIS Re-enrollment", submission_id):
            return not_found_response("Không tìm thấy đơn tái ghi danh")
        
        submission = frappe.get_doc("SIS Re-enrollment", submission_id)
        
        # Lưu lại giá trị cũ để so sánh và tạo log
        old_values = {
            'decision': submission.decision,
            'payment_type': submission.payment_type,
            'selected_discount_id': submission.selected_discount_id,
            'not_re_enroll_reason': submission.not_re_enroll_reason,
            'payment_status': submission.payment_status,
            'adjustment_status': submission.adjustment_status
        }
        
        # Lưu lại answers cũ để so sánh
        old_answers = []
        for ans in submission.answers:
            old_answers.append({
                'question_id': ans.question_id,
                'selected_options_text_vn': ans.selected_options_text_vn
            })
        
        # Lưu lại các system_log cũ (để không bị mất khi clear notes)
        old_system_logs = []
        for note in submission.notes:
            if note.note_type == 'system_log':
                old_system_logs.append({
                    'note_type': note.note_type,
                    'note': note.note,
                    'created_by_user': note.created_by_user,
                    'created_by_name': note.created_by_name,
                    'created_at': note.created_at
                })
        
        # Các trường admin có thể sửa
        updatable_fields = ['decision', 'payment_type', 'selected_discount_id', 
                          'not_re_enroll_reason', 'payment_status', 'adjustment_status']
        
        for field in updatable_fields:
            if field in data:
                submission.set(field, data[field])
        
        # Xử lý discount info nếu chọn
        if data.get('selected_discount_id') and data.get('decision') == 're_enroll':
            # Lấy config để tìm thông tin discount
            config = frappe.get_doc("SIS Re-enrollment Config", submission.config_id)
            payment_type = data.get('payment_type') or submission.payment_type
            for discount in config.discounts:
                if discount.name == data.get('selected_discount_id'):
                    submission.selected_discount_name = discount.description
                    submission.selected_discount_deadline = discount.deadline
                    # Lưu % giảm dựa trên payment_type
                    if payment_type == 'annual':
                        submission.selected_discount_percent = discount.annual_discount
                    else:
                        submission.selected_discount_percent = discount.semester_discount
                    break
        
        # Xử lý notes - clear và thêm mới
        notes_data = data.get('notes', [])
        
        # Clear existing notes
        submission.notes = []
        
        # Lấy full name của user hiện tại
        current_user = frappe.session.user
        current_user_name = frappe.db.get_value("User", current_user, "full_name") or current_user
        
        # Thêm lại các system_log cũ trước
        for old_log in old_system_logs:
            submission.append("notes", old_log)
        
        # Add manual notes từ frontend (chỉ lấy manual_note, bỏ qua system_log vì đã thêm ở trên)
        if notes_data:
            for note in notes_data:
                # Bỏ qua system_log từ frontend (đã có từ old_system_logs)
                if note.get('note_type') == 'system_log':
                    continue
                    
                # Convert ISO datetime to MySQL format nếu cần
                created_at = note.get('created_at')
                if created_at:
                    try:
                        # Parse ISO format và convert sang MySQL format
                        from datetime import datetime
                        if 'T' in str(created_at):
                            dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                            created_at = dt.strftime('%Y-%m-%d %H:%M:%S')
                    except:
                        created_at = now()
                else:
                    created_at = now()
                
                submission.append("notes", {
                    "note_type": "manual_note",
                    "note": note.get('note'),
                    "created_by_user": note.get('created_by_user') or current_user,
                    "created_by_name": note.get('created_by_name') or current_user_name,
                    "created_at": created_at
                })
        
        # Clear các field không cần thiết dựa trên decision
        decision = data.get('decision')
        if decision == 're_enroll':
            submission.not_re_enroll_reason = None
        elif decision in ['considering', 'not_re_enroll']:
            submission.payment_type = None
            submission.selected_discount_id = None
            submission.selected_discount_name = None
            submission.selected_discount_deadline = None
        
        # Xử lý answers (câu trả lời khảo sát)
        answers_data = data.get('answers', [])
        if answers_data:
            # Clear existing answers
            submission.answers = []
            
            # Add new answers
            for answer in answers_data:
                selected_options = answer.get('selected_options', [])
                if isinstance(selected_options, list):
                    selected_options_json = json.dumps(selected_options)
                else:
                    selected_options_json = selected_options
                
                submission.append("answers", {
                    "question_id": answer.get('question_id'),
                    "question_text_vn": answer.get('question_text_vn'),
                    "question_text_en": answer.get('question_text_en'),
                    "selected_options": selected_options_json,
                    "selected_options_text_vn": answer.get('selected_options_text_vn'),
                    "selected_options_text_en": answer.get('selected_options_text_en')
                })
        
        # Tạo log hệ thống về thay đổi của admin
        changes = []
        important_changes = []  # Các thay đổi quan trọng cần gửi notification (Trạng thái, Khảo sát)
        decision_map = {
            're_enroll': 'Tái ghi danh',
            'considering': 'Cân nhắc', 
            'not_re_enroll': 'Không tái ghi danh'
        }
        payment_type_map = {'annual': 'Đóng theo năm', 'semester': 'Đóng theo kỳ'}
        payment_status_map = {'unpaid': 'Chưa đóng', 'paid': 'Đã đóng', 'refunded': 'Hoàn tiền'}
        
        # So sánh decision (QUAN TRỌNG - gửi notification)
        new_decision = data.get('decision') or submission.decision
        if old_values['decision'] != new_decision:
            old_display = decision_map.get(old_values['decision'], old_values['decision'] or 'Chưa có')
            new_display = decision_map.get(new_decision, new_decision)
            changes.append(f"• Quyết định: {old_display} → {new_display}")
            important_changes.append('decision')
        
        # So sánh payment_type (QUAN TRỌNG - gửi notification)
        new_payment_type = data.get('payment_type') or submission.payment_type
        if old_values['payment_type'] != new_payment_type and new_decision == 're_enroll':
            old_display = payment_type_map.get(old_values['payment_type'], old_values['payment_type'] or 'Chưa có')
            new_display = payment_type_map.get(new_payment_type, new_payment_type)
            changes.append(f"• Phương thức: {old_display} → {new_display}")
            important_changes.append('payment_type')
        
        # So sánh payment_status (KHÔNG gửi notification - chỉ log)
        new_payment_status = data.get('payment_status') or submission.payment_status
        if old_values['payment_status'] != new_payment_status:
            old_display = payment_status_map.get(old_values['payment_status'], old_values['payment_status'] or 'Chưa có')
            new_display = payment_status_map.get(new_payment_status, new_payment_status)
            changes.append(f"• Thanh toán: {old_display} → {new_display}")
            # Không thêm vào important_changes
        
        # So sánh adjustment_status (QUAN TRỌNG - gửi notification khi hoàn tất điều chỉnh)
        adjustment_status_map = {'requested': 'Yêu cầu điều chỉnh', 'completed': 'Đã điều chỉnh'}
        new_adjustment_status = data.get('adjustment_status') or submission.adjustment_status
        if old_values['adjustment_status'] != new_adjustment_status:
            old_display = adjustment_status_map.get(old_values['adjustment_status'], old_values['adjustment_status'] or 'Chưa có')
            new_display = adjustment_status_map.get(new_adjustment_status, new_adjustment_status)
            changes.append(f"• Trạng thái điều chỉnh: {old_display} → {new_display}")
            # Gửi notification khi admin hoàn tất điều chỉnh
            if new_adjustment_status == 'completed':
                important_changes.append('adjustment_completed')
        
        # So sánh discount (QUAN TRỌNG - gửi notification)
        new_discount_id = data.get('selected_discount_id') or submission.selected_discount_id
        if old_values['selected_discount_id'] != new_discount_id:
            changes.append(f"• Ưu đãi: Đã cập nhật")
            important_changes.append('discount')
        
        # So sánh lý do (QUAN TRỌNG - gửi notification)
        new_reason = data.get('not_re_enroll_reason') or submission.not_re_enroll_reason
        if old_values['not_re_enroll_reason'] != new_reason and new_decision in ['considering', 'not_re_enroll']:
            changes.append(f"• Lý do: Đã cập nhật")
            important_changes.append('reason')
        
        # So sánh answers (QUAN TRỌNG - gửi notification)
        new_answers_data = data.get('answers', [])
        answers_changed = False
        
        if new_answers_data:
            # So sánh số lượng
            if len(new_answers_data) != len(old_answers):
                answers_changed = True
            else:
                # So sánh nội dung từng câu trả lời
                for new_ans in new_answers_data:
                    q_id = new_ans.get('question_id')
                    new_text = new_ans.get('selected_options_text_vn', '')
                    
                    # Tìm câu trả lời cũ tương ứng
                    old_ans = next((a for a in old_answers if a['question_id'] == q_id), None)
                    
                    if not old_ans:
                        # Câu hỏi mới
                        answers_changed = True
                        break
                    elif old_ans['selected_options_text_vn'] != new_text:
                        # Nội dung khác
                        answers_changed = True
                        break
        
        if answers_changed:
            changes.append(f"• Khảo sát: Đã cập nhật câu trả lời")
            important_changes.append('answers')
        
        # Nếu có thay đổi thì tạo log
        if changes:
            log_content = f"Admin {current_user_name} đã cập nhật đơn:\n" + "\n".join(changes)
            submission.append("notes", {
                "note_type": "system_log",
                "note": log_content,
                "created_by_user": current_user,
                "created_by_name": current_user_name,
                "created_at": now()
            })
        
        # Ghi nhận admin sửa
        submission.modified_by_admin = frappe.session.user
        submission.admin_modified_at = now()
        
        # Cập nhật submitted_at nếu chưa có
        if not submission.submitted_at:
            submission.submitted_at = now()
        
        submission.save()
        frappe.db.commit()
        
        logs.append(f"Đã cập nhật đơn: {submission_id}")
        
        # Chỉ gửi thông báo khi có thay đổi quan trọng (Trạng thái hoặc Khảo sát)
        # KHÔNG gửi khi chỉ thay đổi payment_status hoặc thêm note
        # KHÔNG gửi khi config đã đóng (is_active = false)
        if important_changes:
            try:
                from erp.api.parent_portal.re_enrollment import _create_re_enrollment_announcement
                
                # Lấy thông tin config và năm học
                school_year = ""
                config_is_active = False
                try:
                    config_doc = frappe.get_doc("SIS Re-enrollment Config", submission.config_id)
                    config_is_active = config_doc.is_active
                    school_year_info = frappe.db.get_value(
                        "SIS School Year",
                        config_doc.school_year_id,
                        ["name_vn", "name_en"],
                        as_dict=True
                    )
                    if school_year_info:
                        school_year = school_year_info.name_vn or school_year_info.name_en or ""
                except:
                    pass
                
                # Chỉ gửi notification nếu config còn active
                if not config_is_active:
                    logs.append("Không gửi thông báo (kỳ tái ghi danh đã đóng)")
                else:
                    # Lấy answers từ submission để gửi vào announcement
                    answers_for_announcement = []
                    for answer in submission.answers:
                        answers_for_announcement.append({
                            'question_text_vn': answer.question_text_vn,
                            'question_text_en': answer.question_text_en,
                            'selected_options_text_vn': answer.selected_options_text_vn,
                            'selected_options_text_en': answer.selected_options_text_en
                        })
                    
                    _create_re_enrollment_announcement(
                        student_id=submission.student_id,
                        student_name=submission.student_name,
                        student_code=submission.student_code,
                        submission_data={
                            'decision': submission.decision,
                            'payment_type': submission.payment_type,
                            'discount_name': submission.selected_discount_name,
                            'discount_percent': submission.selected_discount_percent,
                            'discount_deadline': str(submission.selected_discount_deadline) if submission.selected_discount_deadline else None,
                            'reason': submission.not_re_enroll_reason,
                            'school_year': school_year,
                            'submitted_at': str(now()),
                            'status': submission.status or 'pending',
                            'answers': answers_for_announcement  # Câu trả lời khảo sát
                        },
                        is_update=True
                    )
                    logs.append(f"Đã gửi thông báo cập nhật cho phụ huynh (thay đổi: {', '.join(important_changes)})")
            except Exception as notif_err:
                logs.append(f"Lỗi gửi thông báo: {str(notif_err)}")
                frappe.logger().error(f"Error sending admin update notification: {str(notif_err)}")
        else:
            logs.append("Không gửi thông báo (chỉ thay đổi thanh toán/ghi chú)")
        
        return success_response(
            data={"name": submission.name},
            message="Cập nhật đơn thành công",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Admin Update Submission Error")
        return error_response(
            message=f"Lỗi khi cập nhật đơn: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def bulk_update_status():
    """
    Cập nhật trạng thái hàng loạt.
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền truy cập", logs=logs)
        
        # Lấy data
        if frappe.request.is_json:
            data = frappe.request.json or {}
        else:
            data = frappe.form_dict
        
        submission_ids = data.get('submission_ids', [])
        new_status = data.get('status')
        
        if isinstance(submission_ids, str):
            submission_ids = json.loads(submission_ids)
        
        if not submission_ids:
            return validation_error_response(
                "Thiếu danh sách đơn",
                {"submission_ids": ["Danh sách đơn là bắt buộc"]}
            )
        
        if not new_status or new_status not in ['pending', 'approved', 'rejected']:
            return validation_error_response(
                "Trạng thái không hợp lệ",
                {"status": ["Trạng thái phải là pending, approved hoặc rejected"]}
            )
        
        updated_count = 0
        for sub_id in submission_ids:
            try:
                submission = frappe.get_doc("SIS Re-enrollment", sub_id)
                submission.status = new_status
                submission.modified_by_admin = frappe.session.user
                submission.admin_modified_at = now()
                submission.save()
                updated_count += 1
            except Exception as e:
                logs.append(f"Lỗi cập nhật {sub_id}: {str(e)}")
        
        frappe.db.commit()
        
        logs.append(f"Đã cập nhật {updated_count}/{len(submission_ids)} đơn")
        
        return success_response(
            data={"updated_count": updated_count},
            message=f"Đã cập nhật {updated_count} đơn",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Admin Bulk Update Status Error")
        return error_response(
            message=f"Lỗi: {str(e)}",
            logs=logs
        )


# ==================== STATISTICS API ====================

@frappe.whitelist()
def get_statistics():
    """
    Lấy thống kê tái ghi danh.
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền truy cập", logs=logs)
        
        config_id = frappe.request.args.get('config_id')
        
        if not config_id:
            return validation_error_response(
                "Thiếu config_id",
                {"config_id": ["Config ID là bắt buộc"]}
            )
        
        # Thống kê theo quyết định
        decision_stats = frappe.db.sql("""
            SELECT 
                decision,
                COUNT(*) as count
            FROM `tabSIS Re-enrollment`
            WHERE config_id = %s
            GROUP BY decision
        """, config_id, as_dict=True)
        
        # Thống kê theo trạng thái
        status_stats = frappe.db.sql("""
            SELECT 
                status,
                COUNT(*) as count
            FROM `tabSIS Re-enrollment`
            WHERE config_id = %s
            GROUP BY status
        """, config_id, as_dict=True)
        
        # Thống kê theo phương thức thanh toán (chỉ cho những người tái ghi danh)
        payment_stats = frappe.db.sql("""
            SELECT 
                payment_type,
                COUNT(*) as count
            FROM `tabSIS Re-enrollment`
            WHERE config_id = %s AND decision = 're_enroll'
            GROUP BY payment_type
        """, config_id, as_dict=True)
        
        # Tổng số
        total = frappe.db.count("SIS Re-enrollment", {"config_id": config_id})
        
        # Lấy thông tin config
        config = frappe.db.get_value(
            "SIS Re-enrollment Config",
            config_id,
            ["title", "campus_id"],
            as_dict=True
        )
        
        # Số học sinh trong campus (để so sánh)
        if config:
            # Đếm số học sinh active trong campus
            total_students = frappe.db.sql("""
                SELECT COUNT(DISTINCT cs.student_id) as count
                FROM `tabSIS Class Student` cs
                INNER JOIN `tabSIS Class` c ON cs.class_id = c.name
                WHERE c.campus_id = %s
            """, config.campus_id, as_dict=True)[0].count
        else:
            total_students = 0
        
        # Chuyển đổi thành dict dễ sử dụng
        decision_dict = {item.decision: item.count for item in decision_stats if item.decision}
        status_dict = {item.status: item.count for item in status_stats}
        payment_dict = {item.payment_type: item.count for item in payment_stats if item.payment_type}
        
        # Đếm số chưa làm đơn (decision = NULL hoặc rỗng)
        not_submitted_count = frappe.db.sql("""
            SELECT COUNT(*) as count
            FROM `tabSIS Re-enrollment`
            WHERE config_id = %s AND (decision IS NULL OR decision = '')
        """, config_id, as_dict=True)[0].count
        
        # Đếm số yêu cầu điều chỉnh
        adjustment_requested_count = frappe.db.sql("""
            SELECT COUNT(*) as count
            FROM `tabSIS Re-enrollment`
            WHERE config_id = %s AND adjustment_status = 'requested'
        """, config_id, as_dict=True)[0].count
        
        logs.append(f"Thống kê cho config {config_id}")
        
        return success_response(
            data={
                "total_submissions": total,
                "total_students_in_campus": total_students,
                "not_submitted": not_submitted_count,
                "adjustment_requested": adjustment_requested_count,
                "by_decision": {
                    "re_enroll": decision_dict.get("re_enroll", 0),
                    "considering": decision_dict.get("considering", 0),
                    "not_re_enroll": decision_dict.get("not_re_enroll", 0)
                },
                "by_status": {
                    "pending": status_dict.get("pending", 0),
                    "approved": status_dict.get("approved", 0),
                    "rejected": status_dict.get("rejected", 0)
                },
                "by_payment_type": {
                    "annual": payment_dict.get("annual", 0),
                    "semester": payment_dict.get("semester", 0)
                }
            },
            message="Lấy thống kê thành công",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Admin Get Statistics Error")
        return error_response(
            message=f"Lỗi: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def export_submissions():
    """
    Export danh sách đơn ra CSV/Excel.
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền truy cập", logs=logs)
        
        config_id = frappe.request.args.get('config_id')
        
        if not config_id:
            return validation_error_response(
                "Thiếu config_id",
                {"config_id": ["Config ID là bắt buộc"]}
            )
        
        submissions = frappe.db.sql("""
            SELECT 
                re.student_code as 'Mã học sinh',
                re.student_name as 'Tên học sinh',
                re.current_class as 'Lớp hiện tại',
                re.guardian_name as 'Phụ huynh',
                CASE re.decision 
                    WHEN 're_enroll' THEN 'Tái ghi danh'
                    WHEN 'not_re_enroll' THEN 'Không tái ghi danh'
                END as 'Quyết định',
                CASE re.payment_type
                    WHEN 'annual' THEN 'Đóng theo năm'
                    WHEN 'semester' THEN 'Đóng theo kỳ'
                    ELSE ''
                END as 'Phương thức thanh toán',
                re.not_re_enroll_reason as 'Lý do không tái ghi danh',
                CASE re.status
                    WHEN 'pending' THEN 'Chờ xử lý'
                    WHEN 'approved' THEN 'Đã duyệt'
                    WHEN 'rejected' THEN 'Từ chối'
                END as 'Trạng thái',
                DATE_FORMAT(re.submitted_at, '%%d/%%m/%%Y %%H:%%i') as 'Ngày nộp'
            FROM `tabSIS Re-enrollment` re
            WHERE re.config_id = %s
            ORDER BY re.student_name ASC
        """, config_id, as_dict=True)
        
        logs.append(f"Export {len(submissions)} đơn")
        
        return success_response(
            data={"items": submissions},
            message=f"Xuất {len(submissions)} đơn thành công",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Admin Export Submissions Error")
        return error_response(
            message=f"Lỗi: {str(e)}",
            logs=logs
        )


# ==================== UPLOAD PDF API ====================

@frappe.whitelist(allow_guest=False, methods=['POST'])
def upload_service_document():
    """
    Upload file PDF dịch vụ học sinh và convert sang ảnh.
    
    POST body (multipart/form-data):
    {
        "config_id": "SIS-REENROLL-CFG-00001" (optional - nếu muốn update config sau khi upload),
        "file": <PDF file>
    }
    
    Trả về:
    {
        "success": true,
        "data": {
            "file_url": "/files/...",
            "custom_name": "re-enrollment-xxxx",
            "images": ["url1", "url2", ...]
        }
    }
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền truy cập", logs=logs)
        
        # Lấy config_id nếu có
        data = frappe.request.form
        config_id = data.get('config_id')
        
        logs.append(f"Upload PDF cho config: {config_id or 'new'}")
        
        # Kiểm tra có file không
        if not frappe.request.files:
            return validation_error_response(
                "Thiếu file PDF",
                {"file": ["Vui lòng chọn file PDF để upload"]}
            )
        
        # Lấy file từ request
        file_obj = None
        for file_key, f in frappe.request.files.items():
            if file_key == 'file':
                file_obj = f
                break
        
        if not file_obj:
            return validation_error_response(
                "Thiếu file PDF",
                {"file": ["Vui lòng chọn file PDF để upload"]}
            )
        
        # Kiểm tra file là PDF
        filename = file_obj.filename
        if not filename.lower().endswith('.pdf'):
            return validation_error_response(
                "Chỉ chấp nhận file PDF",
                {"file": ["Vui lòng upload file có định dạng PDF"]}
            )
        
        logs.append(f"File: {filename}")
        
        # Đọc nội dung file
        file_content = file_obj.stream.read()
        file_obj.stream.seek(0)  # Reset để có thể đọc lại
        
        # Tạo custom name unique
        custom_name = f"re-enrollment-{uuid.uuid4().hex[:8]}"
        
        logs.append(f"Custom name: {custom_name}")
        
        # 1. Lưu file vào Frappe
        file_doc = frappe.get_doc({
            "doctype": "File",
            "file_name": filename,
            "folder": "Home/Attachments",
            "content": file_content,
            "is_private": 0  # Public để dễ truy cập
        })
        file_doc.insert(ignore_permissions=True)
        frappe.db.commit()
        
        file_url = file_doc.file_url
        logs.append(f"Saved file: {file_url}")
        
        # 2. Gọi PDF Service để convert sang ảnh
        images = []
        try:
            # Upload file đến pdf-service
            pdf_service_url = frappe.conf.get("pdf_service_url", "http://172.16.20.113:5020")
            
            # Reset stream để upload
            file_obj.stream.seek(0)
            
            upload_response = requests.post(
                f"{pdf_service_url}/api/pdfs/upload-pdf",
                files={"pdfFile": (filename, file_obj.stream, "application/pdf")},
                data={"customName": custom_name, "uploader": frappe.session.user},
                timeout=120  # 2 phút cho convert
            )
            
            if upload_response.status_code == 200:
                upload_result = upload_response.json()
                logs.append(f"PDF Service upload: {json.dumps(upload_result)}")
                
                # Lấy danh sách ảnh
                images_response = requests.get(
                    f"{pdf_service_url}/api/pdfs/get-images/{custom_name}",
                    timeout=30
                )
                
                if images_response.status_code == 200:
                    images_result = images_response.json()
                    images = images_result.get("images", [])
                    logs.append(f"Got {len(images)} images from PDF")
                else:
                    logs.append(f"Failed to get images: {images_response.status_code}")
            else:
                logs.append(f"PDF Service error: {upload_response.status_code} - {upload_response.text}")
                
        except requests.exceptions.RequestException as e:
            # PDF service không chạy hoặc lỗi mạng
            logs.append(f"PDF Service unavailable: {str(e)}")
            # Không throw lỗi, vẫn lưu file nhưng không có ảnh
        
        # 3. Nếu có config_id, update config
        if config_id and frappe.db.exists("SIS Re-enrollment Config", config_id):
            config_doc = frappe.get_doc("SIS Re-enrollment Config", config_id)
            config_doc.service_document = file_url
            config_doc.service_document_images = json.dumps(images) if images else None
            config_doc.save()
            frappe.db.commit()
            logs.append(f"Updated config {config_id}")
        
        return success_response(
            data={
                "file_url": file_url,
                "custom_name": custom_name,
                "images": images,
                "image_count": len(images)
            },
            message=f"Upload thành công, đã convert thành {len(images)} ảnh" if images else "Upload thành công (chưa convert ảnh)",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Upload Service Document Error")
        return error_response(
            message=f"Lỗi khi upload file: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def get_service_document_images(config_id=None):
    """
    Lấy danh sách ảnh từ service document của một config.
    """
    logs = []
    
    try:
        if not config_id:
            config_id = frappe.request.args.get('config_id')
        
        if not config_id:
            return validation_error_response(
                "Thiếu config_id",
                {"config_id": ["Config ID là bắt buộc"]}
            )
        
        if not frappe.db.exists("SIS Re-enrollment Config", config_id):
            return not_found_response("Không tìm thấy cấu hình")
        
        config = frappe.get_doc("SIS Re-enrollment Config", config_id)
        
        images = []
        if config.service_document_images:
            try:
                images = json.loads(config.service_document_images)
            except:
                images = []
        
        return success_response(
            data={
                "service_document": config.service_document,
                "images": images,
                "image_count": len(images)
            },
            message="Lấy danh sách ảnh thành công",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        return error_response(
            message=f"Lỗi: {str(e)}",
            logs=logs
        )


# ==================== SYNC STUDENTS API ====================

@frappe.whitelist(allow_guest=False, methods=['POST'])
def sync_students():
    """
    Đồng bộ danh sách học sinh cho một config tái ghi danh.
    Tạo records cho học sinh mới chưa có trong danh sách.
    
    POST body:
    {
        "config_id": "SIS-REENROLL-CFG-00001"
    }
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền truy cập", logs=logs)
        
        # Lấy data từ request
        if frappe.request.is_json:
            data = frappe.request.json or {}
        else:
            data = frappe.form_dict
        
        config_id = data.get('config_id')
        
        if not config_id:
            return validation_error_response(
                "Thiếu config_id",
                {"config_id": ["Config ID là bắt buộc"]}
            )
        
        # Lấy thông tin config
        if not frappe.db.exists("SIS Re-enrollment Config", config_id):
            return not_found_response("Không tìm thấy cấu hình")
        
        config = frappe.get_doc("SIS Re-enrollment Config", config_id)
        
        # Có thể override finance_year_id từ request
        finance_year_id = data.get('finance_year_id') or getattr(config, 'finance_year_id', None)
        
        logs.append(f"Sync students cho config: {config_id}")
        logs.append(f"Source school year: {config.source_school_year_id}, Campus: {config.campus_id}")
        if finance_year_id:
            logs.append(f"Finance Year: {finance_year_id}")
        
        # Gọi hàm auto-create với năm học nguồn hoặc năm tài chính
        result = _auto_create_student_records(
            config_id,
            config.source_school_year_id,  # Dùng năm học nguồn để lấy danh sách học sinh
            config.campus_id,
            logs,
            finance_year_id=finance_year_id  # Nếu có thì lấy từ Finance Year
        )
        
        created_count = result.get("created_count", 0)
        deleted_count = result.get("deleted_count", 0)
        
        # Tạo message phù hợp
        messages = []
        if created_count > 0:
            messages.append(f"Tạo thêm {created_count} đơn mới")
        if deleted_count > 0:
            messages.append(f"Xóa {deleted_count} học sinh lớp 12 (chưa submit)")
        
        message = "Đã đồng bộ thành công. " + ", ".join(messages) if messages else "Danh sách đã đồng bộ, không có thay đổi."
        
        return success_response(
            data={
                "created_count": created_count,
                "deleted_count": deleted_count,
                "config_id": config_id
            },
            message=message,
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Sync Students Error")
        return error_response(
            message=f"Lỗi khi đồng bộ: {str(e)}",
            logs=logs
        )


@frappe.whitelist(allow_guest=False, methods=['POST'])
def update_submission_decision():
    """
    Cập nhật quyết định cho một đơn tái ghi danh.
    Cho phép switch giữa các trạng thái: re_enroll, considering, not_re_enroll
    
    POST body:
    {
        "submission_id": "SIS-REENROLL-00001",
        "decision": "re_enroll" | "considering" | "not_re_enroll",
        "payment_type": "annual" | "semester" (required nếu decision = re_enroll),
        "selected_discount_id": "...", (optional - ID ưu đãi đã chọn nếu re_enroll),
        "reason": "..." (required nếu decision = considering hoặc not_re_enroll)
    }
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền truy cập", logs=logs)
        
        # Lấy data từ request
        if frappe.request.is_json:
            data = frappe.request.json or {}
        else:
            data = frappe.form_dict
        
        submission_id = data.get('submission_id') or data.get('name')
        decision = data.get('decision')
        
        if not submission_id:
            return validation_error_response(
                "Thiếu submission_id",
                {"submission_id": ["Submission ID là bắt buộc"]}
            )
        
        if not decision or decision not in ['re_enroll', 'considering', 'not_re_enroll']:
            return validation_error_response(
                "Decision không hợp lệ",
                {"decision": ["Phải là re_enroll, considering hoặc not_re_enroll"]}
            )
        
        # Lấy submission
        if not frappe.db.exists("SIS Re-enrollment", submission_id):
            return not_found_response("Không tìm thấy đơn tái ghi danh")
        
        submission = frappe.get_doc("SIS Re-enrollment", submission_id)
        
        # Lưu decision cũ để tạo log
        old_decision = submission.decision
        
        logs.append(f"Update decision cho {submission_id}: {submission.decision} -> {decision}")
        
        # Validate theo loại decision
        if decision == 're_enroll':
            payment_type = data.get('payment_type')
            if not payment_type or payment_type not in ['annual', 'semester']:
                return validation_error_response(
                    "Thiếu phương thức thanh toán",
                    {"payment_type": ["Vui lòng chọn đóng theo năm hoặc theo kỳ"]}
                )
            
            submission.decision = decision
            submission.payment_type = payment_type
            submission.selected_discount_deadline = data.get('selected_discount_deadline')
            submission.not_re_enroll_reason = None  # Clear reason nếu đổi sang re_enroll
            
        else:  # considering hoặc not_re_enroll
            reason = data.get('reason') or data.get('not_re_enroll_reason')
            if not reason:
                return validation_error_response(
                    "Thiếu lý do",
                    {"reason": ["Vui lòng nhập lý do"]}
                )
            
            submission.decision = decision
            submission.not_re_enroll_reason = reason
            submission.payment_type = None  # Clear payment nếu không re_enroll
            submission.selected_discount_deadline = None
        
        # Ghi nhận thời gian submit nếu lần đầu có decision
        if not submission.submitted_at:
            submission.submitted_at = now()
        
        # Tạo log hệ thống về thay đổi decision
        decision_map = {
            're_enroll': 'Tái ghi danh',
            'considering': 'Cân nhắc', 
            'not_re_enroll': 'Không tái ghi danh'
        }
        current_user = frappe.session.user
        current_user_name = frappe.db.get_value("User", current_user, "full_name") or current_user
        
        old_display = decision_map.get(old_decision, old_decision or 'Chưa có')
        new_display = decision_map.get(decision, decision)
        
        log_content = f"Admin {current_user_name} đã cập nhật quyết định:\n• Quyết định: {old_display} → {new_display}"
        
        submission.append("notes", {
            "note_type": "system_log",
            "note": log_content,
            "created_by_user": current_user,
            "created_by_name": current_user_name,
            "created_at": now()
        })
        
        # Ghi nhận admin sửa
        submission.modified_by_admin = frappe.session.user
        submission.admin_modified_at = now()
        
        submission.save()
        frappe.db.commit()
        
        logs.append(f"Đã cập nhật decision thành công")
        
        # Gửi thông báo cho phụ huynh về việc cập nhật quyết định
        # Gửi thông báo nếu config còn active
        try:
            from erp.api.parent_portal.re_enrollment import _create_re_enrollment_announcement
            
            # Lấy thông tin config và năm học
            school_year = ""
            config_is_active = False
            try:
                config_doc = frappe.get_doc("SIS Re-enrollment Config", submission.config_id)
                config_is_active = config_doc.is_active
                school_year_info = frappe.db.get_value(
                    "SIS School Year",
                    config_doc.school_year_id,
                    ["name_vn", "name_en"],
                    as_dict=True
                )
                if school_year_info:
                    school_year = school_year_info.name_vn or school_year_info.name_en or ""
            except:
                pass
            
            # Chỉ gửi notification nếu config còn active
            if not config_is_active:
                logs.append("Không gửi thông báo (kỳ tái ghi danh đã đóng)")
            else:
                # Lấy answers từ submission để gửi vào announcement
                answers_for_announcement = []
                for answer in submission.answers:
                    answers_for_announcement.append({
                        'question_text_vn': answer.question_text_vn,
                        'question_text_en': answer.question_text_en,
                        'selected_options_text_vn': answer.selected_options_text_vn,
                        'selected_options_text_en': answer.selected_options_text_en
                    })
                
                _create_re_enrollment_announcement(
                    student_id=submission.student_id,
                    student_name=submission.student_name,
                    student_code=submission.student_code,
                    submission_data={
                        'decision': submission.decision,
                        'payment_type': submission.payment_type,
                        'discount_name': submission.selected_discount_name,
                        'discount_percent': submission.selected_discount_percent,
                        'discount_deadline': str(submission.selected_discount_deadline) if submission.selected_discount_deadline else None,
                        'reason': submission.not_re_enroll_reason,
                        'school_year': school_year,
                        'submitted_at': str(now()),
                        'status': submission.status or 'pending',
                        'answers': answers_for_announcement  # Câu trả lời khảo sát
                    },
                    is_update=True
                )
                logs.append("Đã gửi thông báo cập nhật quyết định cho phụ huynh")
        except Exception as notif_err:
            logs.append(f"Lỗi gửi thông báo: {str(notif_err)}")
            frappe.logger().error(f"Error sending decision update notification: {str(notif_err)}")
        
        return success_response(
            data={
                "name": submission.name,
                "decision": submission.decision,
                "payment_type": submission.payment_type,
                "reason": submission.not_re_enroll_reason
            },
            message="Cập nhật quyết định thành công",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Update Submission Decision Error")
        return error_response(
            message=f"Lỗi: {str(e)}",
            logs=logs
        )


# ==================== SEND REMINDER NOTIFICATION API ====================

@frappe.whitelist(allow_guest=False, methods=['POST'])
def send_reminder_notification():
    """
    Gửi push notification nhắc phụ huynh làm đơn tái ghi danh.
    
    POST body:
    {
        "submission_ids": ["SIS-REENROLL-00001", ...],  # Danh sách ID đơn cần nhắc
        "message": "Nội dung tin nhắn tùy chỉnh"       # Nội dung do user nhập
    }
    
    Trả về:
    {
        "success": true,
        "data": {
            "success_count": 10,
            "failed_count": 2,
            "total_students": 12
        }
    }
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền truy cập", logs=logs)
        
        # Lấy data từ request
        if frappe.request.is_json:
            data = frappe.request.json or {}
        else:
            data = frappe.form_dict
        
        submission_ids = data.get('submission_ids', [])
        message = data.get('message', '')
        
        if isinstance(submission_ids, str):
            submission_ids = json.loads(submission_ids)
        
        if not submission_ids:
            return validation_error_response(
                "Thiếu danh sách đơn",
                {"submission_ids": ["Danh sách đơn là bắt buộc"]}
            )
        
        if not message or not message.strip():
            return validation_error_response(
                "Thiếu nội dung tin nhắn",
                {"message": ["Nội dung tin nhắn là bắt buộc"]}
            )
        
        # Giới hạn độ dài message (150 ký tự để hiển thị tốt trên mobile)
        message = message.strip()[:150]
        
        logs.append(f"Gửi nhắc nhở cho {len(submission_ids)} đơn")
        logs.append(f"Message: {message}")
        
        # Lấy danh sách student_id từ submission_ids
        student_ids = []
        for sub_id in submission_ids:
            student_id = frappe.db.get_value("SIS Re-enrollment", sub_id, "student_id")
            if student_id:
                student_ids.append(student_id)
        
        if not student_ids:
            return error_response("Không tìm thấy học sinh nào", logs=logs)
        
        logs.append(f"Tìm thấy {len(student_ids)} học sinh")
        
        # Gửi push notification
        try:
            from erp.utils.notification_handler import send_bulk_parent_notifications
            
            # Sử dụng notification_type = "reminder" (là giá trị hợp lệ trong ERP Notification)
            result = send_bulk_parent_notifications(
                recipient_type="reminder",
                recipients_data={
                    "student_ids": student_ids
                },
                title="Tái ghi danh",
                body=message,
                icon="/icon.png",
                data={
                    "type": "reminder",
                    "subtype": "re_enrollment",
                    "url": "/re-enrollment"  # URL trên parent-portal
                }
            )
            
            logs.append(f"Kết quả gửi: {result}")
            
            return success_response(
                data={
                    "success_count": result.get("success_count", 0),
                    "failed_count": result.get("failed_count", 0),
                    "total_students": len(student_ids),
                    "total_parents": result.get("total_parents", 0)
                },
                message=f"Đã gửi thông báo đến {result.get('success_count', 0)} phụ huynh",
                logs=logs
            )
            
        except Exception as notif_err:
            logs.append(f"Lỗi gửi notification: {str(notif_err)}")
            frappe.log_error(frappe.get_traceback(), "Send Re-enrollment Reminder Error")
            return error_response(
                message=f"Lỗi khi gửi thông báo: {str(notif_err)}",
                logs=logs
            )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Send Reminder Notification Error")
        return error_response(
            message=f"Lỗi: {str(e)}",
            logs=logs
        )


# ==================== IMPORT/EXPORT DECISION EXCEL APIs ====================

@frappe.whitelist(allow_guest=False, methods=['GET'])
def export_decision_template(config_id=None):
    """
    Xuất file Excel mẫu để import quyết định tái ghi danh.
    File Excel gồm:
    - Sheet 1: Danh sách học sinh với các cột cần điền
    - Sheet 2: Hướng dẫn với các giá trị hợp lệ
    
    GET params:
        config_id: ID của đợt tái ghi danh
    
    Returns:
        File Excel (.xlsx)
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền truy cập", logs=logs)
        
        if not config_id:
            config_id = frappe.request.args.get('config_id')
        
        if not config_id:
            return validation_error_response(
                "Thiếu config_id",
                {"config_id": ["Config ID là bắt buộc"]}
            )
        
        # Kiểm tra config tồn tại
        if not frappe.db.exists("SIS Re-enrollment Config", config_id):
            return not_found_response("Không tìm thấy cấu hình tái ghi danh")
        
        config = frappe.get_doc("SIS Re-enrollment Config", config_id)
        logs.append(f"Xuất template cho config: {config.title}")
        
        # Lấy danh sách học sinh từ config
        submissions = frappe.get_all(
            "SIS Re-enrollment",
            filters={"config_id": config_id},
            fields=["name", "student_code", "student_name", "current_class", "decision", "selected_discount_id"],
            order_by="student_code asc"
        )
        
        logs.append(f"Số học sinh: {len(submissions)}")
        
        # Lấy bảng ưu đãi
        discounts = frappe.get_all(
            "SIS Re-enrollment Discount",
            filters={"parent": config_id},
            fields=["name", "deadline", "description", "annual_discount", "semester_discount"],
            order_by="deadline asc"
        )
        
        # Lấy danh sách câu hỏi khảo sát từ config
        import json as json_lib
        questions = []
        config_doc = frappe.get_doc("SIS Re-enrollment Config", config_id)
        if hasattr(config_doc, 'questions') and config_doc.questions:
            for q in config_doc.questions:
                # Options được lưu trong options_json (JSON string)
                options = []
                if q.options_json:
                    try:
                        options_data = json_lib.loads(q.options_json) if isinstance(q.options_json, str) else q.options_json
                        for idx, opt in enumerate(options_data, 1):
                            options.append({
                                "idx": idx,
                                "name": opt.get('name') or f"opt_{idx}",
                                "option_vn": opt.get('option_vn') or opt.get('text_vn') or '',
                                "option_en": opt.get('option_en') or opt.get('text_en') or ''
                            })
                    except Exception as e:
                        logs.append(f"Lỗi parse options_json: {str(e)}")
                questions.append({
                    "name": q.name,
                    "question_vn": q.question_vn,
                    "question_en": q.question_en,
                    "question_type": q.question_type,  # single_choice / multiple_choice
                    "is_required": q.is_required,
                    "options": options
                })
        logs.append(f"Số câu hỏi khảo sát: {len(questions)}")
        
        # Tạo file Excel
        import pandas as pd
        from io import BytesIO
        import json
        
        # Mapping decision sang tiếng Việt
        decision_map = {
            're_enroll': 'Tái ghi danh',
            'considering': 'Cân nhắc', 
            'not_re_enroll': 'Không tái ghi danh'
        }
        
        # Mapping payment_type sang tiếng Việt
        payment_type_map = {
            'annual': 'Theo năm',
            'semester': 'Theo kỳ'
        }
        
        # Tạo mapping từ discount_id sang deadline (format dd/mm/yyyy)
        discount_deadline_map = {}
        for d in discounts:
            if d.deadline:
                # Format: dd/mm/yyyy
                deadline_str = d.deadline.strftime('%d/%m/%Y') if hasattr(d.deadline, 'strftime') else str(d.deadline)
                discount_deadline_map[d.name] = deadline_str
        
        # Lấy thêm thông tin payment_type từ submissions (bao gồm cả answers)
        submissions_full = frappe.get_all(
            "SIS Re-enrollment",
            filters={"config_id": config_id},
            fields=["name", "student_code", "student_name", "current_class", "decision", "selected_discount_id", "payment_type"],
            order_by="student_code asc"
        )
        
        # Lấy câu trả lời của tất cả học sinh
        # Tạo dict: submission_id -> {question_id -> selected_options_indices}
        answers_map = {}
        for sub in submissions_full:
            sub_doc = frappe.get_doc("SIS Re-enrollment", sub.name)
            if hasattr(sub_doc, 'answers') and sub_doc.answers:
                answers_map[sub.name] = {}
                for ans in sub_doc.answers:
                    # Parse selected_options JSON để lấy các option đã chọn
                    selected_indices = []
                    if ans.selected_options:
                        try:
                            selected_opts = json.loads(ans.selected_options) if isinstance(ans.selected_options, str) else ans.selected_options
                            # selected_opts có thể là list các option_name hoặc option_idx
                            # Tìm index từ câu hỏi tương ứng
                            q_match = next((q for q in questions if q['name'] == ans.question_id), None)
                            if q_match:
                                for sel in selected_opts:
                                    # Tìm idx của option đã chọn
                                    for opt in q_match['options']:
                                        if opt['name'] == sel or str(opt['idx']) == str(sel):
                                            selected_indices.append(str(opt['idx']))
                                            break
                        except:
                            pass
                    answers_map[sub.name][ans.question_id] = selected_indices
        
        # Lấy thêm thông tin not_re_enroll_reason từ submissions
        submissions_with_reason = frappe.get_all(
            "SIS Re-enrollment",
            filters={"config_id": config_id},
            fields=["name", "student_code", "student_name", "current_class", "decision", "selected_discount_id", "payment_type", "not_re_enroll_reason"],
            order_by="student_code asc"
        )
        
        # Sheet 1: Danh sách học sinh - dùng tên cột tiếng Việt thân thiện
        students_data = []
        for sub in submissions_with_reason:
            # Chuyển decision sang tiếng Việt
            decision_vn = decision_map.get(sub.decision, '') if sub.decision else ''
            # Chuyển discount_id sang deadline
            discount_deadline = discount_deadline_map.get(sub.selected_discount_id, '') if sub.selected_discount_id else ''
            # Chuyển payment_type sang tiếng Việt
            payment_type_vn = payment_type_map.get(sub.payment_type, '') if sub.payment_type else ''
            
            row_data = {
                "Mã học sinh": sub.student_code or "",
                "Họ tên": sub.student_name or "",
                "Lớp": sub.current_class or "",
                "Quyết định": decision_vn,
                "Ưu đãi (hạn đóng)": discount_deadline,
                "Đóng theo": payment_type_vn,
                "Lý do": sub.not_re_enroll_reason or ""  # Lý do cho Cân nhắc / Không tái ghi danh
            }
            
            # Thêm cột cho mỗi câu hỏi khảo sát (chỉ khi Tái ghi danh)
            for q in questions:
                col_name = q['question_vn']
                # Lấy câu trả lời hiện có (nếu có)
                answer_indices = answers_map.get(sub.name, {}).get(q['name'], [])
                # Format: "1" hoặc "1,2,3" cho multiple choice
                row_data[col_name] = ",".join(answer_indices) if answer_indices else ""
            
            students_data.append(row_data)
        
        df_students = pd.DataFrame(students_data)
        
        # Sheet 2: Hướng dẫn
        guide_data = [
            {"Cột": "Mã học sinh", "Mô tả": "Mã học sinh (KHÔNG ĐƯỢC SỬA)", "Giá trị hợp lệ": "Giữ nguyên"},
            {"Cột": "Họ tên", "Mô tả": "Tên học sinh (chỉ để tham khảo)", "Giá trị hợp lệ": "Không cần điền"},
            {"Cột": "Lớp", "Mô tả": "Lớp hiện tại (chỉ để tham khảo)", "Giá trị hợp lệ": "Không cần điền"},
            {"Cột": "Quyết định", "Mô tả": "Quyết định tái ghi danh (BẮT BUỘC)", "Giá trị hợp lệ": "Tái ghi danh | Cân nhắc | Không tái ghi danh"},
            {"Cột": "Ưu đãi (hạn đóng)", "Mô tả": "Hạn đóng tiền để hưởng ưu đãi (BẮT BUỘC nếu Tái ghi danh)", "Giá trị hợp lệ": "Xem bảng ưu đãi bên dưới (điền ngày VD: 05/02/2026)"},
            {"Cột": "Đóng theo", "Mô tả": "Đóng tiền theo năm hay theo kỳ (BẮT BUỘC nếu Tái ghi danh)", "Giá trị hợp lệ": "Theo năm | Theo kỳ"},
            {"Cột": "Lý do", "Mô tả": "Lý do (BẮT BUỘC nếu Cân nhắc hoặc Không tái ghi danh)", "Giá trị hợp lệ": "Điền lý do tự do"},
        ]
        # Thêm hướng dẫn cho các cột câu hỏi khảo sát
        for q in questions:
            q_type_desc = "Chọn một số (1,2,3,...)" if q['question_type'] == 'single_choice' else "Chọn nhiều số, cách nhau bằng dấu phẩy (VD: 1,2,3)"
            required_text = " (BẮT BUỘC nếu Tái ghi danh)" if q['is_required'] else " (không bắt buộc)"
            guide_data.append({
                "Cột": q['question_vn'],
                "Mô tả": f"Câu hỏi khảo sát{required_text}",
                "Giá trị hợp lệ": f"{q_type_desc} - Xem bảng đáp án bên dưới"
            })
        df_guide = pd.DataFrame(guide_data)
        
        # Sheet 3: Danh sách ưu đãi - hiển thị rõ ràng hơn
        discounts_data = []
        for d in discounts:
            deadline_str = ""
            if d.deadline:
                deadline_str = d.deadline.strftime('%d/%m/%Y') if hasattr(d.deadline, 'strftime') else str(d.deadline)
            discounts_data.append({
                "Hạn đóng (điền vào cột Ưu đãi)": deadline_str,
                "Mô tả": d.description or "",
                "Giảm giá theo năm (%)": d.annual_discount or 0,
                "Giảm giá theo kỳ (%)": d.semester_discount or 0
            })
        df_discounts = pd.DataFrame(discounts_data) if discounts_data else pd.DataFrame(columns=["Hạn đóng (điền vào cột Ưu đãi)", "Mô tả", "Giảm giá theo năm (%)", "Giảm giá theo kỳ (%)"])
        
        # Sheet 4: Danh sách đáp án câu hỏi khảo sát
        questions_data = []
        for q in questions:
            q_type_text = "Chọn 1" if q['question_type'] == 'single_choice' else "Chọn nhiều"
            required_text = "Bắt buộc" if q['is_required'] else "Không bắt buộc"
            
            # Dòng header cho mỗi câu hỏi
            questions_data.append({
                "Câu hỏi": q['question_vn'],
                "Số đáp án": "",
                "Nội dung đáp án": f"[{q_type_text}] [{required_text}]"
            })
            # Liệt kê các đáp án
            for opt in q['options']:
                questions_data.append({
                    "Câu hỏi": "",
                    "Số đáp án": opt['idx'],
                    "Nội dung đáp án": opt['option_vn']
                })
            # Dòng trống phân cách
            questions_data.append({"Câu hỏi": "", "Số đáp án": "", "Nội dung đáp án": ""})
        
        df_questions = pd.DataFrame(questions_data) if questions_data else pd.DataFrame(columns=["Câu hỏi", "Số đáp án", "Nội dung đáp án"])
        
        # Ghi file Excel
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_students.to_excel(writer, sheet_name='Danh sách học sinh', index=False)
            df_guide.to_excel(writer, sheet_name='Hướng dẫn', index=False)
            df_discounts.to_excel(writer, sheet_name='Danh sách ưu đãi', index=False)
            if questions:
                df_questions.to_excel(writer, sheet_name='Đáp án câu hỏi', index=False)
        
        output.seek(0)
        
        # Trả về file Excel
        frappe.local.response.filename = f"re_enrollment_template_{config_id}.xlsx"
        frappe.local.response.filecontent = output.getvalue()
        frappe.local.response.type = "binary"
        
        logs.append("Xuất file thành công")
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Export Decision Template Error")
        return error_response(
            message=f"Lỗi khi xuất file: {str(e)}",
            logs=logs
        )


@frappe.whitelist(allow_guest=False, methods=['POST'])
def import_decision_from_excel():
    """
    Import quyết định tái ghi danh từ file Excel.
    KHÔNG gửi notification đến phụ huynh.
    
    POST body (form-data):
        file: File Excel (.xlsx, .xls)
        config_id: ID của đợt tái ghi danh
    
    File Excel cần có các cột:
        - student_code: Mã học sinh (BẮT BUỘC)
        - decision: Quyết định (BẮT BUỘC): re_enroll | considering | not_re_enroll
        - selected_discount_id: ID ưu đãi (BẮT BUỘC nếu decision = re_enroll)
    
    Returns:
        {
            "success_count": 10,
            "error_count": 2,
            "total_count": 12,
            "errors": [{"row": 3, "error": "...", "data": {...}}]
        }
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền truy cập", logs=logs)
        
        # Lấy file từ request
        files = frappe.request.files
        if 'file' not in files:
            return validation_error_response(
                "Thiếu file",
                {"file": ["File Excel là bắt buộc"]}
            )
        
        file = files['file']
        config_id = frappe.form_dict.get('config_id') or frappe.request.form.get('config_id')
        
        if not config_id:
            return validation_error_response(
                "Thiếu config_id",
                {"config_id": ["Config ID là bắt buộc"]}
            )
        
        # Kiểm tra config tồn tại
        if not frappe.db.exists("SIS Re-enrollment Config", config_id):
            return not_found_response("Không tìm thấy cấu hình tái ghi danh")
        
        logs.append(f"Import quyết định cho config: {config_id}")
        
        # Lấy danh sách ưu đãi với đầy đủ thông tin
        discounts = frappe.get_all(
            "SIS Re-enrollment Discount",
            filters={"parent": config_id},
            fields=["name", "deadline", "description", "annual_discount", "semester_discount"]
        )
        valid_discount_ids = [d.name for d in discounts]
        
        # Tạo mapping từ deadline (nhiều format) sang discount_id
        deadline_to_discount = {}
        for d in discounts:
            if d.deadline:
                # Format chuẩn: yyyy-mm-dd
                deadline_str = str(d.deadline)
                deadline_to_discount[deadline_str] = d.name
                
                # Format dd/mm/yyyy
                try:
                    from datetime import datetime
                    date_obj = datetime.strptime(deadline_str, '%Y-%m-%d')
                    deadline_to_discount[date_obj.strftime('%d/%m/%Y')] = d.name
                    deadline_to_discount[date_obj.strftime('%d-%m-%Y')] = d.name
                except:
                    pass
        
        logs.append(f"Ưu đãi hợp lệ: {valid_discount_ids}")
        logs.append(f"Deadline mapping: {list(deadline_to_discount.keys())}")
        
        # Lấy danh sách student_code trong config
        valid_students = {
            s.student_code: s.name
            for s in frappe.get_all(
                "SIS Re-enrollment",
                filters={"config_id": config_id},
                fields=["name", "student_code"]
            )
        }
        logs.append(f"Số học sinh trong config: {len(valid_students)}")
        
        # Lấy danh sách câu hỏi khảo sát từ config
        import json
        questions = []
        config_doc = frappe.get_doc("SIS Re-enrollment Config", config_id)
        if hasattr(config_doc, 'questions') and config_doc.questions:
            for q in config_doc.questions:
                options = []
                # Options được lưu trong options_json (JSON string)
                if q.options_json:
                    try:
                        options_data = json.loads(q.options_json) if isinstance(q.options_json, str) else q.options_json
                        for idx, opt in enumerate(options_data, 1):
                            options.append({
                                "idx": idx,
                                "name": opt.get('name') or f"opt_{idx}",
                                "option_vn": opt.get('option_vn') or opt.get('text_vn') or '',
                                "option_en": opt.get('option_en') or opt.get('text_en') or ''
                            })
                    except Exception as e:
                        logs.append(f"Lỗi parse options_json cho câu hỏi '{q.question_vn}': {str(e)}")
                questions.append({
                    "name": q.name,
                    "question_vn": q.question_vn,
                    "question_en": q.question_en,
                    "question_type": q.question_type,
                    "is_required": q.is_required,
                    "options": options
                })
        logs.append(f"Số câu hỏi khảo sát: {len(questions)}")
        
        # Đọc file Excel
        import pandas as pd
        df = pd.read_excel(file)
        
        # Mapping tên cột tiếng Việt sang tên cột chuẩn
        column_mapping = {
            'Mã học sinh': 'student_code',
            'mã học sinh': 'student_code',
            'Họ tên': 'student_name',
            'họ tên': 'student_name',
            'Lớp': 'current_class',
            'lớp': 'current_class',
            'Quyết định': 'decision',
            'quyết định': 'decision',
            'Ưu đãi (hạn đóng)': 'discount_deadline',
            'ưu đãi (hạn đóng)': 'discount_deadline',
            'Ưu đãi': 'discount_deadline',
            'ưu đãi': 'discount_deadline',
            'selected_discount_id': 'discount_deadline',  # Hỗ trợ cả tên cột cũ
            'Đóng theo': 'payment_type',
            'đóng theo': 'payment_type',
            'Đóng Theo': 'payment_type',
            'Lý do': 'reason',
            'lý do': 'reason',
            'Ly do': 'reason',
            'reason': 'reason',
        }
        df = df.rename(columns=column_mapping)
        
        # Mapping payment_type từ tiếng Việt sang giá trị chuẩn
        payment_type_mapping = {
            'theo năm': 'annual',
            'theo nam': 'annual',
            'năm': 'annual',
            'nam': 'annual',
            'annual': 'annual',
            'theo kỳ': 'semester',
            'theo ky': 'semester',
            'kỳ': 'semester',
            'ky': 'semester',
            'semester': 'semester',
        }
        
        logs.append(f"Columns sau rename: {list(df.columns)}")
        
        # Kiểm tra có cột student_code và decision không
        if 'student_code' not in df.columns:
            return validation_error_response(
                "File thiếu cột Mã học sinh",
                {"file": ["Cần có cột 'Mã học sinh' hoặc 'student_code'"]}
            )
        if 'decision' not in df.columns:
            return validation_error_response(
                "File thiếu cột Quyết định",
                {"file": ["Cần có cột 'Quyết định' hoặc 'decision'"]}
            )
        
        # Mapping decision từ tiếng Việt sang giá trị chuẩn
        decision_mapping = {
            # Tiếng Việt
            'tái ghi danh': 're_enroll',
            'tai ghi danh': 're_enroll',
            'cân nhắc': 'considering',
            'can nhac': 'considering',
            'đang cân nhắc': 'considering',
            'không tái ghi danh': 'not_re_enroll',
            'khong tai ghi danh': 'not_re_enroll',
            # Tiếng Anh/Giá trị gốc
            're_enroll': 're_enroll',
            're-enroll': 're_enroll',
            'reenroll': 're_enroll',
            'considering': 'considering',
            'not_re_enroll': 'not_re_enroll',
            'not_re-enroll': 'not_re_enroll',
            'not re enroll': 'not_re_enroll',
        }
        
        valid_decisions = ['re_enroll', 'considering', 'not_re_enroll']
        
        success_count = 0
        error_count = 0
        errors = []
        
        for idx, row in df.iterrows():
            row_num = idx + 2  # Excel row number (1-indexed + header)
            
            try:
                student_code = str(row.get('student_code', '')).strip()
                decision_raw = str(row.get('decision', '')).strip()
                discount_value = str(row.get('discount_deadline', '')).strip() if pd.notna(row.get('discount_deadline')) else ''
                
                # Bỏ qua dòng trống
                if not student_code or pd.isna(row.get('student_code')):
                    continue
                
                # Bỏ qua dòng không có decision
                if not decision_raw or pd.isna(row.get('decision')) or decision_raw.lower() == 'nan':
                    continue
                
                # Map decision từ tiếng Việt/các biến thể sang giá trị chuẩn
                decision = decision_mapping.get(decision_raw.lower(), decision_raw.lower())
                
                # Validate student_code
                if student_code not in valid_students:
                    errors.append({
                        "row": row_num,
                        "error": f"Mã học sinh '{student_code}' không tồn tại trong đợt tái ghi danh này",
                        "data": {"student_code": student_code}
                    })
                    error_count += 1
                    continue
                
                # Validate decision
                if decision not in valid_decisions:
                    errors.append({
                        "row": row_num,
                        "error": f"Quyết định '{decision_raw}' không hợp lệ. Giá trị hợp lệ: Tái ghi danh, Cân nhắc, Không tái ghi danh",
                        "data": {"student_code": student_code, "decision": decision_raw}
                    })
                    error_count += 1
                    continue
                
                # Xử lý ưu đãi và payment_type nếu decision = re_enroll
                selected_discount_id = None
                payment_type = None
                
                if decision == 're_enroll':
                    # Lấy discount_value
                    if not discount_value or discount_value.lower() == 'nan':
                        errors.append({
                            "row": row_num,
                            "error": f"Cần điền ưu đãi (hạn đóng) khi quyết định Tái ghi danh",
                            "data": {"student_code": student_code, "decision": decision_raw}
                        })
                        error_count += 1
                        continue
                    
                    # Lấy payment_type từ Excel
                    payment_type_raw = str(row.get('payment_type', '')).strip() if pd.notna(row.get('payment_type')) else ''
                    if payment_type_raw and payment_type_raw.lower() != 'nan':
                        payment_type = payment_type_mapping.get(payment_type_raw.lower())
                        if not payment_type:
                            errors.append({
                                "row": row_num,
                                "error": f"'Đóng theo' = '{payment_type_raw}' không hợp lệ. Giá trị hợp lệ: Theo năm, Theo kỳ",
                                "data": {"student_code": student_code, "payment_type": payment_type_raw}
                            })
                            error_count += 1
                            continue
                    else:
                        # Mặc định là theo năm nếu không điền
                        payment_type = 'annual'
                    
                    # Thử tìm discount theo nhiều cách
                    # 1. Tìm trực tiếp theo discount_id
                    if discount_value in valid_discount_ids:
                        selected_discount_id = discount_value
                    # 2. Tìm theo deadline (nhiều format)
                    elif discount_value in deadline_to_discount:
                        selected_discount_id = deadline_to_discount[discount_value]
                    else:
                        # 3. Thử parse ngày từ Excel (có thể là datetime object)
                        try:
                            if isinstance(row.get('discount_deadline'), pd.Timestamp):
                                date_str = row.get('discount_deadline').strftime('%Y-%m-%d')
                                if date_str in deadline_to_discount:
                                    selected_discount_id = deadline_to_discount[date_str]
                        except:
                            pass
                    
                    if not selected_discount_id:
                        # Liệt kê các hạn đóng hợp lệ
                        valid_deadlines = [str(d.deadline) for d in discounts if d.deadline]
                        errors.append({
                            "row": row_num,
                            "error": f"Ưu đãi '{discount_value}' không hợp lệ. Hạn đóng hợp lệ: {', '.join(valid_deadlines)}",
                            "data": {"student_code": student_code, "discount": discount_value}
                        })
                        error_count += 1
                        continue
                
                # Cập nhật SIS Re-enrollment
                submission_id = valid_students[student_code]
                submission = frappe.get_doc("SIS Re-enrollment", submission_id)
                
                submission.decision = decision
                submission.submitted_at = now()
                submission.modified_by_admin = frappe.session.user
                submission.admin_modified_at = now()
                submission.agreement_accepted = 1  # Đánh dấu đã xác nhận
                
                if decision == 're_enroll' and selected_discount_id:
                    submission.selected_discount_id = selected_discount_id
                    submission.payment_type = payment_type  # Sử dụng payment_type từ Excel
                    
                    # Lấy thông tin ưu đãi
                    discount_info = frappe.db.get_value(
                        "SIS Re-enrollment Discount",
                        selected_discount_id,
                        ["deadline", "description", "annual_discount", "semester_discount"],
                        as_dict=True
                    )
                    if discount_info:
                        submission.selected_discount_name = discount_info.get("description") or selected_discount_id
                        submission.selected_discount_deadline = discount_info.get("deadline")
                        # Áp dụng đúng % discount dựa trên payment_type
                        if payment_type == "annual":
                            submission.selected_discount_percent = discount_info.get("annual_discount")
                        else:
                            submission.selected_discount_percent = discount_info.get("semester_discount")
                    submission.not_re_enroll_reason = None
                else:
                    # Không tái ghi danh hoặc đang cân nhắc
                    submission.selected_discount_id = None
                    submission.selected_discount_name = None
                    submission.selected_discount_deadline = None
                    submission.selected_discount_percent = None
                    submission.payment_type = None
                    
                    # Lấy lý do từ Excel
                    reason_raw = str(row.get('reason', '')).strip() if pd.notna(row.get('reason')) else ''
                    if reason_raw and reason_raw.lower() != 'nan':
                        submission.not_re_enroll_reason = reason_raw
                    else:
                        submission.not_re_enroll_reason = None
                
                # Xử lý câu trả lời khảo sát (chỉ khi Tái ghi danh)
                if decision == 're_enroll' and questions:
                    # Xóa câu trả lời cũ (nếu có)
                    submission.answers = []
                    
                    # Lấy tất cả tên cột trong DataFrame
                    df_columns = list(df.columns)
                    # Log để debug
                    if row_num == 2:  # Chỉ log 1 lần cho row đầu tiên
                        logs.append(f"Các cột trong Excel: {df_columns}")
                        logs.append(f"Các câu hỏi khảo sát: {[q['question_vn'] for q in questions]}")
                    
                    # Lấy các cột ngoài các cột chuẩn (có thể là cột câu hỏi)
                    standard_cols = ['student_code', 'student_name', 'current_class', 'decision', 'discount_deadline', 'payment_type', 'reason',
                                     'Mã học sinh', 'Họ tên', 'Lớp', 'Quyết định', 'Ưu đãi (hạn đóng)', 'Đóng theo', 'Lý do']
                    extra_cols = [c for c in df_columns if c not in standard_cols]
                    
                    for q in questions:
                        col_name = q['question_vn']
                        
                        # Tìm cột matching trong DataFrame
                        actual_col = None
                        
                        # 1. Khớp chính xác
                        if col_name in df_columns:
                            actual_col = col_name
                        else:
                            # 2. So sánh normalized (strip + lowercase)
                            col_name_normalized = col_name.strip().lower()
                            for c in df_columns:
                                if str(c).strip().lower() == col_name_normalized:
                                    actual_col = c
                                    break
                            
                            # 3. Tìm cột chứa tên câu hỏi hoặc ngược lại
                            if actual_col is None:
                                for c in extra_cols:
                                    c_norm = str(c).strip().lower()
                                    if col_name_normalized in c_norm or c_norm in col_name_normalized:
                                        actual_col = c
                                        break
                            
                            # 4. So sánh theo index (cột thứ 7, 8, 9... là câu hỏi 1, 2, 3...)
                            if actual_col is None and extra_cols:
                                q_index = questions.index(q)
                                if q_index < len(extra_cols):
                                    actual_col = extra_cols[q_index]
                                    if row_num == 2:
                                        logs.append(f"Matching câu hỏi '{col_name}' với cột '{actual_col}' theo index {q_index}")
                        
                        answer_raw = ''
                        if actual_col is not None:
                            val = row.get(actual_col)
                            if pd.notna(val):
                                answer_raw = str(val).strip()
                                if row_num == 2:
                                    logs.append(f"Câu hỏi '{col_name}' -> cột '{actual_col}' -> giá trị '{answer_raw}'")
                        
                        if answer_raw and answer_raw.lower() != 'nan':
                            # Parse các số đáp án (1 hoặc 1,2,3)
                            # Xử lý cả trường hợp số nguyên và số thực (1.0 -> 1)
                            try:
                                # Nếu là số, convert sang int trước
                                num_val = float(answer_raw)
                                if num_val == int(num_val):
                                    answer_raw = str(int(num_val))
                            except:
                                pass
                            
                            answer_indices = [a.strip() for a in answer_raw.replace('.', ',').split(',') if a.strip()]
                            
                            # Validate và convert sang option names
                            selected_option_names = []
                            selected_options_text_vn = []
                            selected_options_text_en = []
                            
                            for ans_idx in answer_indices:
                                try:
                                    idx_int = int(float(ans_idx))  # Xử lý cả "1.0" -> 1
                                    # Tìm option tương ứng
                                    opt_match = next((opt for opt in q['options'] if opt['idx'] == idx_int), None)
                                    if opt_match:
                                        selected_option_names.append(opt_match['name'])
                                        selected_options_text_vn.append(opt_match['option_vn'])
                                        selected_options_text_en.append(opt_match['option_en'])
                                    else:
                                        # Log để debug khi không tìm thấy option
                                        if row_num == 2:
                                            logs.append(f"KHÔNG tìm thấy option idx={idx_int} cho câu hỏi '{q['question_vn']}'. Options hiện có: {q['options']}")
                                except ValueError:
                                    pass  # Bỏ qua nếu không parse được số
                            
                            if selected_options_text_vn:
                                # Validate single_choice chỉ được chọn 1
                                if q['question_type'] == 'single_choice' and len(selected_options_text_vn) > 1:
                                    selected_option_names = [selected_option_names[0]]
                                    selected_options_text_vn = [selected_options_text_vn[0]]
                                    selected_options_text_en = [selected_options_text_en[0]]
                                
                                # Thêm câu trả lời
                                # Frontend expect selected_options chứa option_vn (text), không phải ID
                                submission.append('answers', {
                                    'question_id': q['name'],
                                    'question_text_vn': q['question_vn'],
                                    'question_text_en': q['question_en'],
                                    'selected_options': json.dumps(selected_options_text_vn),  # Lưu text, không phải ID
                                    'selected_options_text_vn': ', '.join(selected_options_text_vn),
                                    'selected_options_text_en': ', '.join(selected_options_text_en)
                                })
                                if row_num == 2:
                                    logs.append(f"Đã thêm câu trả lời cho '{q['question_vn']}': options={selected_options_text_vn}")
                            else:
                                if row_num == 2:
                                    logs.append(f"KHÔNG có option nào được chọn cho câu hỏi '{q['question_vn']}' với giá trị '{answer_raw}'")
                
                submission.save(ignore_permissions=True)
                success_count += 1
                
            except Exception as row_err:
                errors.append({
                    "row": row_num,
                    "error": str(row_err),
                    "data": {"student_code": str(row.get('student_code', ''))}
                })
                error_count += 1
        
        frappe.db.commit()
        
        logs.append(f"Import hoàn tất: {success_count} thành công, {error_count} lỗi")
        
        return success_response(
            data={
                "success_count": success_count,
                "error_count": error_count,
                "total_count": success_count + error_count,
                "errors": errors[:50]  # Giới hạn 50 lỗi để tránh response quá lớn
            },
            message=f"Import hoàn tất: {success_count} thành công, {error_count} lỗi",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Import Decision Excel Error")
        return error_response(
            message=f"Lỗi khi import: {str(e)}",
            logs=logs
        )

