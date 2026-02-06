"""
Parent Portal Scholarship API
Handles scholarship registration for parents

API endpoints cho phụ huynh đăng ký học bổng.
"""

import frappe
from frappe import _
from frappe.utils import nowdate, getdate, now
import json
import requests
from erp.utils.api_response import (
    validation_error_response, 
    list_response, 
    error_response, 
    success_response, 
    single_item_response,
    not_found_response
)


def _send_email_via_service(to_list, subject, body):
    """
    Gửi email qua email service GraphQL API
    
    Args:
        to_list: danh sách email recipients
        subject: tiêu đề email
        body: nội dung email HTML
    """
    try:
        # Lấy URL email service từ config hoặc mặc định
        email_service_url = frappe.conf.get('email_service_url') or 'http://localhost:5030'
        graphql_endpoint = f"{email_service_url}/graphql"
        
        # GraphQL mutation
        graphql_query = """
        mutation SendEmail($input: SendEmailInput!) {
            sendEmail(input: $input) {
                success
                message
                messageId
            }
        }
        """
        
        variables = {
            "input": {
                "to": to_list,
                "subject": subject,
                "body": body,
                "contentType": "HTML"
            }
        }
        
        payload = {
            "query": graphql_query,
            "variables": variables
        }
        
        # Gửi request đến email service
        response = requests.post(
            graphql_endpoint,
            json=payload,
            headers={'Content-Type': 'application/json'},
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            if result.get('errors'):
                frappe.logger().error(f"GraphQL errors: {result['errors']}")
                return {"success": False, "message": str(result['errors'])}
            
            send_result = result.get('data', {}).get('sendEmail')
            if send_result and send_result.get('success'):
                frappe.logger().info(f"Email sent successfully to {to_list}")
                return {"success": True, "message": "Email sent"}
        
        frappe.logger().error(f"Email service error: {response.status_code}")
        return {"success": False, "message": f"HTTP {response.status_code}"}
        
    except Exception as e:
        frappe.logger().error(f"Error sending email: {str(e)}")
        return {"success": False, "message": str(e)}


def _build_scholarship_email(teacher_name, student_name, student_code, class_name, portal_link, deadline_str):
    """
    Tạo subject và body email yêu cầu viết thư giới thiệu học bổng (song ngữ Việt-Anh).
    
    Args:
        teacher_name: tên giáo viên
        student_name: tên học sinh
        student_code: mã học sinh
        class_name: tên lớp
        portal_link: link portal giáo viên (đến tab scholarship)
        deadline_str: hạn chót gửi thư (format dd/mm/yyyy cho VN, Month dd, yyyy cho EN)
    
    Returns:
        tuple (subject, body_html)
    """
    subject = (
        f"Yêu cầu viết thư giới thiệu – Học bổng Tài năng Wellspring 2026-2027 | "
        f"Request for Letter of Recommendation – 2026-2027 Wellspring Talent Scholarship"
    )
    
    body = f"""
    <div style="font-family: Arial, sans-serif; max-width: 700px; margin: 0 auto; color: #333; line-height: 1.7;">
        <!-- Phần tiếng Việt -->
        <p style="color: #888; font-style: italic; margin-bottom: 20px;">[English version below]</p>

        <p>Kính gửi Thầy/Cô <strong>{teacher_name}</strong>,</p>

        <p>Hội đồng Thi đua Khen thưởng Wellspring Hanoi trân trọng thông báo:</p>

        <p>Học sinh <strong>{student_name}</strong> (Mã học sinh: <strong>{student_code}</strong>, lớp <strong>{class_name}</strong>) đã nộp hồ sơ đăng ký Học bổng Tài năng Wellspring Năm học 2026-2027 và lựa chọn Thầy/Cô là giáo viên viết thư giới thiệu cho học sinh.</p>

        <p>Thầy/Cô vui lòng đăng nhập hệ thống Portal để viết và gửi thư giới thiệu trước <strong>17h00 ngày {deadline_str}</strong>.</p>

        <div style="background: #f5f7fa; border-left: 4px solid #1976d2; padding: 16px 20px; margin: 24px 0; border-radius: 4px;">
            <p style="margin: 0 0 12px 0; font-weight: bold;">📝 HƯỚNG DẪN GỬI THƯ GIỚI THIỆU:</p>
            <p style="margin: 4px 0;">1️⃣ Truy cập Portal theo đường link:<br>&nbsp;&nbsp;&nbsp;&nbsp;👉 <a href="{portal_link}" style="color: #1976d2;">{portal_link}</a></p>
            <p style="margin: 4px 0;">2️⃣ Đăng nhập bằng tài khoản giáo viên của Thầy/Cô</p>
            <p style="margin: 4px 0;">3️⃣ Tại menu mục "Giảng dạy", nhấn "Lớp học" → Chọn lớp của học sinh → "Học bổng"</p>
            <p style="margin: 4px 0;">4️⃣ Chọn "Viết thư" cho học sinh tương ứng</p>
            <p style="margin: 4px 0;">5️⃣ Nhập điểm đánh giá và nhận xét → Nhấn "Gửi thư giới thiệu"</p>
            <p style="margin: 4px 0;">6️⃣ Sau khi Thầy/Cô gửi thư giới thiệu thành công, hệ thống Portal sẽ tự động cập nhật trạng thái thư từ "Viết thư" sang "Đã hoàn thành"</p>
        </div>

        <p>Nếu Thầy/Cô có bất kỳ thắc mắc nào hoặc cần hỗ trợ, vui lòng liên hệ qua email: <a href="mailto:hocbong@wellspring.edu.vn" style="color: #1976d2;">hocbong@wellspring.edu.vn</a>.</p>

        <p>Xin chân thành cảm ơn sự hỗ trợ và hợp tác của Thầy/Cô!</p>

        <p>Trân trọng,<br><strong>Hội đồng Thi đua Khen thưởng Wellspring Hanoi</strong></p>

        <hr style="border: none; border-top: 2px solid #ddd; margin: 36px 0;">

        <!-- Phần tiếng Anh -->
        <p>Dear <strong>{teacher_name}</strong>,</p>

        <p>The Wellspring Hanoi Emulation and Reward Committee would like to inform you that:</p>

        <p>Student <strong>{student_name}</strong> (Student ID: <strong>{student_code}</strong>, Class: <strong>{class_name}</strong>) has submitted their application for the 2026-2027 Wellspring Talent Scholarship and has selected you as their recommender.</p>

        <p>We kindly ask that you log in to the Portal system to complete and submit the letter of recommendation by <strong>5:00 PM on {deadline_str}</strong>.</p>

        <div style="background: #f5f7fa; border-left: 4px solid #1976d2; padding: 16px 20px; margin: 24px 0; border-radius: 4px;">
            <p style="margin: 0 0 12px 0; font-weight: bold;">📝 INSTRUCTIONS FOR SUBMITTING THE LETTER OF RECOMMENDATION:</p>
            <p style="margin: 4px 0;">1️⃣ Access the Portal via the following link:<br>&nbsp;&nbsp;&nbsp;&nbsp;👉 <a href="{portal_link}" style="color: #1976d2;">{portal_link}</a></p>
            <p style="margin: 4px 0;">2️⃣ Log in using your teacher account</p>
            <p style="margin: 4px 0;">3️⃣ From the menu, under "Teaching" → click "Classes" → Choose the student's class → click "Scholarship"</p>
            <p style="margin: 4px 0;">4️⃣ Select "Write Letter" for the corresponding student</p>
            <p style="margin: 4px 0;">5️⃣ Enter your evaluation scores and comments → Click "Submit"</p>
            <p style="margin: 4px 0;">6️⃣ Once the letter has been successfully submitted, the Portal system will automatically update the status from "Write Letter" to "Completed."</p>
        </div>

        <p>Should you have any questions or require further assistance, please contact us at <a href="mailto:hocbong@wellspring.edu.vn" style="color: #1976d2;">hocbong@wellspring.edu.vn</a>.</p>

        <p>Thank you very much for your support and cooperation.</p>

        <p>Sincerely,<br><strong>The Wellspring Hanoi Emulation and Reward Committee</strong></p>
    </div>
    """
    
    return subject, body


def _get_teacher_email_info(teacher_id):
    """
    Lấy email và tên giáo viên từ teacher_id.
    
    Returns:
        tuple (email, teacher_name) hoặc (None, None) nếu không tìm thấy
    """
    try:
        teacher = frappe.get_doc("SIS Teacher", teacher_id, ignore_permissions=True)
        if not teacher.user_id:
            frappe.logger().warning(f"[Scholarship Email] Teacher {teacher_id} không có user_id")
            return None, None
        
        # Dùng ignore_permissions vì API được gọi bởi parent user, 
        # parent có thể không có quyền đọc User doctype
        user = frappe.get_doc("User", teacher.user_id, ignore_permissions=True)
        if not user.email or user.email == 'Administrator':
            frappe.logger().warning(f"[Scholarship Email] Teacher {teacher_id} user {teacher.user_id} không có email hợp lệ")
            return None, None
        
        teacher_name = teacher.teacher_name or user.full_name or teacher_id
        return user.email, teacher_name
    except Exception as e:
        frappe.logger().error(f"[Scholarship Email] Lỗi lấy thông tin GV {teacher_id}: {str(e)}")
        return None, None


def _get_period_deadline_str(period_id):
    """
    Lấy deadline (to_date) từ kỳ học bổng, trả về chuỗi format dd/mm/yyyy.
    Fallback nếu không có to_date.
    """
    try:
        to_date = frappe.db.get_value("SIS Scholarship Period", period_id, "to_date")
        if to_date:
            d = getdate(to_date)
            return d.strftime("%d/%m/%Y")
    except Exception:
        pass
    return "theo thông báo"


def _send_scholarship_notification_to_teachers(app, student_info, is_new=True):
    """
    Gửi email thông báo đến giáo viên về đơn học bổng mới.
    Dùng template song ngữ Việt-Anh.
    
    Args:
        app: SIS Scholarship Application document
        student_info: thông tin học sinh (từ _get_guardian_students)
        is_new: True nếu đơn mới, False nếu cập nhật
    """
    try:
        # Lấy danh sách giáo viên cần gửi email
        teacher_ids = []
        if app.main_teacher_id:
            teacher_ids.append(app.main_teacher_id)
        if app.second_teacher_id:
            teacher_ids.append(app.second_teacher_id)
        
        if not teacher_ids:
            frappe.logger().info("No teachers to notify for scholarship application")
            return
        
        # Lấy thông tin học sinh
        student_name = student_info.get('student_name') or student_info.get('student_id') or ''
        student_code = student_info.get('student_code') or ''
        class_name = student_info.get('class_name') or ''
        class_id = student_info.get('class_id') or app.class_id
        
        # URL portal giáo viên - tab scholarship trong trang ClassInfo
        portal_url = frappe.conf.get('teacher_portal_url') or 'https://wis.wellspring.edu.vn'
        portal_link = f"{portal_url}/teaching/classes/{class_id}?tab=scholarship"
        
        # Lấy deadline từ kỳ học bổng
        deadline_str = _get_period_deadline_str(app.scholarship_period_id)
        
        # Gửi email cho từng giáo viên
        for teacher_id in teacher_ids:
            teacher_email, teacher_name = _get_teacher_email_info(teacher_id)
            if not teacher_email:
                frappe.logger().warning(f"Could not get email for teacher {teacher_id}")
                continue
            
            subject, body = _build_scholarship_email(
                teacher_name=teacher_name,
                student_name=student_name,
                student_code=student_code,
                class_name=class_name,
                portal_link=portal_link,
                deadline_str=deadline_str
            )
            
            result = _send_email_via_service([teacher_email], subject, body)
            if result.get('success'):
                frappe.logger().info(f"Scholarship notification sent to {teacher_email}")
            else:
                frappe.logger().warning(f"Failed to send scholarship notification to {teacher_email}: {result.get('message')}")
        
    except Exception as e:
        frappe.logger().error(f"Error sending scholarship notification: {str(e)}")
        # Không raise exception để không ảnh hưởng đến luồng chính


def _send_email_to_changed_teachers(app, student_info, changed_teachers, logs):
    """
    Gửi email thông báo đến giáo viên MỚI khi phụ huynh thay đổi giáo viên viết thư giới thiệu.
    Chỉ gửi cho giáo viên mới được thay đổi, không gửi lại cho giáo viên không thay đổi.
    Dùng template song ngữ Việt-Anh.
    
    Args:
        app: SIS Scholarship Application document
        student_info: thông tin học sinh (từ _get_guardian_students)
        changed_teachers: list of tuples (recommendation_type, teacher_id) cho giáo viên thay đổi
        logs: list để ghi log
    """
    try:
        if not changed_teachers:
            return
        
        # Lấy thông tin học sinh
        student_name = student_info.get('student_name') or student_info.get('student_id') or ''
        student_code = student_info.get('student_code') or ''
        class_name = student_info.get('class_name') or ''
        class_id = student_info.get('class_id') or app.class_id
        
        # URL portal giáo viên
        portal_url = frappe.conf.get('teacher_portal_url') or 'https://wis.wellspring.edu.vn'
        portal_link = f"{portal_url}/teaching/classes/{class_id}?tab=scholarship"
        
        # Lấy deadline từ kỳ học bổng
        deadline_str = _get_period_deadline_str(app.scholarship_period_id)
        
        logs.append(f"[DEBUG Email] student={student_name}, class={class_name}, deadline={deadline_str}, portal={portal_link}")
        
        for rec_type, teacher_id in changed_teachers:
            try:
                logs.append(f"[DEBUG Email] Xử lý GV: {teacher_id} ({rec_type})")
                teacher_email, teacher_name = _get_teacher_email_info(teacher_id)
                if not teacher_email:
                    logs.append(f"[DEBUG Email] GV {teacher_id} không có email hợp lệ hoặc user_id")
                    continue
                
                logs.append(f"[DEBUG Email] Gửi email đến: {teacher_email} ({teacher_name})")
                
                subject, body = _build_scholarship_email(
                    teacher_name=teacher_name,
                    student_name=student_name,
                    student_code=student_code,
                    class_name=class_name,
                    portal_link=portal_link,
                    deadline_str=deadline_str
                )
                
                result = _send_email_via_service([teacher_email], subject, body)
                if result.get('success'):
                    logs.append(f"✅ Đã gửi email thông báo đến GV mới: {teacher_email} ({teacher_name})")
                else:
                    logs.append(f"❌ Không thể gửi email đến {teacher_email}: {result.get('message')}")
                    
            except Exception as e:
                logs.append(f"❌ Lỗi khi gửi email cho GV {teacher_id}: {str(e)}")
                continue
        
    except Exception as e:
        frappe.logger().error(f"Error sending email to changed teachers: {str(e)}")
        # Ghi log vào logs nếu có
        if logs is not None:
            logs.append(f"❌ [DEBUG Email] Exception ngoài cùng: {str(e)}")


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
    
    # Lấy năm học hiện tại để lấy ảnh
    current_school_year = frappe.db.get_value(
        "SIS School Year",
        {"is_enable": 1},
        "name",
        order_by="start_date desc"
    )
    
    # Lấy tên GVCN và ảnh học sinh riêng
    for student in students:
        # Lấy tên GVCN
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
        
        # Lấy ảnh học sinh từ SIS Photo (giống logic trong re_enrollment.py)
        sis_photo = None
        try:
            # Ưu tiên: 1) Năm học hiện tại trước, 2) Upload date mới nhất, 3) Creation mới nhất
            sis_photos = frappe.db.sql("""
                SELECT photo, title, upload_date, school_year_id
                FROM `tabSIS Photo`
                WHERE student_id = %s
                    AND type = 'student'
                    AND status = 'Active'
                ORDER BY 
                    CASE WHEN school_year_id = %s THEN 0 ELSE 1 END,
                    upload_date DESC,
                    creation DESC
                LIMIT 1
            """, (student.student_id, current_school_year), as_dict=True)

            if sis_photos:
                sis_photo = sis_photos[0]["photo"]
        except Exception as photo_err:
            frappe.logger().error(f"Error getting sis_photo for {student.student_id}: {str(photo_err)}")
        
        student['sis_photo'] = sis_photo
    
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
        
        # Tìm kỳ học bổng được hiển thị trên Parent Portal (độc lập với status và thời gian)
        period = frappe.db.sql("""
            SELECT name, title, academic_year_id, campus_id, status, from_date, to_date
            FROM `tabSIS Scholarship Period`
            WHERE show_on_parent_portal = 1
            ORDER BY modified DESC
            LIMIT 1
        """, as_dict=True)
        
        if not period:
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
                "sis_photo": student.get('sis_photo'),
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
                # Lấy thông tin từ chối nếu có
                denied_info = None
                denied_recommendation = frappe.db.sql("""
                    SELECT 
                        r.name,
                        r.teacher_id,
                        r.recommendation_type,
                        r.denied_reason,
                        r.teacher_name
                    FROM `tabSIS Scholarship Recommendation` r
                    WHERE r.application_id = %(app_id)s
                      AND r.status = 'Denied'
                    ORDER BY r.modified DESC
                    LIMIT 1
                """, {"app_id": existing_app.name}, as_dict=True)
                
                if denied_recommendation:
                    denied_info = {
                        "teacher_id": denied_recommendation[0].teacher_id,
                        "teacher_name": denied_recommendation[0].teacher_name,
                        "recommendation_type": denied_recommendation[0].recommendation_type,
                        "deny_reason": denied_recommendation[0].denied_reason
                    }
                
                student_info["submission"] = {
                    "name": existing_app.name,
                    "status": existing_app.status,
                    "denied_info": denied_info
                }
            
            students.append(student_info)
        
        # Lấy cấu hình hạng mục thành tích
        achievement_categories = []
        for category in period_doc.achievement_categories:
            achievement_categories.append({
                "name": category.name,
                "title_vn": category.title_vn,
                "title_en": category.title_en,
                "description_vn": category.description_vn,
                "description_en": category.description_en,
                "example_vn": category.example_vn,
                "example_en": category.example_en,
                "is_required": category.is_required,
                "sort_order": category.sort_order
            })
        
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
                    "status": period_data.status,  # Trạng thái kỳ: Draft/Open/Closed
                    "from_date": str(period_data.from_date) if period_data.from_date else None,
                    "to_date": str(period_data.to_date) if period_data.to_date else None,
                    "achievement_categories": achievement_categories
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
def get_student_subject_teachers_international(student_id=None):
    """
    Lấy danh sách giáo viên bộ môn của học sinh - CHỈ GIÁO VIÊN DẠY CHƯƠNG TRÌNH QUỐC TẾ.
    Dùng riêng cho trang Scholarship.
    """
    logs = []
    
    try:
        if not student_id:
            student_id = frappe.request.args.get('student_id')
        
        if not student_id:
            return validation_error_response(
                "Thiếu student_id",
                {"student_id": ["Student ID là bắt buộc"]}
            )
        
        logs.append(f"🔍 Getting International curriculum teachers for student: {student_id}")
        
        # ID của chương trình Quốc tế
        INTERNATIONAL_CURRICULUM_ID = "SIS_CURRICULUM-00011"
        
        # Lấy các lớp của học sinh
        class_students = frappe.get_all(
            "SIS Class Student",
            filters={"student_id": student_id},
            fields=["class_id"],
            ignore_permissions=True
        )
        
        if not class_students:
            logs.append("⚠️ No classes found for student")
            return list_response(data=[], message="No classes found", logs=logs)
        
        class_ids = [cs.class_id for cs in class_students if cs.class_id]
        logs.append(f"✅ Found {len(class_ids)} classes for student")
        
        # Lấy giáo viên chủ nhiệm để loại trừ
        homeroom_teacher_ids = []
        for class_id in class_ids:
            homeroom = frappe.db.get_value("SIS Class", class_id, "homeroom_teacher")
            if homeroom:
                homeroom_teacher_ids.append(homeroom)
        
        # Lấy giáo viên dạy môn Quốc tế cho các lớp này
        teachers = frappe.db.sql("""
            SELECT DISTINCT 
                t.name as teacher_id,
                u.full_name as teacher_name
            FROM `tabSIS Teacher` t
            INNER JOIN `tabUser` u ON t.user_id = u.name
            INNER JOIN `tabSIS Subject Assignment` sa ON t.name = sa.teacher_id
            INNER JOIN `tabSIS Actual Subject` subj ON sa.actual_subject_id = subj.name
            WHERE sa.class_id IN %(class_ids)s
              AND subj.curriculum_id = %(curriculum_id)s
              AND t.name NOT IN %(homeroom_ids)s
            ORDER BY u.full_name
        """, {
            "class_ids": class_ids,
            "curriculum_id": INTERNATIONAL_CURRICULUM_ID,
            "homeroom_ids": homeroom_teacher_ids if homeroom_teacher_ids else [""]
        }, as_dict=True)
        
        logs.append(f"✅ Found {len(teachers)} International curriculum teachers")
        
        return success_response(
            data=teachers,
            message=f"Retrieved {len(teachers)} teachers",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"❌ Error: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Get Student International Teachers Error")
        return error_response(
            message=f"Lỗi: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def get_application_detail(application_id=None):
    """
    Lấy chi tiết đơn đăng ký học bổng để phụ huynh có thể chỉnh sửa.
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
        
        # Kiểm tra guardian
        guardian_id = _get_current_guardian()
        if not guardian_id:
            return error_response("Không tìm thấy thông tin phụ huynh", logs=logs)
        
        # Lấy thông tin đơn
        app = frappe.get_doc("SIS Scholarship Application", application_id, ignore_permissions=True)
        
        # Kiểm tra đơn thuộc về học sinh của guardian này
        guardian_students = _get_guardian_students(guardian_id)
        student_ids = [s.student_id for s in guardian_students]
        
        if app.student_id not in student_ids:
            return error_response("Bạn không có quyền xem đơn này", logs=logs)
        
        logs.append(f"Lấy chi tiết đơn: {application_id}")
        
        # Parse báo cáo học tập - format: semester1_urls||semester2_urls
        semester1_files = []
        semester2_files = []
        if app.academic_report_upload:
            parts = app.academic_report_upload.split('||')
            if len(parts) >= 1 and parts[0]:
                semester1_files = [url.strip() for url in parts[0].split('|') if url.strip()]
            if len(parts) >= 2 and parts[1]:
                semester2_files = [url.strip() for url in parts[1].split('|') if url.strip()]
        
        # Lấy thành tích với files
        achievements = []
        for ach in app.achievements:
            # Parse nhiều file URLs nếu có (phân cách bằng |)
            files = []
            if ach.attachment:
                files = [url.strip() for url in ach.attachment.split(' | ') if url.strip()]
            
            achievements.append({
                "achievement_type": ach.achievement_type,
                "title": ach.title,
                "description": ach.description,
                "files": files
            })
        
        return success_response(
            data={
                "student_notification_email": app.student_notification_email,
                "student_contact_phone": app.student_contact_phone,
                "guardian_name": app.guardian_contact_name,
                "guardian_phone": app.guardian_contact_phone,
                "guardian_email": app.guardian_contact_email,
                "second_teacher_id": app.second_teacher_id,
                "video_url": app.video_url,
                "semester1_files": semester1_files,
                "semester2_files": semester2_files,
                "achievements": achievements
            }
        )
        
    except frappe.DoesNotExistError:
        return error_response("Không tìm thấy đơn đăng ký", logs=logs)
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Parent Portal Get Application Detail Error")
        return error_response(
            message=f"Lỗi khi lấy chi tiết đơn: {str(e)}",
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
        
        # ID của chương trình Quốc tế
        INTERNATIONAL_CURRICULUM_ID = "SIS_CURRICULUM-00011"
        
        # Lấy danh sách GV dạy lớp này từ SIS Subject Assignment
        # Filter theo curriculum để chỉ lấy GV dạy chương trình Quốc tế
        teachers = frappe.db.sql("""
            SELECT DISTINCT 
                t.name as teacher_id,
                u.full_name as teacher_name
            FROM `tabSIS Teacher` t
            INNER JOIN `tabUser` u ON t.user_id = u.name
            INNER JOIN `tabSIS Subject Assignment` sa ON t.name = sa.teacher_id
            INNER JOIN `tabSIS Actual Subject` subj ON sa.actual_subject_id = subj.name
            WHERE sa.class_id = %(class_id)s
              AND t.name != %(homeroom_id)s
              AND subj.curriculum_id = %(curriculum_id)s
            ORDER BY u.full_name
        """, {
            "class_id": class_id,
            "homeroom_id": homeroom_teacher_id or "",
            "curriculum_id": INTERNATIONAL_CURRICULUM_ID
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
        
        # Kiểm tra kỳ học bổng có đang mở và còn trong thời hạn không
        period_info = frappe.db.get_value(
            "SIS Scholarship Period",
            period_id,
            ["name", "status", "from_date", "to_date", "title"],
            as_dict=True
        )
        
        if not period_info:
            return error_response("Kỳ học bổng không tồn tại", logs=logs)
        
        # Kiểm tra trạng thái kỳ
        if period_info.status != 'Open':
            status_msg = {
                'Draft': 'Kỳ học bổng chưa mở đăng ký',
                'Closed': 'Kỳ học bổng đã đóng'
            }
            return error_response(
                status_msg.get(period_info.status, 'Kỳ học bổng không ở trạng thái cho phép đăng ký'),
                logs=logs
            )
        
        # Kiểm tra thời gian đăng ký
        today = getdate(nowdate())
        if period_info.from_date and today < getdate(period_info.from_date):
            return error_response(
                f"Chưa đến thời gian đăng ký. Thời gian mở: {period_info.from_date}",
                logs=logs
            )
        
        if period_info.to_date and today > getdate(period_info.to_date):
            return error_response(
                f"Đã hết hạn đăng ký. Hạn cuối: {period_info.to_date}",
                logs=logs
            )
        
        logs.append(f"PHHS {guardian_id} đăng ký học bổng cho {student_id}")
        
        # Kiểm tra học sinh thuộc về phụ huynh này
        students = _get_guardian_students(guardian_id)
        student_ids = [s['student_id'] for s in students]
        
        if student_id not in student_ids:
            return error_response("Học sinh này không thuộc quyền quản lý của bạn", logs=logs)
        
        # Lấy thông tin học sinh
        student_info = next((s for s in students if s['student_id'] == student_id), None)
        
        # Kiểm tra xem đây là edit hay tạo mới
        application_id = get_form_value('application_id')
        is_edit = bool(application_id)
        
        # Kiểm tra đã đăng ký chưa (nếu không phải edit mode)
        existing = frappe.db.exists("SIS Scholarship Application", {
            "scholarship_period_id": period_id,
            "student_id": student_id
        })
        
        if existing and not is_edit:
            return error_response("Học sinh này đã đăng ký học bổng rồi", logs=logs)
        
        # Nếu edit mode, kiểm tra application_id hợp lệ
        if is_edit:
            if not frappe.db.exists("SIS Scholarship Application", application_id):
                return error_response("Không tìm thấy đơn đăng ký cần chỉnh sửa", logs=logs)
            
            # Kiểm tra đơn thuộc về học sinh đúng
            app_student = frappe.db.get_value("SIS Scholarship Application", application_id, "student_id")
            if app_student != student_id:
                return error_response("Đơn đăng ký không thuộc về học sinh này", logs=logs)
            
            # Kiểm tra đơn chưa có kết quả cuối (không cho sửa khi đã Approved/Rejected)
            app_status = frappe.db.get_value("SIS Scholarship Application", application_id, "status")
            if app_status in ['Approved', 'Rejected']:
                return error_response("Không thể chỉnh sửa đơn đã có kết quả", logs=logs)
        
        # Kiểm tra kỳ học bổng - chỉ cần còn trong hạn khi tạo mới
        period = frappe.get_doc("SIS Scholarship Period", period_id)
        
        if not is_edit:
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
        
        # Upload báo cáo học tập - hỗ trợ nhiều files
        semester1_urls = []
        semester1_count = int(get_form_value('semester1_report_count') or 0)
        for i in range(semester1_count):
            file_url = upload_file(f'semester1_report_{i}', 'Scholarship/Reports')
            if file_url:
                semester1_urls.append(file_url)
        
        semester2_urls = []
        semester2_count = int(get_form_value('semester2_report_count') or 0)
        for i in range(semester2_count):
            file_url = upload_file(f'semester2_report_{i}', 'Scholarship/Reports')
            if file_url:
                semester2_urls.append(file_url)
        
        # Gộp với existing files (khi edit mode)
        existing_semester1_json = get_form_value('existing_semester1_files')
        if existing_semester1_json:
            try:
                existing_semester1 = json.loads(existing_semester1_json)
                semester1_urls = existing_semester1 + semester1_urls
            except json.JSONDecodeError:
                pass
        
        existing_semester2_json = get_form_value('existing_semester2_files')
        if existing_semester2_json:
            try:
                existing_semester2 = json.loads(existing_semester2_json)
                semester2_urls = existing_semester2 + semester2_urls
            except json.JSONDecodeError:
                pass
        
        # Gộp link báo cáo học tập (backward compatible với code cũ)
        report_links = []
        if semester1_urls:
            report_links.append(f"Kì 1: {', '.join(semester1_urls)}")
        if semester2_urls:
            report_links.append(f"Kì 2: {', '.join(semester2_urls)}")
        
        # Lấy video URL từ form (không upload file nữa)
        video_url = get_form_value('video_url')
        
        # Lấy thông tin liên hệ từ form
        student_notification_email = get_form_value('student_notification_email')
        student_contact_phone = get_form_value('student_contact_phone')
        guardian_contact_name = get_form_value('guardian_contact_name')
        guardian_contact_phone = get_form_value('guardian_contact_phone')
        guardian_contact_email = get_form_value('guardian_contact_email')
        
        # Tạo hoặc cập nhật đơn đăng ký
        # Lưu báo cáo học tập với format: semester1_urls||semester2_urls
        # Mỗi semester có nhiều URLs phân cách bằng |
        # Dùng || để phân biệt giữa 2 kỳ
        academic_report_str = None
        if semester1_urls or semester2_urls:
            semester1_str = '|'.join(semester1_urls) if semester1_urls else ''
            semester2_str = '|'.join(semester2_urls) if semester2_urls else ''
            academic_report_str = f"{semester1_str}||{semester2_str}"
        
        if is_edit:
            # Cập nhật đơn hiện có
            app = frappe.get_doc("SIS Scholarship Application", application_id, ignore_permissions=True)
            
            # Lưu giá trị cũ để so sánh xem giáo viên có thay đổi không
            old_main_teacher_id = app.main_teacher_id
            old_second_teacher_id = app.second_teacher_id
            
            # Giá trị mới
            new_main_teacher_id = get_form_value('main_teacher_id') or student_info.get('homeroom_teacher')
            new_second_teacher_id = get_form_value('second_teacher_id')
            
            # Track các giáo viên mới được thay đổi để gửi email
            changed_teachers = []
            
            # Kiểm tra GVCN có thay đổi không
            if new_main_teacher_id and new_main_teacher_id != old_main_teacher_id:
                changed_teachers.append(('main', new_main_teacher_id))
                logs.append(f"GVCN thay đổi: {old_main_teacher_id} -> {new_main_teacher_id}")
            
            # Kiểm tra GV bộ môn có thay đổi không  
            if new_second_teacher_id and new_second_teacher_id != old_second_teacher_id:
                changed_teachers.append(('second', new_second_teacher_id))
                logs.append(f"GV bộ môn thay đổi: {old_second_teacher_id} -> {new_second_teacher_id}")
            
            # Nếu có thay đổi giáo viên, xóa recommendation cũ và tạo mới cho GV mới
            if changed_teachers:
                for rec_type, new_teacher_id in changed_teachers:
                    # Xóa TẤT CẢ recommendation cũ của loại này (Denied, Pending, v.v.)
                    old_recs = frappe.get_all(
                        "SIS Scholarship Recommendation",
                        filters={
                            "application_id": application_id,
                            "recommendation_type": rec_type
                        },
                        fields=["name", "teacher_id", "status"]
                    )
                    
                    # Bước 1: Xóa link reference trên application TRƯỚC (để Frappe cho phép xóa)
                    if rec_type == 'main':
                        app.db_set("main_recommendation_id", None, update_modified=False)
                        app.db_set("main_recommendation_status", None, update_modified=False)
                    else:
                        app.db_set("second_recommendation_id", None, update_modified=False)
                        app.db_set("second_recommendation_status", None, update_modified=False)
                    
                    # Bước 2: Xóa recommendation cũ (không bị block vì đã gỡ link)
                    for rec in old_recs:
                        frappe.delete_doc("SIS Scholarship Recommendation", rec.name, ignore_permissions=True, force=True)
                        logs.append(f"Đã xóa recommendation cũ ({rec.status}): {rec.name} của GV {rec.teacher_id}")
                    
                    # Bước 3: Tạo recommendation MỚI cho giáo viên mới
                    try:
                        new_rec = frappe.get_doc({
                            "doctype": "SIS Scholarship Recommendation",
                            "application_id": application_id,
                            "teacher_id": new_teacher_id,
                            "recommendation_type": rec_type,
                            "status": "Pending"
                        })
                        new_rec.insert(ignore_permissions=True)
                        
                        # Cập nhật reference trên application bằng db_set (ghi thẳng DB)
                        # Không cần set attribute trên app vì sẽ reload() sau
                        if rec_type == 'main':
                            app.db_set("main_recommendation_id", new_rec.name, update_modified=False)
                            app.db_set("main_recommendation_status", "Pending", update_modified=False)
                        else:
                            app.db_set("second_recommendation_id", new_rec.name, update_modified=False)
                            app.db_set("second_recommendation_status", "Pending", update_modified=False)
                        
                        logs.append(f"Đã tạo recommendation mới: {new_rec.name} cho GV {new_teacher_id} ({rec_type})")
                    except Exception as rec_err:
                        logs.append(f"Lỗi tạo recommendation mới cho GV {new_teacher_id}: {str(rec_err)}")
                        frappe.log_error(frappe.get_traceback(), "Scholarship Create New Recommendation Error")
                
                # Reset status về WaitingRecommendation nếu đang ở trạng thái DeniedByTeacher
                if app.status == 'DeniedByTeacher':
                    app.db_set("status", "WaitingRecommendation", update_modified=False)
                    logs.append("Reset trạng thái về WaitingRecommendation")
                
                # Reload app để đồng bộ modified timestamp
                # (vì new_rec.insert() trigger on_update → update_application_status → app.save() → thay đổi modified)
                app.reload()
            
            # Cập nhật các trường
            app.main_teacher_id = new_main_teacher_id
            app.second_teacher_id = new_second_teacher_id
            if academic_report_str:
                app.academic_report_type = 'upload'
                app.academic_report_upload = academic_report_str
            app.video_url = video_url if video_url else None
            app.student_notification_email = student_notification_email
            app.student_contact_phone = student_contact_phone
            app.guardian_contact_name = guardian_contact_name
            app.guardian_contact_phone = guardian_contact_phone
            app.guardian_contact_email = guardian_contact_email
            
            # Xóa thành tích cũ nếu có thành tích mới
            achievements_json = get_form_value('achievements')
            if achievements_json:
                app.achievements = []
            
            logs.append(f"Cập nhật đơn: {application_id}")
        else:
            # Tạo đơn mới
            app = frappe.get_doc({
                "doctype": "SIS Scholarship Application",
                "scholarship_period_id": period_id,
                "student_id": student_id,
                "class_id": student_info.get('class_id'),
                "education_stage_id": student_info.get('education_stage_id'),
                "guardian_id": guardian_id,
                "main_teacher_id": get_form_value('main_teacher_id') or student_info.get('homeroom_teacher'),
                "second_teacher_id": get_form_value('second_teacher_id'),
                "academic_report_type": 'upload' if academic_report_str else 'existing',
                "academic_report_upload": academic_report_str,  # Format: semester1_url||semester2_url
                "video_url": video_url if video_url else None,
                "status": "Submitted",
                # Thông tin liên hệ
                "student_notification_email": student_notification_email,
                "student_contact_phone": student_contact_phone,
                "guardian_contact_name": guardian_contact_name,
                "guardian_contact_phone": guardian_contact_phone,
                "guardian_contact_email": guardian_contact_email
            })
        
        # Parse và thêm thành tích - Cấu trúc mới: chỉ files, không có entries
        achievements_json = get_form_value('achievements')
        if achievements_json:
            try:
                achievements_data = json.loads(achievements_json)
                logs.append(f"Achievements data: {len(achievements_data)} categories")
                
                for cat_data in achievements_data:
                    category_index = cat_data.get('category_index', 0)
                    category_title_vn = cat_data.get('category_title_vn', '')
                    category_title_en = cat_data.get('category_title_en', '')
                    file_count = cat_data.get('file_count', 0)
                    existing_files = cat_data.get('existing_files', [])
                    
                    # Bỏ qua nếu không có file nào (cả mới và cũ)
                    if file_count == 0 and len(existing_files) == 0:
                        continue
                    
                    # Map category title to achievement_type dựa vào tên
                    achievement_type = 'other'
                    title_lower = category_title_vn.lower() if category_title_vn else ''
                    if 'bài thi' in title_lower or 'chuẩn hóa' in title_lower or 'standardized' in title_lower.lower():
                        achievement_type = 'standardized_test'
                    elif 'giải thưởng' in title_lower or 'thành tích' in title_lower or 'award' in title_lower.lower():
                        achievement_type = 'award'
                    elif 'ngoại khóa' in title_lower or 'hoạt động' in title_lower or 'extracurricular' in title_lower.lower():
                        achievement_type = 'extracurricular'
                    
                    logs.append(f"Category {category_index}: {category_title_vn} -> {achievement_type}, {file_count} new files, {len(existing_files)} existing files")
                    
                    # Bắt đầu với existing files
                    attachment_urls = list(existing_files) if existing_files else []
                    
                    # Upload files mới cho category này
                    for file_idx in range(file_count):
                        file_key = f'achievement_file_{category_index}_{file_idx}'
                        file_url = upload_file(file_key, 'Scholarship/Certificates')
                        if file_url:
                            attachment_urls.append(file_url)
                    
                    # Gộp nhiều file URLs thành 1 string, phân cách bằng |
                    attachment_str = ' | '.join(attachment_urls) if attachment_urls else None
                    
                    # Tạo 1 achievement record cho category với tất cả files
                    app.append("achievements", {
                        "achievement_type": achievement_type,
                        "title": category_title_vn,
                        "description": f"{category_title_vn} ({category_title_en})" if category_title_en else category_title_vn,
                        "attachment": attachment_str
                    })
                    logs.append(f"  Added {len(attachment_urls)} total files for category {category_title_vn}")
                        
            except json.JSONDecodeError as e:
                logs.append(f"Error parsing achievements JSON: {str(e)}")
        
        # Backward compatible: Hỗ trợ cấu trúc cũ nếu có
        # Parse và thêm thành tích - Bài thi chuẩn hóa (cấu trúc cũ)
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
        
        # Parse và thêm thành tích - Giải thưởng (cấu trúc cũ)
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
        
        # Parse và thêm thành tích - Hoạt động ngoại khóa (cấu trúc cũ)
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
        
        if is_edit:
            app.save(ignore_permissions=True)
            logs.append(f"Đã cập nhật đơn đăng ký: {app.name}")
            message = "Cập nhật hồ sơ thành công"
            
            # Debug log: kiểm tra changed_teachers có được populate không
            logs.append(f"[DEBUG] changed_teachers = {changed_teachers}")
            logs.append(f"[DEBUG] old_second={old_second_teacher_id}, new_second={new_second_teacher_id}")
            
            # Gửi email thông báo đến giáo viên MỚI được thay đổi (không gửi lại cho GV cũ)
            if changed_teachers:
                logs.append(f"[DEBUG] Bắt đầu gửi email cho {len(changed_teachers)} GV thay đổi")
                try:
                    _send_email_to_changed_teachers(app, student_info, changed_teachers, logs)
                except Exception as email_error:
                    logs.append(f"Cảnh báo: Không thể gửi email thông báo - {str(email_error)}")
            else:
                logs.append("[DEBUG] changed_teachers rỗng - không gửi email")
        else:
            app.insert(ignore_permissions=True)
            logs.append(f"Đã tạo đơn đăng ký: {app.name}")
            message = "Đăng ký học bổng thành công"
            
            # Gửi email thông báo đến giáo viên khi tạo đơn mới
            try:
                _send_scholarship_notification_to_teachers(app, student_info, is_new=True)
                logs.append("Đã gửi email thông báo đến giáo viên")
            except Exception as email_error:
                logs.append(f"Cảnh báo: Không thể gửi email thông báo - {str(email_error)}")
        
        frappe.db.commit()
        
        return success_response(
            data={
                "name": app.name,
                "status": app.status
            },
            message=message,
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Parent Portal Submit Scholarship With Files Error")
        return error_response(
            message=f"Lỗi khi đăng ký học bổng: {str(e)}",
            logs=logs
        )
