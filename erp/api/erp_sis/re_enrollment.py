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
    allowed_roles = ['System Manager', 'SIS Manager', 'Registrar', 'SIS BOD']
    
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
                "discounts": discounts,
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
        required_fields = ['title', 'school_year_id', 'campus_id', 'start_date', 'end_date']
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
            "school_year_id": data['school_year_id'],
            "campus_id": data['campus_id'],
            "is_active": data.get('is_active', 0),
            "start_date": data['start_date'],
            "end_date": data['end_date'],
            "service_document": data.get('service_document'),
            "service_document_images": service_document_images,
            "agreement_text": data.get('agreement_text')
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
        
        config_doc.insert()
        frappe.db.commit()
        
        logs.append(f"Đã tạo config: {config_doc.name}")
        
        return success_response(
            data={
                "name": config_doc.name,
                "title": config_doc.title
            },
            message="Tạo cấu hình tái ghi danh thành công",
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
        update_fields = ['title', 'school_year_id', 'campus_id', 'is_active', 
                        'start_date', 'end_date', 'service_document', 'agreement_text']
        
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
    Chỉ xóa được nếu chưa có đơn nào.
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
            return error_response(
                f"Không thể xóa vì đã có {submission_count} đơn tái ghi danh",
                logs=logs
            )
        
        frappe.delete_doc("SIS Re-enrollment Config", config_id)
        frappe.db.commit()
        
        logs.append(f"Đã xóa config: {config_id}")
        
        return success_response(
            message="Xóa cấu hình thành công",
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
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền truy cập", logs=logs)
        
        # Lấy filters từ query params
        config_id = frappe.request.args.get('config_id')
        status = frappe.request.args.get('status')
        decision = frappe.request.args.get('decision')
        search = frappe.request.args.get('search')
        page = int(frappe.request.args.get('page', 1))
        page_size = int(frappe.request.args.get('page_size', 50))
        
        filters = {}
        if config_id:
            filters["config_id"] = config_id
        if status:
            filters["status"] = status
        if decision:
            filters["decision"] = decision
        
        # Build query
        conditions = []
        values = {}
        
        for key, value in filters.items():
            conditions.append(f"re.{key} = %({key})s")
            values[key] = value
        
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
        offset = (page - 1) * page_size
        query = f"""
            SELECT 
                re.name, re.config_id, re.student_id, re.student_name, re.student_code,
                re.guardian_id, re.guardian_name, re.current_class, re.campus_id,
                re.decision, re.payment_type, re.not_re_enroll_reason,
                re.status, re.submitted_at, re.modified_by_admin, re.admin_modified_at
            FROM `tabSIS Re-enrollment` re
            WHERE {where_clause}
            ORDER BY re.submitted_at DESC
            LIMIT {page_size} OFFSET {offset}
        """
        
        submissions = frappe.db.sql(query, values, as_dict=True)
        
        # Thêm display values
        for sub in submissions:
            sub["decision_display"] = "Tái ghi danh" if sub.decision == 're_enroll' else "Không tái ghi danh"
            if sub.payment_type:
                sub["payment_display"] = "Đóng theo năm" if sub.payment_type == 'annual' else "Đóng theo kỳ"
            
            status_map = {
                "pending": "Chờ xử lý",
                "approved": "Đã duyệt", 
                "rejected": "Từ chối"
            }
            sub["status_display"] = status_map.get(sub.status, sub.status)
        
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
        
        # Các trường admin có thể sửa
        updatable_fields = ['decision', 'payment_type', 'not_re_enroll_reason', 'status', 'admin_notes']
        
        for field in updatable_fields:
            if field in data:
                submission.set(field, data[field])
        
        # Ghi nhận admin sửa
        submission.modified_by_admin = frappe.session.user
        submission.admin_modified_at = now()
        
        submission.save()
        frappe.db.commit()
        
        logs.append(f"Đã cập nhật đơn: {submission_id}")
        
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
        decision_dict = {item.decision: item.count for item in decision_stats}
        status_dict = {item.status: item.count for item in status_stats}
        payment_dict = {item.payment_type: item.count for item in payment_stats if item.payment_type}
        
        logs.append(f"Thống kê cho config {config_id}")
        
        return success_response(
            data={
                "total_submissions": total,
                "total_students_in_campus": total_students,
                "not_submitted": total_students - total,
                "by_decision": {
                    "re_enroll": decision_dict.get("re_enroll", 0),
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

