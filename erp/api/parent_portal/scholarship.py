"""
Parent Portal Scholarship API
Handles scholarship registration for parents

API endpoints cho phụ huynh đăng ký học bổng.
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


def _get_current_guardian():
    """
    Lấy guardian name của user hiện tại.
    Email format: guardian_id@parent.wellspring.edu.vn
    """
    user_email = frappe.session.user
    
    if not user_email:
        return None
    
    # Format email: guardian_id@parent.wellspring.edu.vn
    if "@parent.wellspring.edu.vn" not in user_email:
        # Fallback: thử tìm trực tiếp bằng email
        guardian = frappe.db.get_value("CRM Guardian", {"email": user_email}, "name")
        return guardian
    
    # Extract guardian_id từ email
    guardian_id = user_email.split("@")[0]
    
    # Lấy guardian name từ guardian_id
    guardian = frappe.db.get_value("CRM Guardian", {"guardian_id": guardian_id}, "name")
    return guardian


def _get_guardian_students(guardian_id, school_year_id=None):
    """
    Lấy danh sách học sinh của phụ huynh.
    Sử dụng CRM Family Relationship giống re_enrollment.
    Nếu có school_year_id thì chỉ lấy lớp của năm học đó.
    """
    if not guardian_id:
        return []
    
    # Lấy từ CRM Family Relationship
    relationships = frappe.get_all(
        "CRM Family Relationship",
        filters={"guardian": guardian_id},
        fields=["student"]
    )
    
    if not relationships:
        return []
    
    student_ids = [r.student for r in relationships]
    
    # Build query với filter năm học nếu có
    school_year_filter = ""
    params = {"student_ids": student_ids}
    
    if school_year_id:
        school_year_filter = "AND c.school_year_id = %(school_year_id)s"
        params["school_year_id"] = school_year_id
    
    # Lấy thông tin chi tiết học sinh với lớp
    # Sử dụng subquery để lấy lớp chính (regular) đầu tiên của học sinh, tránh duplicate
    students = frappe.db.sql(f"""
        SELECT 
            s.name as student_id,
            s.student_name,
            s.student_code,
            c.name as class_id,
            c.title as class_name,
            c.education_grade,
            eg.education_stage_id,
            es.title_vn as education_stage_name,
            c.homeroom_teacher
        FROM `tabCRM Student` s
        LEFT JOIN (
            SELECT cs1.student_id, MIN(cs1.class_id) as class_id
            FROM `tabSIS Class Student` cs1
            INNER JOIN `tabSIS Class` c1 ON cs1.class_id = c1.name
            WHERE (c1.class_type = 'regular' OR c1.class_type IS NULL OR c1.class_type = '')
                {"AND c1.school_year_id = %(school_year_id)s" if school_year_id else ""}
            GROUP BY cs1.student_id
        ) cs ON s.name = cs.student_id
        LEFT JOIN `tabSIS Class` c ON cs.class_id = c.name
        LEFT JOIN `tabSIS Education Grade` eg ON c.education_grade = eg.name
        LEFT JOIN `tabSIS Education Stage` es ON eg.education_stage_id = es.name
        WHERE s.name IN %(student_ids)s
        ORDER BY s.student_name
    """, params, as_dict=True)
    
    # Lấy tên GVCN riêng để tránh lỗi JOIN phức tạp
    for student in students:
        homeroom_teacher_name = None
        if student.get('homeroom_teacher'):
            try:
                teacher = frappe.get_doc("SIS Teacher", student['homeroom_teacher'])
                if teacher.user_id:
                    user = frappe.get_doc("User", teacher.user_id)
                    homeroom_teacher_name = user.full_name
            except Exception:
                pass
        student['homeroom_teacher_name'] = homeroom_teacher_name
    
    return students


# ==================== PUBLIC APIs ====================

@frappe.whitelist()
def get_active_period():
    """
    Lấy kỳ học bổng đang mở và danh sách học sinh có thể đăng ký.
    """
    logs = []
    
    try:
        # Lấy guardian
        guardian_id = _get_current_guardian()
        if not guardian_id:
            return error_response("Không tìm thấy thông tin phụ huynh", logs=logs)
        
        # Tìm kỳ học bổng đang Open
        today = nowdate()
        period = frappe.db.sql("""
            SELECT name, title, academic_year_id, campus_id, status, from_date, to_date
            FROM `tabSIS Scholarship Period`
            WHERE status = 'Open'
              AND from_date <= %(today)s
              AND to_date >= %(today)s
            ORDER BY from_date DESC
            LIMIT 1
        """, {"today": today}, as_dict=True)
        
        if not period:
            # Kiểm tra có kỳ sắp mở không
            upcoming = frappe.db.sql("""
                SELECT name, title, from_date, to_date, status
                FROM `tabSIS Scholarship Period`
                WHERE status = 'Open'
                  AND from_date > %(today)s
                ORDER BY from_date ASC
                LIMIT 1
            """, {"today": today}, as_dict=True)
            
            if upcoming:
                return success_response(
                    data={
                        "status": "not_started",
                        "message": "Chưa đến thời gian đăng ký học bổng",
                        "start_date": str(upcoming[0].from_date) if upcoming[0].from_date else None
                    }
                )
            
            # Kiểm tra có kỳ đã đóng không
            closed = frappe.db.sql("""
                SELECT name, title, to_date
                FROM `tabSIS Scholarship Period`
                WHERE status = 'Open'
                  AND to_date < %(today)s
                ORDER BY to_date DESC
                LIMIT 1
            """, {"today": today}, as_dict=True)
            
            if closed:
                return success_response(
                    data={
                        "status": "ended",
                        "message": "Đã hết thời gian đăng ký học bổng"
                    }
                )
            
            return success_response(
                data={
                    "status": "no_period",
                    "message": "Không có kỳ học bổng nào đang mở"
                }
            )
        
        period_data = period[0]
        period_doc = frappe.get_doc("SIS Scholarship Period", period_data.name)
        
        # Lấy danh sách cấp học được áp dụng
        allowed_stages = [stage.educational_stage_id for stage in period_doc.education_stages]
        
        # Lấy thông tin năm học
        school_year = frappe.db.get_value(
            "SIS School Year",
            period_data.academic_year_id,
            ["title_vn", "title_en"],
            as_dict=True
        )
        
        # Lấy danh sách học sinh của phụ huynh (filter theo năm học của kỳ học bổng)
        all_students = _get_guardian_students(guardian_id, period_data.academic_year_id)
        
        # Lọc học sinh theo cấp học được áp dụng và kiểm tra đã đăng ký chưa
        students = []
        for student in all_students:
            # Kiểm tra cấp học
            if student.education_stage_id and student.education_stage_id not in allowed_stages:
                continue
            
            # Kiểm tra đã đăng ký chưa
            existing_app = frappe.db.get_value(
                "SIS Scholarship Application",
                {
                    "scholarship_period_id": period_data.name,
                    "student_id": student.student_id
                },
                ["name", "status"],
                as_dict=True
            )
            
            student_info = {
                "name": student.student_id,
                "student_name": student.student_name,
                "student_code": student.student_code,
                "class_id": student.class_id,
                "class_name": student.class_name,
                "education_stage_id": student.education_stage_id,
                "education_stage_name": student.education_stage_name,
                "homeroom_teacher": student.homeroom_teacher,
                "homeroom_teacher_name": student.homeroom_teacher_name,
                "has_submitted": existing_app is not None,
                "submission": None
            }
            
            if existing_app:
                student_info["submission"] = {
                    "name": existing_app.name,
                    "status": existing_app.status
                }
            
            students.append(student_info)
        
        logs.append(f"Tìm thấy kỳ {period_data.name}, {len(students)} học sinh có thể đăng ký")
        
        return success_response(
            data={
                "status": "open",
                "config": {
                    "name": period_data.name,
                    "title": period_data.title,
                    "academic_year_id": period_data.academic_year_id,
                    "school_year_name_vn": school_year.title_vn if school_year else None,
                    "school_year_name_en": school_year.title_en if school_year else None,
                    "from_date": str(period_data.from_date) if period_data.from_date else None,
                    "to_date": str(period_data.to_date) if period_data.to_date else None
                },
                "students": students
            }
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Parent Portal Get Active Scholarship Period Error")
        return error_response(
            message=f"Lỗi khi lấy thông tin kỳ học bổng: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def get_teachers_for_class(class_id=None):
    """
    Lấy danh sách giáo viên dạy một lớp để PHHS chọn làm người giới thiệu thứ 2.
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
        
        # Lấy GVCN
        class_info = frappe.db.get_value(
            "SIS Class",
            class_id,
            ["homeroom_teacher", "school_year_id"],
            as_dict=True
        )
        
        homeroom_teacher_id = class_info.homeroom_teacher if class_info else None
        
        # Lấy danh sách GV dạy lớp này từ timetable
        teachers = frappe.db.sql("""
            SELECT DISTINCT 
                t.name as teacher_id,
                u.full_name as teacher_name
            FROM `tabSIS Teacher` t
            INNER JOIN `tabUser` u ON t.user_id = u.name
            INNER JOIN `tabSIS Timetable Instance Row` tir ON t.name = tir.teacher_id
            INNER JOIN `tabSIS Timetable Instance` ti ON tir.parent = ti.name
            WHERE ti.class_id = %(class_id)s
              AND t.name != %(homeroom_id)s
            ORDER BY u.full_name
        """, {
            "class_id": class_id,
            "homeroom_id": homeroom_teacher_id or ""
        }, as_dict=True)
        
        # Lấy thông tin GVCN từ User
        homeroom_info = None
        if homeroom_teacher_id:
            homeroom_data = frappe.db.sql("""
                SELECT t.name as teacher_id, u.full_name as teacher_name
                FROM `tabSIS Teacher` t
                INNER JOIN `tabUser` u ON t.user_id = u.name
                WHERE t.name = %(teacher_id)s
            """, {"teacher_id": homeroom_teacher_id}, as_dict=True)
            if homeroom_data:
                homeroom_info = homeroom_data[0]
        
        return success_response(
            data={
                "homeroom_teacher": homeroom_info,
                "subject_teachers": teachers
            },
            message="Lấy danh sách giáo viên thành công"
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Get Teachers For Class Error")
        return error_response(
            message=f"Lỗi: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def submit_application():
    """
    PHHS nộp đơn đăng ký học bổng cho con.
    """
    logs = []
    
    try:
        # Lấy guardian
        guardian_id = _get_current_guardian()
        if not guardian_id:
            return error_response("Không tìm thấy thông tin phụ huynh", logs=logs)
        
        # Lấy data từ request
        if frappe.request.is_json:
            data = frappe.request.json or {}
        else:
            data = frappe.form_dict
        
        student_id = data.get('student_id')
        period_id = data.get('period_id')
        
        if not student_id:
            return validation_error_response(
                "Thiếu student_id",
                {"student_id": ["Student ID là bắt buộc"]}
            )
        
        if not period_id:
            return validation_error_response(
                "Thiếu period_id",
                {"period_id": ["Period ID là bắt buộc"]}
            )
        
        logs.append(f"PHHS {guardian_id} đăng ký học bổng cho {student_id}")
        
        # Kiểm tra học sinh thuộc về phụ huynh này
        students = _get_guardian_students(guardian_id)
        student_ids = [s['student_id'] for s in students]
        
        if student_id not in student_ids:
            return error_response("Học sinh này không thuộc quyền quản lý của bạn", logs=logs)
        
        # Lấy thông tin học sinh
        student_info = next((s for s in students if s['student_id'] == student_id), None)
        
        # Kiểm tra đã đăng ký chưa
        existing = frappe.db.exists("SIS Scholarship Application", {
            "scholarship_period_id": period_id,
            "student_id": student_id
        })
        
        if existing:
            return error_response("Học sinh này đã đăng ký học bổng rồi", logs=logs)
        
        # Kiểm tra kỳ học bổng
        period = frappe.get_doc("SIS Scholarship Period", period_id)
        if period.status != "Open":
            return error_response("Kỳ học bổng này chưa mở hoặc đã đóng", logs=logs)
        
        if not period.is_within_period():
            return error_response("Không trong thời gian đăng ký", logs=logs)
        
        # Tạo đơn đăng ký
        app = frappe.get_doc({
            "doctype": "SIS Scholarship Application",
            "scholarship_period_id": period_id,
            "student_id": student_id,
            "class_id": student_info.get('class_id'),
            "education_stage_id": student_info.get('education_stage_id'),
            "guardian_id": guardian_id,
            "main_teacher_id": data.get('main_teacher_id') or student_info.get('homeroom_teacher'),
            "second_teacher_id": data.get('second_teacher_id'),
            "academic_report_type": data.get('academic_report_type', 'existing'),
            "academic_report_link": data.get('academic_report_link'),
            "academic_report_upload": data.get('academic_report_upload'),
            "video_url": data.get('video_url'),
            "status": "Submitted"
        })
        
        # Thêm thành tích
        achievements = data.get('achievements', [])
        if isinstance(achievements, str):
            achievements = json.loads(achievements)
        
        for ach in achievements:
            app.append("achievements", {
                "achievement_type": ach.get('achievement_type'),
                "title": ach.get('title'),
                "description": ach.get('description'),
                "organization": ach.get('organization'),
                "role": ach.get('role'),
                "result": ach.get('result'),
                "date_received": ach.get('date_received'),
                "attachment": ach.get('attachment')
            })
        
        app.insert()
        frappe.db.commit()
        
        logs.append(f"Đã tạo đơn đăng ký: {app.name}")
        
        return success_response(
            data={
                "name": app.name,
                "status": app.status
            },
            message="Đăng ký học bổng thành công",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Parent Portal Submit Scholarship Application Error")
        return error_response(
            message=f"Lỗi khi đăng ký học bổng: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def get_my_applications():
    """
    Lấy danh sách đơn đăng ký học bổng của các con.
    """
    logs = []
    
    try:
        # Lấy guardian
        guardian_id = _get_current_guardian()
        if not guardian_id:
            return error_response("Không tìm thấy thông tin phụ huynh", logs=logs)
        
        # Lấy danh sách đơn
        applications = frappe.db.sql("""
            SELECT 
                app.name, app.scholarship_period_id, app.student_id, app.student_name,
                app.student_code, app.class_name, app.status, app.submitted_at,
                app.total_score, app.total_percentage,
                app.main_recommendation_status, app.second_recommendation_status,
                p.title as period_title
            FROM `tabSIS Scholarship Application` app
            INNER JOIN `tabSIS Scholarship Period` p ON app.scholarship_period_id = p.name
            WHERE app.guardian_id = %(guardian_id)s
            ORDER BY app.submitted_at DESC
        """, {"guardian_id": guardian_id}, as_dict=True)
        
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
        
        logs.append(f"Tìm thấy {len(applications)} đơn")
        
        return list_response(applications)
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Parent Portal Get My Scholarship Applications Error")
        return error_response(
            message=f"Lỗi: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def get_application_status(application_id=None):
    """
    Lấy trạng thái chi tiết một đơn đăng ký.
    """
    logs = []
    
    try:
        # Lấy guardian
        guardian_id = _get_current_guardian()
        if not guardian_id:
            return error_response("Không tìm thấy thông tin phụ huynh", logs=logs)
        
        if not application_id:
            application_id = frappe.request.args.get('application_id')
        
        if not application_id:
            return validation_error_response(
                "Thiếu application_id",
                {"application_id": ["Application ID là bắt buộc"]}
            )
        
        # Kiểm tra quyền truy cập
        app = frappe.db.get_value(
            "SIS Scholarship Application",
            application_id,
            ["name", "guardian_id", "student_name", "student_code", "class_name",
             "status", "submitted_at", "main_teacher_name", "second_teacher_name",
             "main_recommendation_status", "second_recommendation_status",
             "rejection_reason"],
            as_dict=True
        )
        
        if not app:
            return not_found_response("Không tìm thấy đơn đăng ký")
        
        if app.guardian_id != guardian_id:
            return error_response("Bạn không có quyền xem đơn này", logs=logs)
        
        # Thêm display values
        status_display_map = {
            "Submitted": "Đã nộp",
            "WaitingRecommendation": "Chờ thư giới thiệu",
            "RecommendationSubmitted": "Đã có thư giới thiệu",
            "InReview": "Đang xét duyệt",
            "Approved": "Đã duyệt",
            "Rejected": "Không đạt",
            "DeniedByTeacher": "Giáo viên từ chối"
        }
        
        rec_status_map = {
            "Pending": "Chờ viết thư",
            "Submitted": "Đã viết thư",
            "Denied": "Từ chối"
        }
        
        return single_item_response(
            data={
                "name": app.name,
                "student_name": app.student_name,
                "student_code": app.student_code,
                "class_name": app.class_name,
                "status": app.status,
                "status_display": status_display_map.get(app.status, app.status),
                "submitted_at": str(app.submitted_at) if app.submitted_at else None,
                "main_teacher_name": app.main_teacher_name,
                "main_recommendation_status": app.main_recommendation_status,
                "main_recommendation_display": rec_status_map.get(app.main_recommendation_status, app.main_recommendation_status),
                "second_teacher_name": app.second_teacher_name,
                "second_recommendation_status": app.second_recommendation_status,
                "second_recommendation_display": rec_status_map.get(app.second_recommendation_status, app.second_recommendation_status) if app.second_recommendation_status else None,
                "rejection_reason": app.rejection_reason
            },
            message="Lấy trạng thái đơn thành công"
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Parent Portal Get Application Status Error")
        return error_response(
            message=f"Lỗi: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def submit_application_with_files():
    """
    PHHS nộp đơn đăng ký học bổng với file uploads.
    Hỗ trợ upload:
    - Báo cáo học tập kì 1, kì 2
    - Chứng chỉ cho từng loại thành tích
    """
    logs = []
    
    try:
        # Lấy guardian
        guardian_id = _get_current_guardian()
        if not guardian_id:
            return error_response("Không tìm thấy thông tin phụ huynh", logs=logs)
        
        # Lấy data từ form (hỗ trợ cả multipart/form-data)
        # Ưu tiên frappe.request.form cho multipart, fallback sang frappe.form_dict
        def get_form_value(key):
            """Lấy giá trị từ form, hỗ trợ multipart/form-data"""
            if hasattr(frappe.request, 'form') and frappe.request.form:
                value = frappe.request.form.get(key)
                if value:
                    return value
            return frappe.form_dict.get(key)
        
        student_id = get_form_value('student_id')
        period_id = get_form_value('period_id')
        
        if not student_id:
            return validation_error_response(
                "Thiếu student_id",
                {"student_id": ["Student ID là bắt buộc"]}
            )
        
        if not period_id:
            return validation_error_response(
                "Thiếu period_id",
                {"period_id": ["Period ID là bắt buộc"]}
            )
        
        logs.append(f"PHHS {guardian_id} đăng ký học bổng cho {student_id}")
        
        # Kiểm tra học sinh thuộc về phụ huynh này
        students = _get_guardian_students(guardian_id)
        student_ids = [s['student_id'] for s in students]
        
        if student_id not in student_ids:
            return error_response("Học sinh này không thuộc quyền quản lý của bạn", logs=logs)
        
        # Lấy thông tin học sinh
        student_info = next((s for s in students if s['student_id'] == student_id), None)
        
        # Kiểm tra đã đăng ký chưa
        existing = frappe.db.exists("SIS Scholarship Application", {
            "scholarship_period_id": period_id,
            "student_id": student_id
        })
        
        if existing:
            return error_response("Học sinh này đã đăng ký học bổng rồi", logs=logs)
        
        # Kiểm tra kỳ học bổng
        period = frappe.get_doc("SIS Scholarship Period", period_id)
        if period.status != "Open":
            return error_response("Kỳ học bổng này chưa mở hoặc đã đóng", logs=logs)
        
        if not period.is_within_period():
            return error_response("Không trong thời gian đăng ký", logs=logs)
        
        # Helper function để tạo folder nếu chưa tồn tại
        def ensure_folder_exists(folder_path):
            """Tạo folder nếu chưa tồn tại, hỗ trợ nested folders"""
            parts = folder_path.split('/')
            current_path = "Home"
            
            for part in parts:
                if not part:
                    continue
                next_path = f"{current_path}/{part}"
                if not frappe.db.exists("File", {"is_folder": 1, "file_name": next_path}):
                    try:
                        folder_doc = frappe.get_doc({
                            "doctype": "File",
                            "file_name": part,
                            "is_folder": 1,
                            "folder": current_path
                        })
                        folder_doc.insert(ignore_permissions=True)
                    except frappe.DuplicateEntryError:
                        pass  # Folder đã tồn tại
                current_path = next_path
            
            return current_path
        
        # Helper function để upload file
        def upload_file(file_key, folder="Scholarship"):
            """Upload file và trả về file URL"""
            if file_key not in frappe.request.files:
                return None
            
            file = frappe.request.files[file_key]
            if not file or not file.filename:
                return None
            
            # Đảm bảo folder tồn tại
            folder_path = ensure_folder_exists(folder)
            
            # Lưu file
            file_doc = frappe.get_doc({
                "doctype": "File",
                "file_name": file.filename,
                "folder": folder_path,
                "is_private": 0,
                "content": file.read()
            })
            file_doc.insert(ignore_permissions=True)
            
            return file_doc.file_url
        
        # Upload báo cáo học tập
        semester1_report_url = upload_file('semester1_report', 'Scholarship/Reports')
        semester2_report_url = upload_file('semester2_report', 'Scholarship/Reports')
        
        # Gộp link báo cáo học tập
        report_links = []
        if semester1_report_url:
            report_links.append(f"Kì 1: {semester1_report_url}")
        if semester2_report_url:
            report_links.append(f"Kì 2: {semester2_report_url}")
        
        # Upload video giới thiệu
        video_url = upload_file('video_file', 'Scholarship/Videos')
        
        # Tạo đơn đăng ký
        app = frappe.get_doc({
            "doctype": "SIS Scholarship Application",
            "scholarship_period_id": period_id,
            "student_id": student_id,
            "class_id": student_info.get('class_id'),
            "education_stage_id": student_info.get('education_stage_id'),
            "guardian_id": guardian_id,
            "main_teacher_id": get_form_value('main_teacher_id') or student_info.get('homeroom_teacher'),
            "second_teacher_id": get_form_value('second_teacher_id'),
            "academic_report_type": 'upload' if report_links else 'existing',
            "academic_report_upload": ' | '.join(report_links) if report_links else None,
            "video_url": video_url,
            "status": "Submitted"
        })
        
        # Parse và thêm thành tích - Bài thi chuẩn hóa
        standardized_tests = get_form_value('standardized_tests')
        if standardized_tests:
            try:
                tests = json.loads(standardized_tests)
                for idx, content in enumerate(tests):
                    file_url = upload_file(f'standardized_test_file_{idx}', 'Scholarship/Certificates')
                    app.append("achievements", {
                        "achievement_type": "standardized_test",
                        "title": content,
                        "attachment": file_url
                    })
            except json.JSONDecodeError:
                pass
        
        # Parse và thêm thành tích - Giải thưởng
        awards_data = get_form_value('awards')
        if awards_data:
            try:
                awards_list = json.loads(awards_data)
                for idx, content in enumerate(awards_list):
                    file_url = upload_file(f'award_file_{idx}', 'Scholarship/Certificates')
                    app.append("achievements", {
                        "achievement_type": "award",
                        "title": content,
                        "attachment": file_url
                    })
            except json.JSONDecodeError:
                pass
        
        # Parse và thêm thành tích - Hoạt động ngoại khóa
        extracurriculars_data = get_form_value('extracurriculars')
        if extracurriculars_data:
            try:
                extracurriculars_list = json.loads(extracurriculars_data)
                for idx, content in enumerate(extracurriculars_list):
                    file_url = upload_file(f'extracurricular_file_{idx}', 'Scholarship/Certificates')
                    app.append("achievements", {
                        "achievement_type": "extracurricular",
                        "title": content,
                        "attachment": file_url
                    })
            except json.JSONDecodeError:
                pass
        
        app.insert()
        frappe.db.commit()
        
        logs.append(f"Đã tạo đơn đăng ký: {app.name}")
        
        return success_response(
            data={
                "name": app.name,
                "status": app.status
            },
            message="Đăng ký học bổng thành công",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Parent Portal Submit Scholarship With Files Error")
        return error_response(
            message=f"Lỗi khi đăng ký học bổng: {str(e)}",
            logs=logs
        )
