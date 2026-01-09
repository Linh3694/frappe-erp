"""
Admin Scholarship API
Handles scholarship management for admin/admission staff

API endpoints cho admin quản lý kỳ học bổng và đơn đăng ký.
"""

import frappe
from frappe import _
from frappe.utils import nowdate, getdate, now
import json
from erp.utils.api_response import (
    validation_error_response, 
    list_response, 
    error_response, 
    success_response, 
    single_item_response,
    not_found_response
)


def _check_admin_permission():
    """Kiểm tra quyền admin"""
    user_roles = frappe.get_roles(frappe.session.user)
    allowed_roles = ['System Manager', 'SIS Manager', 'Registrar', 'SIS BOD']
    
    if not any(role in user_roles for role in allowed_roles):
        return False
    return True


def _check_approver_permission(education_stage_id=None, period_id=None):
    """Kiểm tra quyền người phê duyệt"""
    user = frappe.session.user
    
    # Admin luôn có quyền
    if _check_admin_permission():
        return True
    
    # Kiểm tra trong danh sách approver
    if period_id:
        period = frappe.get_doc("SIS Scholarship Period", period_id)
        return period.is_approver(user, education_stage_id)
    
    return False


def _resolve_campus_id(campus_id):
    """
    Chuyển đổi campus_id từ format frontend (campus-1) sang format database (CAMPUS-00001)
    Giống cách xử lý trong re_enrollment.py
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


# ==================== PERIOD APIs ====================

@frappe.whitelist()
def get_scholarship_periods():
    """
    Lấy danh sách tất cả kỳ học bổng.
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
        
        periods = frappe.get_all(
            "SIS Scholarship Period",
            filters=filters,
            fields=["*"],
            order_by="modified desc"
        )
        
        # Thêm thông tin bổ sung
        for period in periods:
            # Tên năm học
            school_year = frappe.db.get_value(
                "SIS School Year",
                period.get("academic_year_id"),
                ["title_vn", "title_en"],
                as_dict=True
            )
            period["academic_year_name"] = school_year.title_vn if school_year else None
            
            # Tên campus
            campus_info = frappe.db.get_value(
                "SIS Campus", 
                period.get("campus_id"), 
                ["title_vn", "title_en"],
                as_dict=True
            )
            period["campus_name"] = campus_info.title_vn if campus_info else None
            
            # Đếm số đơn
            application_count = frappe.db.count(
                "SIS Scholarship Application",
                {"scholarship_period_id": period.name}
            )
            period["application_count"] = application_count
        
        logs.append(f"Tìm thấy {len(periods)} kỳ học bổng")
        
        return list_response(periods)
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Admin Get Scholarship Periods Error")
        return error_response(
            message=f"Lỗi khi lấy danh sách kỳ học bổng: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def get_scholarship_period(period_id=None):
    """
    Lấy chi tiết một kỳ học bổng.
    Bao gồm cấp học, người phê duyệt và cấu hình form thư giới thiệu.
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền truy cập", logs=logs)
        
        if not period_id:
            period_id = frappe.request.args.get('period_id')
        
        if not period_id:
            return validation_error_response(
                "Thiếu period_id",
                {"period_id": ["Period ID là bắt buộc"]}
            )
        
        if not frappe.db.exists("SIS Scholarship Period", period_id):
            return not_found_response("Không tìm thấy kỳ học bổng")
        
        period = frappe.get_doc("SIS Scholarship Period", period_id)
        
        # Lấy danh sách cấp học
        education_stages = []
        for stage in period.education_stages:
            education_stages.append({
                "name": stage.name,
                "educational_stage_id": stage.educational_stage_id,
                "educational_stage_name": stage.educational_stage_name
            })
        
        # Lấy danh sách người phê duyệt
        approvers = []
        for approver in period.approvers:
            approvers.append({
                "name": approver.name,
                "educational_stage_id": approver.educational_stage_id,
                "educational_stage_name": approver.educational_stage_name,
                "user_id": approver.user_id,
                "user_name": approver.user_name
            })
        
        # Lấy cấu hình form thư giới thiệu
        form_sections = []
        for section in period.form_sections:
            questions = []
            if section.questions_json:
                try:
                    questions = json.loads(section.questions_json)
                except:
                    questions = []
            
            form_sections.append({
                "name": section.name,
                "section_title_vn": section.section_title_vn,
                "section_title_en": section.section_title_en,
                "sort_order": section.sort_order,
                "questions": questions
            })
        
        # Tên năm học
        school_year = frappe.db.get_value(
            "SIS School Year",
            period.academic_year_id,
            ["title_vn", "title_en"],
            as_dict=True
        )
        
        logs.append(f"Lấy period: {period_id}")
        
        return single_item_response(
            data={
                "name": period.name,
                "title": period.title,
                "academic_year_id": period.academic_year_id,
                "academic_year_name_vn": school_year.title_vn if school_year else None,
                "academic_year_name_en": school_year.title_en if school_year else None,
                "campus_id": period.campus_id,
                "status": period.status,
                "from_date": str(period.from_date) if period.from_date else None,
                "to_date": str(period.to_date) if period.to_date else None,
                "education_stages": education_stages,
                "approvers": approvers,
                "form_sections": form_sections,
                "created_by": period.created_by,
                "created_at": str(period.created_at) if period.created_at else None
            },
            message="Lấy kỳ học bổng thành công"
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Admin Get Scholarship Period Error")
        return error_response(
            message=f"Lỗi khi lấy kỳ học bổng: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def create_scholarship_period():
    """
    Tạo kỳ học bổng mới.
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
        
        logs.append(f"Tạo kỳ học bổng mới: {json.dumps(data, default=str)}")
        
        # Validate required fields
        required_fields = ['title', 'academic_year_id', 'campus_id', 'from_date', 'to_date']
        for field in required_fields:
            if field not in data or not data[field]:
                return validation_error_response(
                    f"Thiếu trường bắt buộc: {field}",
                    {field: [f"Trường {field} là bắt buộc"]}
                )
        
        # Resolve campus_id (chuyển đổi từ format frontend sang format database)
        resolved_campus_id = _resolve_campus_id(data['campus_id'])
        if not resolved_campus_id:
            return validation_error_response(
                f"Không tìm thấy Campus nào trong hệ thống",
                {"campus_id": ["Vui lòng tạo Campus trước"]}
            )
        
        logs.append(f"Campus resolved: {data['campus_id']} -> {resolved_campus_id}")
        
        # Tạo document
        period_doc = frappe.get_doc({
            "doctype": "SIS Scholarship Period",
            "title": data['title'],
            "academic_year_id": data['academic_year_id'],
            "campus_id": resolved_campus_id,
            "status": data.get('status', 'Draft'),
            "from_date": data['from_date'],
            "to_date": data['to_date']
        })
        
        # Thêm cấp học
        education_stages = data.get('education_stages', [])
        if isinstance(education_stages, str):
            education_stages = json.loads(education_stages)
        
        for stage in education_stages:
            period_doc.append("education_stages", {
                "educational_stage_id": stage.get('educational_stage_id')
            })
        
        # Thêm người phê duyệt
        approvers = data.get('approvers', [])
        if isinstance(approvers, str):
            approvers = json.loads(approvers)
        
        for approver in approvers:
            period_doc.append("approvers", {
                "educational_stage_id": approver.get('educational_stage_id'),
                "user_id": approver.get('user_id')
            })
        
        # Thêm cấu hình form thư giới thiệu
        form_sections = data.get('form_sections', [])
        if isinstance(form_sections, str):
            form_sections = json.loads(form_sections)
        
        for idx, section in enumerate(form_sections):
            questions = section.get('questions', [])
            period_doc.append("form_sections", {
                "section_title_vn": section.get('section_title_vn'),
                "section_title_en": section.get('section_title_en'),
                "sort_order": section.get('sort_order', idx),
                "questions_json": json.dumps(questions) if questions else None
            })
        
        period_doc.insert()
        frappe.db.commit()
        
        logs.append(f"Đã tạo kỳ học bổng: {period_doc.name}")
        
        return success_response(
            data={
                "name": period_doc.name,
                "title": period_doc.title
            },
            message="Tạo kỳ học bổng thành công",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Admin Create Scholarship Period Error")
        return error_response(
            message=f"Lỗi khi tạo kỳ học bổng: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def update_scholarship_period():
    """
    Cập nhật kỳ học bổng.
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
        
        period_id = data.get('name') or data.get('period_id')
        if not period_id:
            return validation_error_response(
                "Thiếu period_id",
                {"period_id": ["Period ID là bắt buộc"]}
            )
        
        logs.append(f"Cập nhật kỳ học bổng: {period_id}")
        
        if not frappe.db.exists("SIS Scholarship Period", period_id):
            return not_found_response("Không tìm thấy kỳ học bổng")
        
        period_doc = frappe.get_doc("SIS Scholarship Period", period_id)
        
        # Update các trường cơ bản
        update_fields = ['title', 'academic_year_id', 'campus_id', 'status', 
                        'from_date', 'to_date']
        
        for field in update_fields:
            if field in data:
                period_doc.set(field, data[field])
        
        # Update cấp học
        if 'education_stages' in data:
            education_stages = data['education_stages']
            if isinstance(education_stages, str):
                education_stages = json.loads(education_stages)
            
            period_doc.education_stages = []
            for stage in education_stages:
                period_doc.append("education_stages", {
                    "educational_stage_id": stage.get('educational_stage_id')
                })
        
        # Update người phê duyệt
        if 'approvers' in data:
            approvers = data['approvers']
            if isinstance(approvers, str):
                approvers = json.loads(approvers)
            
            period_doc.approvers = []
            for approver in approvers:
                period_doc.append("approvers", {
                    "educational_stage_id": approver.get('educational_stage_id'),
                    "user_id": approver.get('user_id')
                })
        
        # Update form sections
        if 'form_sections' in data:
            form_sections = data['form_sections']
            if isinstance(form_sections, str):
                form_sections = json.loads(form_sections)
            
            period_doc.form_sections = []
            for idx, section in enumerate(form_sections):
                questions = section.get('questions', [])
                period_doc.append("form_sections", {
                    "section_title_vn": section.get('section_title_vn'),
                    "section_title_en": section.get('section_title_en'),
                    "sort_order": section.get('sort_order', idx),
                    "questions_json": json.dumps(questions) if questions else None
                })
        
        period_doc.save()
        frappe.db.commit()
        
        logs.append(f"Đã cập nhật kỳ học bổng: {period_id}")
        
        return success_response(
            data={"name": period_doc.name},
            message="Cập nhật kỳ học bổng thành công",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Admin Update Scholarship Period Error")
        return error_response(
            message=f"Lỗi khi cập nhật kỳ học bổng: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def toggle_period_status():
    """
    Đổi trạng thái kỳ học bổng (Draft/Open/Closed).
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
        
        period_id = data.get('period_id')
        new_status = data.get('status')
        
        if not period_id:
            return validation_error_response(
                "Thiếu period_id",
                {"period_id": ["Period ID là bắt buộc"]}
            )
        
        if new_status not in ['Draft', 'Open', 'Closed']:
            return validation_error_response(
                "Trạng thái không hợp lệ",
                {"status": ["Trạng thái phải là Draft, Open hoặc Closed"]}
            )
        
        logs.append(f"Toggle status {period_id} -> {new_status}")
        
        period_doc = frappe.get_doc("SIS Scholarship Period", period_id)
        period_doc.status = new_status
        period_doc.save()
        
        frappe.db.commit()
        
        status_text_map = {
            "Draft": "Nháp",
            "Open": "Đang mở",
            "Closed": "Đã đóng"
        }
        
        return success_response(
            data={"name": period_id, "status": new_status},
            message=f"Kỳ học bổng đã chuyển sang trạng thái: {status_text_map.get(new_status, new_status)}",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Admin Toggle Period Status Error")
        return error_response(
            message=f"Lỗi: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def delete_scholarship_period():
    """
    Xóa kỳ học bổng.
    Chỉ có thể xóa kỳ chưa có đơn đăng ký.
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
        
        period_id = data.get('period_id')
        
        if not period_id:
            return validation_error_response(
                "Thiếu period_id",
                {"period_id": ["Period ID là bắt buộc"]}
            )
        
        # Kiểm tra tồn tại
        if not frappe.db.exists("SIS Scholarship Period", period_id):
            return not_found_response("Không tìm thấy kỳ học bổng")
        
        # Kiểm tra có đơn đăng ký hay không
        application_count = frappe.db.count(
            "SIS Scholarship Application",
            {"scholarship_period_id": period_id}
        )
        
        if application_count > 0:
            return validation_error_response(
                f"Không thể xóa kỳ học bổng vì đã có {application_count} đơn đăng ký",
                {"period_id": ["Kỳ học bổng đã có đơn đăng ký"]}
            )
        
        # Xóa kỳ học bổng
        frappe.delete_doc("SIS Scholarship Period", period_id)
        frappe.db.commit()
        
        logs.append(f"Đã xóa kỳ học bổng: {period_id}")
        
        return success_response(
            data={"message": "Đã xóa kỳ học bổng thành công"},
            message="Đã xóa kỳ học bổng thành công",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Admin Delete Period Error")
        return error_response(
            message=f"Lỗi: {str(e)}",
            logs=logs
        )


# ==================== APPLICATION APIs ====================

@frappe.whitelist()
def get_applications():
    """
    Lấy danh sách đơn đăng ký học bổng.
    Có thể filter theo period_id, education_stage_id, status.
    """
    logs = []
    
    try:
        # Kiểm tra quyền
        user_roles = frappe.get_roles(frappe.session.user)
        if not any(role in user_roles for role in ['System Manager', 'SIS Manager', 'Registrar', 'SIS BOD']):
            return error_response("Bạn không có quyền truy cập", logs=logs)
        
        # Lấy filters từ query params
        period_id = frappe.request.args.get('period_id')
        education_stage_id = frappe.request.args.get('education_stage_id')
        status = frappe.request.args.get('status')
        search = frappe.request.args.get('search')
        page = int(frappe.request.args.get('page', 1))
        page_size = int(frappe.request.args.get('page_size', 50))
        
        # Build query
        conditions = []
        values = {}
        
        if period_id:
            conditions.append("app.scholarship_period_id = %(period_id)s")
            values["period_id"] = period_id
        
        if education_stage_id:
            conditions.append("app.education_stage_id = %(education_stage_id)s")
            values["education_stage_id"] = education_stage_id
        
        if status:
            conditions.append("app.status = %(status)s")
            values["status"] = status
        
        if search:
            conditions.append("(app.student_name LIKE %(search)s OR app.student_code LIKE %(search)s)")
            values["search"] = f"%{search}%"
        
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        
        # Count total
        total_query = f"""
            SELECT COUNT(*) as total
            FROM `tabSIS Scholarship Application` app
            WHERE {where_clause}
        """
        total = frappe.db.sql(total_query, values, as_dict=True)[0].total
        
        # Get applications with pagination
        offset = (page - 1) * page_size
        query = f"""
            SELECT 
                app.name, app.scholarship_period_id, app.student_id, app.student_name, 
                app.student_code, app.class_name, app.education_stage_name,
                app.status, app.submitted_at,
                app.main_teacher_name, app.second_teacher_name,
                app.main_recommendation_status, app.second_recommendation_status,
                app.total_score, app.total_percentage
            FROM `tabSIS Scholarship Application` app
            WHERE {where_clause}
            ORDER BY app.submitted_at DESC
            LIMIT {page_size} OFFSET {offset}
        """
        
        applications = frappe.db.sql(query, values, as_dict=True)
        
        # Thêm display values
        status_display_map = {
            "Submitted": "Đã nộp",
            "WaitingRecommendation": "Chờ thư giới thiệu",
            "RecommendationSubmitted": "Đã có thư GT",
            "InReview": "Đang xét duyệt",
            "Approved": "Đã duyệt",
            "Rejected": "Từ chối",
            "DeniedByTeacher": "GV từ chối"
        }
        
        for app in applications:
            app["status_display"] = status_display_map.get(app.status, app.status)
        
        logs.append(f"Tìm thấy {len(applications)} / {total} đơn")
        
        return success_response(
            data={
                "items": applications,
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
        frappe.log_error(frappe.get_traceback(), "Admin Get Applications Error")
        return error_response(
            message=f"Lỗi: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def get_application_detail(application_id=None):
    """
    Lấy chi tiết đơn đăng ký học bổng.
    Bao gồm thành tích, thư giới thiệu và điểm số.
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền truy cập", logs=logs)
        
        if not application_id:
            application_id = frappe.request.args.get('application_id')
        
        if not application_id:
            return validation_error_response(
                "Thiếu application_id",
                {"application_id": ["Application ID là bắt buộc"]}
            )
        
        if not frappe.db.exists("SIS Scholarship Application", application_id):
            return not_found_response("Không tìm thấy đơn đăng ký")
        
        app = frappe.get_doc("SIS Scholarship Application", application_id)
        
        # Lấy thành tích
        achievements = []
        for ach in app.achievements:
            achievements.append({
                "achievement_type": ach.achievement_type,
                "title": ach.title,
                "description": ach.description,
                "organization": ach.organization,
                "role": ach.role,
                "result": ach.result,
                "date_received": str(ach.date_received) if ach.date_received else None,
                "attachment": ach.attachment
            })
        
        # Lấy thư giới thiệu
        recommendations = []
        if app.main_recommendation_id:
            main_rec = frappe.get_doc("SIS Scholarship Recommendation", app.main_recommendation_id)
            recommendations.append({
                "type": "main",
                "teacher_name": main_rec.teacher_name,
                "status": main_rec.status,
                "denied_reason": main_rec.denied_reason,
                "submitted_at": str(main_rec.submitted_at) if main_rec.submitted_at else None,
                "answers": [{"section_title": a.section_title, "question_text_vn": a.question_text_vn, "answer_text": a.answer_text, "answer_rating": a.answer_rating} for a in main_rec.answers]
            })
        
        if app.second_recommendation_id:
            second_rec = frappe.get_doc("SIS Scholarship Recommendation", app.second_recommendation_id)
            recommendations.append({
                "type": "second",
                "teacher_name": second_rec.teacher_name,
                "status": second_rec.status,
                "denied_reason": second_rec.denied_reason,
                "submitted_at": str(second_rec.submitted_at) if second_rec.submitted_at else None,
                "answers": [{"section_title": a.section_title, "question_text_vn": a.question_text_vn, "answer_text": a.answer_text, "answer_rating": a.answer_rating} for a in second_rec.answers]
            })
        
        # Lấy điểm số
        scoring = None
        if app.scoring_id:
            score_doc = frappe.get_doc("SIS Scholarship Scoring", app.scoring_id)
            scoring = {
                "ctvn_score": score_doc.ctvn_score,
                "ctqt_score": score_doc.ctqt_score,
                "standardized_test_score": score_doc.standardized_test_score,
                "quality_score": score_doc.quality_score,
                "extracurricular_score": score_doc.extracurricular_score,
                "competition_score": score_doc.competition_score,
                "recommendation_score": score_doc.recommendation_score,
                "video_score": score_doc.video_score,
                "total_score": score_doc.total_score,
                "percentage": score_doc.percentage,
                "note": score_doc.note,
                "approver_name": score_doc.approver_name
            }
        
        return single_item_response(
            data={
                "name": app.name,
                "scholarship_period_id": app.scholarship_period_id,
                "student_id": app.student_id,
                "student_name": app.student_name,
                "student_code": app.student_code,
                "class_id": app.class_id,
                "class_name": app.class_name,
                "education_stage_id": app.education_stage_id,
                "education_stage_name": app.education_stage_name,
                "status": app.status,
                "submitted_at": str(app.submitted_at) if app.submitted_at else None,
                "guardian_name": app.guardian_name,
                "academic_report_type": app.academic_report_type,
                "academic_report_link": app.academic_report_link,
                "academic_report_upload": app.academic_report_upload,
                "video_url": app.video_url,
                "main_teacher_name": app.main_teacher_name,
                "second_teacher_name": app.second_teacher_name,
                "achievements": achievements,
                "recommendations": recommendations,
                "scoring": scoring,
                "total_score": app.total_score,
                "total_percentage": app.total_percentage,
                "approved_by": app.approved_by,
                "approved_at": str(app.approved_at) if app.approved_at else None,
                "rejection_reason": app.rejection_reason
            },
            message="Lấy chi tiết đơn thành công"
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Admin Get Application Detail Error")
        return error_response(
            message=f"Lỗi: {str(e)}",
            logs=logs
        )


# ==================== SCORING APIs ====================

@frappe.whitelist()
def save_scoring():
    """
    Lưu chấm điểm hồ sơ.
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
        
        application_id = data.get('application_id')
        if not application_id:
            return validation_error_response(
                "Thiếu application_id",
                {"application_id": ["Application ID là bắt buộc"]}
            )
        
        logs.append(f"Chấm điểm cho đơn: {application_id}")
        
        # Lấy hoặc tạo scoring record
        app = frappe.get_doc("SIS Scholarship Application", application_id)
        
        if app.scoring_id:
            scoring = frappe.get_doc("SIS Scholarship Scoring", app.scoring_id)
        else:
            scoring = frappe.new_doc("SIS Scholarship Scoring")
            scoring.application_id = application_id
            scoring.approver_id = frappe.session.user
        
        # Cập nhật điểm
        score_fields = ['ctvn_score', 'ctqt_score', 'standardized_test_score',
                       'quality_score', 'extracurricular_score', 'competition_score',
                       'recommendation_score', 'video_score', 'note']
        
        for field in score_fields:
            if field in data:
                setattr(scoring, field, data[field])
        
        scoring.save()
        frappe.db.commit()
        
        logs.append(f"Đã lưu điểm: Tổng {scoring.total_score}/{scoring.percentage}%")
        
        return success_response(
            data={
                "name": scoring.name,
                "total_score": scoring.total_score,
                "percentage": scoring.percentage
            },
            message="Lưu chấm điểm thành công",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Admin Save Scoring Error")
        return error_response(
            message=f"Lỗi khi chấm điểm: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def approve_application():
    """
    Duyệt đơn đăng ký học bổng.
    Yêu cầu đã chấm điểm trước.
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
        
        application_id = data.get('application_id')
        if not application_id:
            return validation_error_response(
                "Thiếu application_id",
                {"application_id": ["Application ID là bắt buộc"]}
            )
        
        app = frappe.get_doc("SIS Scholarship Application", application_id)
        
        # Kiểm tra đã chấm điểm chưa
        if not app.scoring_id:
            return error_response("Vui lòng chấm điểm hồ sơ trước khi duyệt", logs=logs)
        
        scoring = frappe.get_doc("SIS Scholarship Scoring", app.scoring_id)
        if not scoring.is_complete():
            return error_response("Vui lòng chấm đủ tất cả tiêu chí trước khi duyệt", logs=logs)
        
        # Duyệt đơn
        app.status = "Approved"
        app.approved_by = frappe.session.user
        app.approved_at = now()
        app.save()
        
        frappe.db.commit()
        
        logs.append(f"Đã duyệt đơn: {application_id}")
        
        return success_response(
            data={"name": app.name, "status": "Approved"},
            message="Duyệt đơn thành công",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Admin Approve Application Error")
        return error_response(
            message=f"Lỗi: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def reject_application():
    """
    Từ chối đơn đăng ký học bổng.
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
        
        application_id = data.get('application_id')
        reason = data.get('reason')
        
        if not application_id:
            return validation_error_response(
                "Thiếu application_id",
                {"application_id": ["Application ID là bắt buộc"]}
            )
        
        if not reason:
            return validation_error_response(
                "Thiếu lý do từ chối",
                {"reason": ["Lý do từ chối là bắt buộc"]}
            )
        
        app = frappe.get_doc("SIS Scholarship Application", application_id)
        
        # Từ chối đơn
        app.status = "Rejected"
        app.rejection_reason = reason
        app.approved_by = frappe.session.user
        app.approved_at = now()
        app.save()
        
        frappe.db.commit()
        
        logs.append(f"Đã từ chối đơn: {application_id}")
        
        return success_response(
            data={"name": app.name, "status": "Rejected"},
            message="Từ chối đơn thành công",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Admin Reject Application Error")
        return error_response(
            message=f"Lỗi: {str(e)}",
            logs=logs
        )


# ==================== TEACHER APIs ====================

@frappe.whitelist()
def get_class_applications(class_id=None):
    """
    Lấy danh sách đơn học bổng cần viết thư giới thiệu theo lớp.
    Dùng cho giáo viên trong ClassInfo tab.
    """
    logs = []
    
    try:
        if not class_id:
            class_id = frappe.request.args.get('class_id')
        
        if not class_id:
            return validation_error_response(
                "Thiếu class_id",
                {"class_id": ["Class ID là bắt buộc"]}
            )
        
        user = frappe.session.user
        
        # Lấy teacher_id của user hiện tại
        teacher_id = frappe.db.get_value(
            "SIS Teacher",
            {"user_id": user},
            "name"
        )
        
        if not teacher_id:
            return error_response("Bạn không phải giáo viên trong hệ thống", logs=logs)
        
        # Lấy các đơn mà GV này được chọn làm người giới thiệu
        query = """
            SELECT 
                app.name, app.student_id, app.student_name, app.student_code,
                app.status, app.submitted_at,
                CASE 
                    WHEN app.main_teacher_id = %(teacher_id)s THEN 'main'
                    WHEN app.second_teacher_id = %(teacher_id)s THEN 'second'
                END as recommendation_type,
                CASE 
                    WHEN app.main_teacher_id = %(teacher_id)s THEN app.main_recommendation_status
                    WHEN app.second_teacher_id = %(teacher_id)s THEN app.second_recommendation_status
                END as recommendation_status,
                CASE 
                    WHEN app.main_teacher_id = %(teacher_id)s THEN app.main_recommendation_id
                    WHEN app.second_teacher_id = %(teacher_id)s THEN app.second_recommendation_id
                END as recommendation_id
            FROM `tabSIS Scholarship Application` app
            WHERE app.class_id = %(class_id)s
              AND (app.main_teacher_id = %(teacher_id)s OR app.second_teacher_id = %(teacher_id)s)
              AND app.status IN ('WaitingRecommendation', 'RecommendationSubmitted', 'InReview', 'Approved', 'Rejected', 'DeniedByTeacher')
            ORDER BY app.submitted_at DESC
        """
        
        applications = frappe.db.sql(query, {
            "class_id": class_id,
            "teacher_id": teacher_id
        }, as_dict=True)
        
        # Thêm display values
        for app in applications:
            app["recommendation_status_display"] = {
                "Pending": "Chờ viết thư",
                "Submitted": "Đã viết thư",
                "Denied": "Đã từ chối"
            }.get(app.recommendation_status, app.recommendation_status)
        
        logs.append(f"Tìm thấy {len(applications)} đơn cho class {class_id}")
        
        return list_response(applications, logs=logs)
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Get Class Applications Error")
        return error_response(
            message=f"Lỗi: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def get_recommendation_form(application_id=None):
    """
    Lấy form thư giới thiệu cho một đơn đăng ký.
    """
    logs = []
    
    try:
        if not application_id:
            application_id = frappe.request.args.get('application_id')
        
        if not application_id:
            return validation_error_response(
                "Thiếu application_id",
                {"application_id": ["Application ID là bắt buộc"]}
            )
        
        app = frappe.get_doc("SIS Scholarship Application", application_id)
        period = frappe.get_doc("SIS Scholarship Period", app.scholarship_period_id)
        
        # Lấy cấu hình form
        form_sections = []
        for section in period.form_sections:
            questions = []
            if section.questions_json:
                try:
                    questions = json.loads(section.questions_json)
                except:
                    questions = []
            
            form_sections.append({
                "section_title_vn": section.section_title_vn,
                "section_title_en": section.section_title_en,
                "sort_order": section.sort_order,
                "questions": questions
            })
        
        # Thông tin học sinh
        student_info = {
            "student_name": app.student_name,
            "student_code": app.student_code,
            "class_name": app.class_name
        }
        
        return single_item_response(
            data={
                "student_info": student_info,
                "form_sections": form_sections
            },
            message="Lấy form thư giới thiệu thành công"
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Get Recommendation Form Error")
        return error_response(
            message=f"Lỗi: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def submit_recommendation():
    """
    Giáo viên submit thư giới thiệu.
    """
    logs = []
    
    try:
        # Lấy data từ request
        if frappe.request.is_json:
            data = frappe.request.json or {}
        else:
            data = frappe.form_dict
        
        recommendation_id = data.get('recommendation_id')
        answers = data.get('answers', [])
        
        if not recommendation_id:
            return validation_error_response(
                "Thiếu recommendation_id",
                {"recommendation_id": ["Recommendation ID là bắt buộc"]}
            )
        
        if isinstance(answers, str):
            answers = json.loads(answers)
        
        if not answers:
            return validation_error_response(
                "Thiếu nội dung thư giới thiệu",
                {"answers": ["Vui lòng điền nội dung thư giới thiệu"]}
            )
        
        logs.append(f"Submit recommendation: {recommendation_id}")
        
        rec = frappe.get_doc("SIS Scholarship Recommendation", recommendation_id)
        
        # Kiểm tra quyền
        user = frappe.session.user
        teacher_user = frappe.db.get_value("SIS Teacher", rec.teacher_id, "user_id")
        
        user_roles = frappe.get_roles(user)
        if teacher_user != user and "System Manager" not in user_roles and "SIS Manager" not in user_roles:
            return error_response("Bạn không có quyền viết thư giới thiệu này", logs=logs)
        
        # Submit thư
        rec.submit_recommendation(answers)
        
        logs.append(f"Đã submit thư giới thiệu: {recommendation_id}")
        
        return success_response(
            data={"name": rec.name, "status": "Submitted"},
            message="Gửi thư giới thiệu thành công",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Submit Recommendation Error")
        return error_response(
            message=f"Lỗi: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def deny_recommendation():
    """
    Giáo viên từ chối viết thư giới thiệu.
    """
    logs = []
    
    try:
        # Lấy data từ request
        if frappe.request.is_json:
            data = frappe.request.json or {}
        else:
            data = frappe.form_dict
        
        recommendation_id = data.get('recommendation_id')
        reason = data.get('reason')
        
        if not recommendation_id:
            return validation_error_response(
                "Thiếu recommendation_id",
                {"recommendation_id": ["Recommendation ID là bắt buộc"]}
            )
        
        if not reason:
            return validation_error_response(
                "Thiếu lý do từ chối",
                {"reason": ["Lý do từ chối là bắt buộc"]}
            )
        
        logs.append(f"Deny recommendation: {recommendation_id}")
        
        rec = frappe.get_doc("SIS Scholarship Recommendation", recommendation_id)
        
        # Kiểm tra quyền
        user = frappe.session.user
        teacher_user = frappe.db.get_value("SIS Teacher", rec.teacher_id, "user_id")
        
        user_roles = frappe.get_roles(user)
        if teacher_user != user and "System Manager" not in user_roles and "SIS Manager" not in user_roles:
            return error_response("Bạn không có quyền từ chối thư giới thiệu này", logs=logs)
        
        # Deny thư
        rec.deny_recommendation(reason)
        
        logs.append(f"Đã từ chối viết thư: {recommendation_id}")
        
        return success_response(
            data={"name": rec.name, "status": "Denied"},
            message="Đã từ chối viết thư giới thiệu",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Deny Recommendation Error")
        return error_response(
            message=f"Lỗi: {str(e)}",
            logs=logs
        )


# ==================== STATISTICS API ====================

@frappe.whitelist()
def get_statistics(period_id=None):
    """
    Lấy thống kê học bổng theo kỳ.
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền truy cập", logs=logs)
        
        if not period_id:
            period_id = frappe.request.args.get('period_id')
        
        if not period_id:
            return validation_error_response(
                "Thiếu period_id",
                {"period_id": ["Period ID là bắt buộc"]}
            )
        
        # Thống kê theo trạng thái
        status_stats = frappe.db.sql("""
            SELECT 
                status,
                COUNT(*) as count
            FROM `tabSIS Scholarship Application`
            WHERE scholarship_period_id = %s
            GROUP BY status
        """, period_id, as_dict=True)
        
        # Thống kê theo cấp học
        stage_stats = frappe.db.sql("""
            SELECT 
                education_stage_name,
                COUNT(*) as count
            FROM `tabSIS Scholarship Application`
            WHERE scholarship_period_id = %s
            GROUP BY education_stage_id
        """, period_id, as_dict=True)
        
        # Tổng số
        total = frappe.db.count("SIS Scholarship Application", {"scholarship_period_id": period_id})
        
        # Chuyển đổi thành dict
        status_dict = {item.status: item.count for item in status_stats}
        
        return success_response(
            data={
                "total_applications": total,
                "by_status": {
                    "Submitted": status_dict.get("Submitted", 0),
                    "WaitingRecommendation": status_dict.get("WaitingRecommendation", 0),
                    "RecommendationSubmitted": status_dict.get("RecommendationSubmitted", 0),
                    "InReview": status_dict.get("InReview", 0),
                    "Approved": status_dict.get("Approved", 0),
                    "Rejected": status_dict.get("Rejected", 0),
                    "DeniedByTeacher": status_dict.get("DeniedByTeacher", 0)
                },
                "by_stage": stage_stats
            },
            message="Lấy thống kê thành công",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Admin Get Scholarship Statistics Error")
        return error_response(
            message=f"Lỗi: {str(e)}",
            logs=logs
        )
