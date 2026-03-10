"""
Parent Portal Re-enrollment API
Handles re-enrollment submission for parent portal

API endpoints cho phụ huynh nộp đơn tái ghi danh qua Parent Portal.
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

# Email nhận thông báo yêu cầu điều chỉnh
ADJUSTMENT_NOTIFICATION_EMAILS = [
    "linh.nguyenhai@wellspring.edu.vn",
    "hieu.nguyenduy@wellspring.edu.vn"
]

# Decision types cho tái ghi danh
DECISION_TYPES = ['re_enroll', 'considering', 'not_re_enroll']

# Decision display mapping
DECISION_DISPLAY_MAP_VI = {
    're_enroll': 'Tái ghi danh',
    'considering': 'Đang cân nhắc',
    'not_re_enroll': 'Không tái ghi danh'
}
DECISION_DISPLAY_MAP_EN = {
    're_enroll': 'Re-enroll',
    'considering': 'Considering',
    'not_re_enroll': 'Not Re-enrolling'
}


def _send_email_via_service(to_list, subject, body):
    """
    Gửi email qua email service GraphQL API
    
    Args:
        to_list: List các email người nhận
        subject: Tiêu đề email
        body: Nội dung email (HTML)
    
    Returns:
        dict: {"success": True/False, "message": "..."}
    """
    try:
        # Lấy URL email service từ config hoặc mặc định
        email_service_url = frappe.conf.get('email_service_url') or 'http://localhost:5030'
        graphql_endpoint = f"{email_service_url}/graphql"
        
        # GraphQL mutation gửi email
        graphql_query = """
        mutation SendEmail($input: SendEmailInput!) {
            sendEmail(input: $input) {
                success
                message
                messageId
            }
        }
        """
        
        # Variables cho GraphQL mutation
        variables = {
            "input": {
                "to": to_list,
                "subject": subject,
                "body": body,
                "contentType": "HTML"
            }
        }
        
        # GraphQL request payload
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
            
            # Kiểm tra lỗi GraphQL
            if result.get('errors'):
                error_messages = [err.get('message', 'Unknown error') for err in result['errors']]
                frappe.logger().error(f"GraphQL errors: {error_messages}")
                return {"success": False, "message": f"GraphQL errors: {', '.join(error_messages)}"}
            
            # Kiểm tra kết quả mutation
            send_email_result = result.get('data', {}).get('sendEmail')
            if send_email_result and send_email_result.get('success'):
                frappe.logger().info(f"Email sent successfully to {to_list} - MessageId: {send_email_result.get('messageId')}")
                return {"success": True, "message": send_email_result.get('message')}
            else:
                error_msg = send_email_result.get('message', 'Unknown error') if send_email_result else 'No response data'
                frappe.logger().error(f"Email service returned error: {error_msg}")
                return {"success": False, "message": error_msg}
        else:
            frappe.logger().error(f"Email service HTTP error: {response.status_code} - {response.text}")
            return {"success": False, "message": f"HTTP {response.status_code}: {response.text}"}
    
    except requests.exceptions.RequestException as e:
        frappe.logger().error(f"Request error sending email: {str(e)}")
        return {"success": False, "message": f"Request error: {str(e)}"}
    except Exception as e:
        frappe.logger().error(f"Error sending email: {str(e)}")
        return {"success": False, "message": f"Error: {str(e)}"}


def _send_adjustment_notification_email(student_name, student_code, requested_at, re_enrollment_id, config_id):
    """
    Gửi email thông báo yêu cầu điều chỉnh tái ghi danh đến bộ phận tuyển sinh
    
    Args:
        student_name: Tên học sinh
        student_code: Mã học sinh
        requested_at: Thời gian yêu cầu
        re_enrollment_id: ID đơn tái ghi danh
        config_id: ID config tái ghi danh
    """
    try:
        # Format thời gian
        from datetime import datetime
        if isinstance(requested_at, str):
            dt = datetime.fromisoformat(requested_at.replace('Z', '+00:00')) if 'T' in requested_at else datetime.strptime(requested_at, '%Y-%m-%d %H:%M:%S.%f')
        else:
            dt = requested_at
        
        time_str = dt.strftime('%H:%M')
        date_str = dt.strftime('%d/%m/%Y')
        
        # Tạo link điều chỉnh - trỏ đến trang danh sách submissions với filter theo config
        # Lấy URL frontend từ allow_cors (ưu tiên wis.wellspring.edu.vn) hoặc mặc định production
        allow_cors = frappe.conf.get('allow_cors') or []
        base_url = 'https://wis.wellspring.edu.vn'  # Mặc định production
        for cors_url in allow_cors:
            if 'wis.wellspring.edu.vn' in cors_url or 'wis-staging.wellspring.edu.vn' in cors_url:
                base_url = cors_url
                break
        adjustment_link = f"{base_url}/admission/re-enrollment/submissions?config={config_id}"
        
        # Tiêu đề email
        subject = "YÊU CẦU ĐIỀU CHỈNH TÁI GHI DANH"
        
        # Nội dung email HTML
        body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <h2 style="color: #002855; border-bottom: 2px solid #F05023; padding-bottom: 10px;">
                    YÊU CẦU ĐIỀU CHỈNH TÁI GHI DANH
                </h2>
                
                <p>Hệ thống nhận được yêu cầu điều chỉnh Tái ghi danh của Học sinh:</p>
                
                <table style="width: 100%; border-collapse: collapse; margin: 20px 0;">
                    <tr>
                        <td style="padding: 10px; border: 1px solid #ddd; background-color: #f9f9f9; font-weight: bold; width: 40%;">
                            Họ và Tên Học sinh:
                        </td>
                        <td style="padding: 10px; border: 1px solid #ddd;">
                            {student_name} ({student_code})
                        </td>
                    </tr>
                    <tr>
                        <td style="padding: 10px; border: 1px solid #ddd; background-color: #f9f9f9; font-weight: bold;">
                            Thời gian yêu cầu:
                        </td>
                        <td style="padding: 10px; border: 1px solid #ddd;">
                            {time_str}, Ngày {date_str}
                        </td>
                    </tr>
                    <tr>
                        <td style="padding: 10px; border: 1px solid #ddd; background-color: #f9f9f9; font-weight: bold;">
                            Link điều chỉnh:
                        </td>
                        <td style="padding: 10px; border: 1px solid #ddd;">
                            <a href="{adjustment_link}" style="color: #F05023; text-decoration: none;">
                                Xem và điều chỉnh đơn
                            </a>
                        </td>
                    </tr>
                </table>
                
                <p style="color: #F05023; font-weight: bold;">
                    Vui lòng liên hệ hỗ trợ Phụ huynh trong thời gian sớm nhất.
                </p>
                
                <hr style="border: none; border-top: 1px solid #ddd; margin: 20px 0;">
                
                <p style="font-size: 12px; color: #666;">
                    Email này được gửi tự động từ hệ thống Wellspring SIS.<br>
                    Vui lòng không reply trực tiếp vào email này.
                </p>
            </div>
        </body>
        </html>
        """
        
        # Gửi email
        result = _send_email_via_service(
            to_list=ADJUSTMENT_NOTIFICATION_EMAILS,
            subject=subject,
            body=body
        )
        
        if result.get('success'):
            frappe.logger().info(f"Adjustment notification email sent for {re_enrollment_id}")
        else:
            frappe.logger().error(f"Failed to send adjustment notification email: {result.get('message')}")
        
        return result
        
    except Exception as e:
        frappe.logger().error(f"Error sending adjustment notification email: {str(e)}")
        return {"success": False, "message": str(e)}


def _create_re_enrollment_announcement(
    student_id: str,
    student_name: str,
    student_code: str,
    submission_data: dict,
    is_update: bool = False
):
    """
    Tạo Announcement (Tin tức) cho đơn tái ghi danh.
    Gửi cả push notification.
    
    Args:
        student_id: ID học sinh (CRM Student)
        student_name: Tên học sinh
        student_code: Mã học sinh
        submission_data: Dict chứa thông tin đơn:
            - decision: re_enroll | considering | not_re_enroll
            - payment_type: annual | semester (nếu re_enroll)
            - discount_name: Tên ưu đãi (nếu có)
            - discount_percent: % giảm (nếu có)
            - school_year: Năm học (VD: "2026-2027")
            - submitted_at: Thời gian nộp/cập nhật
            - status: Trạng thái (nếu update)
            - answers: Danh sách câu trả lời khảo sát (list of dict)
        is_update: True nếu là cập nhật từ admin
    """
    try:
        decision = submission_data.get('decision')
        payment_type = submission_data.get('payment_type')
        discount_name = submission_data.get('discount_name')
        discount_percent = submission_data.get('discount_percent')
        school_year = submission_data.get('school_year', '')
        submitted_at = submission_data.get('submitted_at', now())
        status = submission_data.get('status', 'pending')
        answers = submission_data.get('answers', [])  # Câu trả lời khảo sát
        
        # Format datetime
        from datetime import datetime
        if isinstance(submitted_at, str):
            try:
                dt = datetime.fromisoformat(submitted_at.replace('Z', '+00:00'))
                time_display_vi = dt.strftime('%d/%m/%Y %H:%M')
                time_display_en = dt.strftime('%b %d, %Y %H:%M')
            except:
                time_display_vi = submitted_at
                time_display_en = submitted_at
        else:
            time_display_vi = str(submitted_at)
            time_display_en = str(submitted_at)
        
        # Get display names
        decision_vi = DECISION_DISPLAY_MAP_VI.get(decision, decision)
        decision_en = DECISION_DISPLAY_MAP_EN.get(decision, decision)
        
        payment_vi = ""
        payment_en = ""
        if payment_type:
            payment_vi = "Đóng theo năm" if payment_type == 'annual' else "Đóng theo kỳ"
            payment_en = "Annual" if payment_type == 'annual' else "Semester"
        
        status_vi = {"pending": "Chờ xử lý", "approved": "Đã duyệt", "rejected": "Từ chối"}.get(status, status)
        status_en = {"pending": "Pending", "approved": "Approved", "rejected": "Rejected"}.get(status, status)
        
        # Lấy thêm thông tin reason từ submission_data
        reason = submission_data.get('reason', '')
        
        # Build content based on action type
        if is_update:
            # Admin update notification
            title_vn = f"Cập nhật đơn tái ghi danh - {student_name}"
            title_en = f"Re-enrollment Update - {student_name}"
            
            # Lấy thông tin mốc thanh toán (discount deadline) từ submission_data
            discount_deadline = submission_data.get('discount_deadline', '')
            discount_deadline_display = ""
            if discount_deadline:
                try:
                    from datetime import datetime
                    if isinstance(discount_deadline, str):
                        dt = datetime.fromisoformat(discount_deadline.replace('Z', '+00:00'))
                        discount_deadline_display = dt.strftime('%d/%m/%Y')
                    else:
                        discount_deadline_display = str(discount_deadline)
                except:
                    discount_deadline_display = str(discount_deadline)
            
            # Build thông tin đơn theo format mới cho update
            info_lines_vn = [
                f"- Năm học tái ghi danh: **{school_year}**",
                f"- Quyết định: **{decision_vi}**"
            ]
            
            if decision == 're_enroll':
                if payment_vi:
                    info_lines_vn.append(f"- Phương thức thanh toán: **{payment_vi}**")
                
                if discount_deadline_display:
                    info_lines_vn.append(f"- Mốc thanh toán lựa chọn: **{discount_deadline_display}**")
                
                if discount_name and discount_percent:
                    info_lines_vn.append(f"- Ưu đãi tài chính được áp dụng: **Giảm {discount_percent}%** (theo hạn ưu đãi: trước {discount_deadline_display})")
            
            info_details_vn = "\n".join(info_lines_vn)
            
            content_vn = f"""Kính gửi Quý Phụ huynh,

Nhà trường xác nhận việc điều chỉnh và cập nhật hồ sơ Tái ghi danh cho Năm học {school_year} đã được thực hiện thành công theo thông tin Quý Phụ huynh cung cấp.

Hồ sơ Tái ghi danh của Học sinh **{student_name}** – **{student_code}** đã được hệ thống ghi nhận vào **{time_display_vi}**, với các nội dung như sau:

{info_details_vn}

Trường hợp Quý Phụ huynh có nhu cầu tiếp tục điều chỉnh thông tin, bổ sung hồ sơ hoặc cần hỗ trợ thêm liên quan đến kế hoạch tái ghi danh, xin vui lòng liên hệ Bộ phận Kết nối WISers – Phòng Tuyển sinh qua các kênh sau:
📞 0973 759 229 | 0915 846 229 | (024) 37305 8668

Nhà trường trân trọng cảm ơn sự phối hợp và đồng hành của Quý Phụ huynh, đồng thời rất mong tiếp tục được đồng hành cùng Gia đình và Học sinh trong năm học mới tại Wellspring Hanoi.

Trân trọng,
**Hệ thống Trường Phổ thông Liên cấp Song ngữ Quốc tế Wellspring – Wellspring Hanoi**"""

            # Build thông tin đơn tiếng Anh cho update
            info_lines_en = [
                f"- School Year: **{school_year}**",
                f"- Decision: **{decision_en}**"
            ]
            
            if decision == 're_enroll':
                if payment_en:
                    info_lines_en.append(f"- Payment Method: **{payment_en}**")
                
                if discount_deadline_display:
                    info_lines_en.append(f"- Selected Payment Milestone: **{discount_deadline_display}**")
                
                if discount_name and discount_percent:
                    info_lines_en.append(f"- Financial Discount Applied: **{discount_percent}% off** (discount deadline: before {discount_deadline_display})")
            
            info_details_en = "\n".join(info_lines_en)
            
            content_en = f"""Dear Parents,

The School confirms that the re-enrollment application for School Year {school_year} has been successfully updated based on the information you provided.

The re-enrollment application for student **{student_name}** – **{student_code}** has been recorded in the system on **{time_display_en}**, with the following details:

{info_details_en}

If you need to continue adjusting information, supplementing documents, or require further support regarding the re-enrollment plan, please contact the WISers Connection Department – Admissions Office through the following channels:
📞 0973 759 229 | 0915 846 229 | (024) 37305 8668

The School sincerely appreciates your cooperation and partnership, and looks forward to continuing our journey with your family and student in the new school year at Wellspring Hanoi.

Best regards,
**Wellspring International Bilingual School Hanoi**"""
            
            push_body_vi = f"Đơn tái ghi danh của {student_name} đã được cập nhật"
            push_body_en = f"Re-enrollment application for {student_name} has been updated"
        else:
            # Parent submission notification
            title_vn = f"Đơn tái ghi danh - {student_name}"
            title_en = f"Re-enrollment Application - {student_name}"
            
            # Lấy thông tin mốc thanh toán (discount deadline) từ submission_data
            discount_deadline = submission_data.get('discount_deadline', '')
            discount_deadline_display = ""
            if discount_deadline:
                try:
                    from datetime import datetime
                    if isinstance(discount_deadline, str):
                        dt = datetime.fromisoformat(discount_deadline.replace('Z', '+00:00'))
                        discount_deadline_display = dt.strftime('%d/%m/%Y')
                    else:
                        discount_deadline_display = str(discount_deadline)
                except:
                    discount_deadline_display = str(discount_deadline)
            
            # Build thông tin đơn theo format mới
            info_lines_vn = [
                f"- Năm học đăng ký tái ghi danh: **{school_year}**",
                f"- Quyết định: **{decision_vi}**"
            ]
            
            if decision == 're_enroll':
                if payment_vi:
                    info_lines_vn.append(f"- Phương thức thanh toán: **{payment_vi}**")
                
                if discount_deadline_display:
                    info_lines_vn.append(f"- Mốc thanh toán lựa chọn: **{discount_deadline_display}**")
                
                if discount_name and discount_percent:
                    info_lines_vn.append(f"- Ưu đãi tài chính được áp dụng: **Giảm {discount_percent}%** (theo hạn ưu đãi: trước {discount_deadline_display})")
            
            info_details_vn = "\n".join(info_lines_vn)
            
            content_vn = f"""Kính gửi Quý Phụ huynh,

Nhà trường trân trọng cảm ơn Quý Phụ huynh đã xác nhận thông tin Tái ghi danh cho Năm học {school_year}.

Đơn Tái ghi danh của Học sinh **{student_name}** – **{student_code}** đã được gửi thành công vào **{time_display_vi}** với các thông tin đăng ký như sau:

{info_details_vn}

Trong trường hợp Quý Phụ huynh cần hỗ trợ thêm thông tin, điều chỉnh hoặc hỗ trợ liên quan đến hồ sơ tái ghi danh, xin vui lòng liên hệ Bộ phận hỗ trợ qua các kênh sau:

📞 Bộ phận Kết nối WISers – Phòng Tuyển sinh: 0973 759 229 | 0915 846 229 | (024) 37305 8668
📞 Phòng Kế toán: 0936 203 888
📞 Phòng Dịch vụ Học sinh: 083 657 3838 | 0902 192 200

Nhà trường rất mong tiếp tục được đồng hành cùng Gia đình và Học sinh trong năm học mới tại Wellspring Hanoi.

Trân trọng,
**Hệ thống Trường Phổ thông Liên cấp Song ngữ Quốc tế Wellspring – Wellspring Hanoi**"""

            # Build thông tin đơn tiếng Anh cho parent submission
            info_lines_en = [
                f"- School Year for Re-enrollment: **{school_year}**",
                f"- Decision: **{decision_en}**"
            ]
            
            if decision == 're_enroll':
                if payment_en:
                    info_lines_en.append(f"- Payment Method: **{payment_en}**")
                
                if discount_deadline_display:
                    info_lines_en.append(f"- Selected Payment Milestone: **{discount_deadline_display}**")
                
                if discount_name and discount_percent:
                    info_lines_en.append(f"- Financial Discount Applied: **{discount_percent}% off** (discount deadline: before {discount_deadline_display})")
            
            info_details_en = "\n".join(info_lines_en)
            
            content_en = f"""Dear Parents,

The School sincerely thanks you for confirming the Re-enrollment information for School Year {school_year}.

The Re-enrollment application for student **{student_name}** – **{student_code}** has been successfully submitted on **{time_display_en}** with the following details:

{info_details_en}

If you need additional support, information adjustments, or assistance regarding the re-enrollment application, please contact the support departments through the following channels:

📞 WISers Connection Department – Admissions Office: 0973 759 229 | 0915 846 229 | (024) 37305 8668
📞 Finance Department: 0936 203 888
📞 Student Services Department: 083 657 3838 | 0902 192 200

The School looks forward to continuing our journey with your family and student in the new school year at Wellspring Hanoi.

Best regards,
**Wellspring International Bilingual School Hanoi**"""

            push_body_vi = f"Nộp đơn tái ghi danh cho {student_name} thành công"
            push_body_en = f"Re-enrollment application for {student_name} submitted successfully"
        
        # Lấy campus_id để filter announcement
        campus_id = frappe.db.get_value("CRM Student", student_id, "campus_id")
        
        # Tạo SIS Announcement
        announcement = frappe.get_doc({
            "doctype": "SIS Announcement",
            "title_vn": title_vn,
            "title_en": title_en,
            "content_vn": content_vn,
            "content_en": content_en,
            "campus_id": campus_id,
            "status": "sent",
            "sent_at": now(),
            "recipients": json.dumps([{
                "id": student_id, 
                "type": "student",
                "display_name": student_name  # Hiển thị tên học sinh thay vì ID
            }]),
            "recipient_type": "specific"
        })
        announcement.insert(ignore_permissions=True)
        frappe.db.commit()
        
        frappe.logger().info(f"✅ Created re-enrollment announcement: {announcement.name} for student {student_id}")
        
        # Gửi push notification
        try:
            from erp.utils.notification_handler import send_bulk_parent_notifications
            
            notification_result = send_bulk_parent_notifications(
                recipient_type="announcement",
                recipients_data={
                    "student_ids": [student_id],
                    "announcement_id": announcement.name
                },
                title="Đơn tái ghi danh",
                body=push_body_vi,
                icon="/icon.png",
                data={
                    "type": "announcement",
                    "announcement_id": announcement.name,
                    "student_id": student_id,
                    "title_en": title_en,
                    "title_vn": title_vn,
                    "url": f"/announcement?id={announcement.name}&student={student_id}"
                }
            )
            
            frappe.logger().info(f"📢 Re-enrollment push notification result: {notification_result}")
            
        except Exception as push_err:
            frappe.logger().error(f"❌ Error sending re-enrollment push notification: {str(push_err)}")
        
        return announcement.name
        
    except Exception as e:
        frappe.logger().error(f"❌ Error creating re-enrollment announcement: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Create Re-enrollment Announcement Error")
        return None


def _get_current_parent():
    """Lấy thông tin phụ huynh đang đăng nhập"""
    user_email = frappe.session.user
    if user_email == "Guest":
        return None

    # Format email: guardian_id@parent.wellspring.edu.vn
    if "@parent.wellspring.edu.vn" not in user_email:
        return None

    guardian_id = user_email.split("@")[0]

    # Lấy guardian name từ guardian_id
    guardian = frappe.db.get_value("CRM Guardian", {"guardian_id": guardian_id}, "name")
    return guardian


def _get_parent_students(parent_id):
    """
    Lấy danh sách học sinh của phụ huynh.
    Trả về list các student với thông tin lớp hiện tại.
    Loại bỏ duplicate students.
    """
    if not parent_id:
        return []
    
    # Query CRM Family Relationship để lấy danh sách học sinh
    relationships = frappe.get_all(
        "CRM Family Relationship",
        filters={"guardian": parent_id},
        fields=["student", "relationship_type", "key_person"]
    )
    
    # Dùng dict để loại bỏ duplicate theo student ID
    students_dict = {}
    for rel in relationships:
        # Bỏ qua nếu đã có student này
        if rel.student in students_dict:
            continue
            
        try:
            student = frappe.get_doc("CRM Student", rel.student)
            
            # Lấy lớp hiện tại
            current_class = _get_student_current_class(student.name, student.campus_id)
            
            # Lấy ảnh học sinh từ SIS Photo (giống logic trong otp_auth.py)
            sis_photo = None
            try:
                # Lấy năm học hiện tại đang active
                current_school_year = frappe.db.get_value(
                    "SIS School Year",
                    {"is_enable": 1},
                    "name",
                    order_by="start_date desc"
                )
                
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
                """, (student.name, current_school_year), as_dict=True)

                if sis_photos:
                    sis_photo = sis_photos[0]["photo"]
            except Exception as photo_err:
                frappe.logger().error(f"Error getting sis_photo for {student.name}: {str(photo_err)}")
            
            students_dict[student.name] = {
                "name": student.name,
                "student_name": student.student_name,
                "student_code": student.student_code,
                "campus_id": student.campus_id,
                "current_class": current_class.get("class_title") if current_class else None,
                "current_class_id": current_class.get("class_id") if current_class else None,
                "relationship_type": rel.relationship_type,
                "is_key_person": rel.key_person,
                "sis_photo": sis_photo
            }
        except Exception as e:
            frappe.logger().error(f"Error getting student {rel.student}: {str(e)}")
            continue
    
    return list(students_dict.values())


def _get_student_current_class(student_id, campus_id=None):
    """Lấy lớp hiện tại của học sinh"""
    if not student_id:
        return None
    
    # Lấy campus_id nếu chưa có
    if not campus_id:
        campus_id = frappe.db.get_value("CRM Student", student_id, "campus_id")
    
    if not campus_id:
        return None
    
    # Lấy năm học hiện tại (đang active)
    current_school_year = frappe.db.get_value(
        "SIS School Year",
        {"is_enable": 1, "campus_id": campus_id},
        "name",
        order_by="start_date desc"
    )
    
    if not current_school_year:
        return None
    
    # Tìm lớp regular của học sinh
    class_student = frappe.db.sql("""
        SELECT cs.class_id, c.title as class_title
        FROM `tabSIS Class Student` cs
        INNER JOIN `tabSIS Class` c ON cs.class_id = c.name
        WHERE cs.student_id = %s
        AND cs.school_year_id = %s
        AND (c.class_type = 'regular' OR c.class_type IS NULL OR c.class_type = '')
        LIMIT 1
    """, (student_id, current_school_year), as_dict=True)
    
    if class_student:
        return {
            "class_id": class_student[0].class_id,
            "class_title": class_student[0].class_title
        }
    
    return None


@frappe.whitelist()
def get_active_config():
    """
    Lấy cấu hình tái ghi danh đang mở cho campus của phụ huynh.
    Trả về config với đầy đủ thông tin bao gồm bảng ưu đãi.
    """
    logs = []
    
    try:
        logs.append("Đang lấy cấu hình tái ghi danh đang mở")
        
        # Lấy thông tin phụ huynh
        parent_id = _get_current_parent()
        if not parent_id:
            return error_response("Không tìm thấy thông tin phụ huynh", logs=logs)
        
        logs.append(f"Parent ID: {parent_id}")
        
        # Lấy danh sách học sinh của phụ huynh
        students = _get_parent_students(parent_id)
        if not students:
            return error_response("Không tìm thấy học sinh", logs=logs)
        
        # Lấy campus_id từ học sinh đầu tiên
        campus_id = students[0].get("campus_id") if students else None
        
        if not campus_id:
            return error_response("Không xác định được campus", logs=logs)
        
        logs.append(f"Campus: {campus_id}")
        
        # Tìm config đang active cho campus này
        config = frappe.db.get_value(
            "SIS Re-enrollment Config",
            {
                "is_active": 1,
                "campus_id": campus_id
            },
            ["name", "title", "school_year_id", "campus_id", "start_date", "end_date",
             "service_document", "service_document_images", "agreement_text", "agreement_text_en"],
            as_dict=True
        )
        
        if not config:
            logs.append("Không có đợt tái ghi danh nào đang mở")
            return success_response(
                data=None,
                message="Không có đợt tái ghi danh nào đang mở",
                logs=logs
            )
        
        # Kiểm tra thời gian
        today = getdate(nowdate())
        start_date = getdate(config.start_date) if config.start_date else None
        end_date = getdate(config.end_date) if config.end_date else None
        
        if start_date and today < start_date:
            logs.append(f"Chưa đến thời gian tái ghi danh. Bắt đầu: {config.start_date}")
            return success_response(
                data={
                    "status": "not_started",
                    "start_date": str(config.start_date),
                    "message": f"Đợt tái ghi danh sẽ bắt đầu từ ngày {config.start_date}"
                },
                message="Chưa đến thời gian tái ghi danh",
                logs=logs
            )
        
        if end_date and today > end_date:
            logs.append(f"Đã hết thời gian tái ghi danh. Kết thúc: {config.end_date}")
            return success_response(
                data={
                    "status": "ended",
                    "end_date": str(config.end_date),
                    "message": f"Đợt tái ghi danh đã kết thúc ngày {config.end_date}"
                },
                message="Đã hết thời gian tái ghi danh",
                logs=logs
            )
        
        # Lấy bảng ưu đãi
        discounts = frappe.get_all(
            "SIS Re-enrollment Discount",
            filters={"parent": config.name},
            fields=["name", "deadline", "description", "annual_discount", "semester_discount"],
            order_by="deadline asc"
        )
        
        # Lấy câu hỏi khảo sát
        questions = []
        question_rows = frappe.get_all(
            "SIS Re-enrollment Question",
            filters={"parent": config.name},
            fields=["name", "question_vn", "question_en", "question_type", "is_required", "sort_order", "options_json"],
            order_by="sort_order asc"
        )
        
        for q in question_rows:
            # Parse options từ JSON
            options = []
            if q.options_json:
                try:
                    parsed_options = json.loads(q.options_json)
                    # Lọc bỏ options rỗng hoặc có text là "0"
                    options = [
                        opt for opt in parsed_options 
                        if opt.get('option_vn', '').strip() or opt.get('option_en', '').strip()
                    ]
                except json.JSONDecodeError:
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
        
        # Parse service_document_images từ JSON
        service_document_images = []
        if config.service_document_images:
            try:
                service_document_images = json.loads(config.service_document_images)
            except json.JSONDecodeError:
                service_document_images = []
        
        # Lấy tên năm học
        school_year_name = frappe.db.get_value(
            "SIS School Year", 
            config.school_year_id, 
            ["title_vn", "title_en"],
            as_dict=True
        )
        
        # Tìm mức ưu đãi hiện tại
        current_discount = None
        for discount in discounts:
            if today <= getdate(discount.deadline):
                current_discount = discount
                break
        
        # Kiểm tra xem các học sinh đã nộp đơn chưa
        # Lưu ý: Bản ghi SIS Re-enrollment được tạo sẵn khi admin tạo đợt
        # PHHS "đã nộp" khi họ điền form và submit -> có submitted_at
        logs.append(f"Checking submissions for {len(students)} students, config: {config.name}")
        for student in students:
            # Tìm bản ghi của học sinh
            existing = frappe.db.get_value(
                "SIS Re-enrollment",
                {
                    "student_id": student["name"],
                    "config_id": config.name
                },
                ["name", "decision", "payment_type", "status", "submitted_at", "adjustment_status", "adjustment_requested_at"],
                as_dict=True
            )
            
            if existing:
                # Đã nộp = có submitted_at (PHHS đã điền form)
                student["has_submitted"] = bool(existing.submitted_at)
                student["submission"] = existing if existing.submitted_at else None
                student["re_enrollment_id"] = existing.name  # ID để update khi submit
                logs.append(f"Student {student['name']} - record: {existing.name}, submitted_at: {existing.submitted_at}")
            else:
                student["has_submitted"] = False
                student["submission"] = None
                student["re_enrollment_id"] = None
                logs.append(f"Student {student['name']} - no record found")
        
        logs.append(f"Tìm thấy config: {config.name}")
        
        return success_response(
            data={
                "config": {
                    "name": config.name,
                    "title": config.title,
                    "school_year_id": config.school_year_id,
                    "school_year_name_vn": school_year_name.title_vn if school_year_name else None,
                    "school_year_name_en": school_year_name.title_en if school_year_name else None,
                    "start_date": str(config.start_date),
                    "end_date": str(config.end_date),
                    "service_document": config.service_document,
                    "service_document_images": service_document_images,
                    "agreement_text": config.agreement_text,
                    "agreement_text_en": config.agreement_text_en
                },
                "discounts": discounts,
                "current_discount": current_discount,
                "questions": questions,
                "students": students,
                "status": "open"
            },
            message="Lấy cấu hình tái ghi danh thành công",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Parent Portal Get Re-enrollment Config Error")
        return error_response(
            message=f"Lỗi khi lấy cấu hình tái ghi danh: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def get_student_re_enrollment(student_id=None):
    """
    Lấy đơn tái ghi danh của học sinh (nếu có).
    Dùng để kiểm tra học sinh đã nộp đơn chưa.
    """
    logs = []
    
    try:
        # Lấy student_id từ query params nếu không truyền vào
        if not student_id:
            student_id = frappe.request.args.get('student_id')
        
        if not student_id:
            return validation_error_response(
                "Thiếu student_id", 
                {"student_id": ["Student ID là bắt buộc"]}
            )
        
        logs.append(f"Kiểm tra đơn tái ghi danh cho học sinh: {student_id}")
        
        # Kiểm tra phụ huynh có quyền xem không
        parent_id = _get_current_parent()
        if not parent_id:
            return error_response("Không tìm thấy thông tin phụ huynh", logs=logs)
        
        # Kiểm tra học sinh có thuộc phụ huynh này không
        relationship = frappe.db.exists(
            "CRM Family Relationship",
            {"guardian": parent_id, "student": student_id}
        )
        
        if not relationship:
            return error_response("Bạn không có quyền xem thông tin học sinh này", logs=logs)
        
        # Tìm config đang active
        campus_id = frappe.db.get_value("CRM Student", student_id, "campus_id")
        config = frappe.db.get_value(
            "SIS Re-enrollment Config",
            {"is_active": 1, "campus_id": campus_id},
            "name"
        )
        
        if not config:
            return success_response(
                data=None,
                message="Không có đợt tái ghi danh nào đang mở",
                logs=logs
            )
        
        # Tìm đơn đã nộp - lấy full doc để có answers và thông tin chi tiết
        re_enrollment_name = frappe.db.get_value(
            "SIS Re-enrollment",
            {"student_id": student_id, "config_id": config},
            "name"
        )
        
        if not re_enrollment_name:
            return success_response(
                data=None,
                message="Học sinh chưa nộp đơn tái ghi danh",
                logs=logs
            )
        
        logs.append(f"Tìm thấy đơn: {re_enrollment_name}")
        
        # Lấy full document để có answers và thông tin chi tiết (cho màn hình xem lại)
        doc = frappe.get_doc("SIS Re-enrollment", re_enrollment_name)
        
        # Lấy thông tin config cho fallback khi đợt đã đóng
        config_doc = frappe.db.get_value(
            "SIS Re-enrollment Config", doc.config_id,
            ["title", "school_year_id"],
            as_dict=True
        )
        school_year_names = {}
        if config_doc and config_doc.get("school_year_id"):
            school_year_names = frappe.db.get_value(
                "SIS School Year", config_doc.school_year_id,
                ["title_vn", "title_en"],
                as_dict=True
            ) or {}

        # Build response với đầy đủ thông tin
        submission_data = {
            "name": doc.name,
            "config_id": doc.config_id,
            "config_title": config_doc.title if config_doc else None,
            "school_year_name_vn": school_year_names.get("title_vn"),
            "school_year_name_en": school_year_names.get("title_en"),
            "student_id": doc.student_id,
            "student_name": doc.student_name,
            "student_code": doc.student_code,
            "current_class": doc.current_class,
            "decision": doc.decision,
            "decision_display": DECISION_DISPLAY_MAP_VI.get(doc.decision, doc.decision),
            "payment_type": doc.payment_type,
            "payment_display": "Đóng theo năm" if doc.payment_type == "annual" else "Đóng theo kỳ" if doc.payment_type == "semester" else None,
            "selected_discount_id": doc.selected_discount_id,
            "selected_discount_name": doc.selected_discount_name,
            "selected_discount_deadline": str(doc.selected_discount_deadline) if doc.selected_discount_deadline else None,
            "selected_discount_percent": doc.selected_discount_percent,
            "not_re_enroll_reason": doc.not_re_enroll_reason,
            "status": doc.status,
            "submitted_at": str(doc.submitted_at) if doc.submitted_at else None,
            "adjustment_status": doc.adjustment_status,
            "adjustment_requested_at": str(doc.adjustment_requested_at) if doc.adjustment_requested_at else None,
        }
        
        # Thêm answers (câu trả lời khảo sát)
        answers_list = []
        for ans in (doc.answers or []):
            answer_text = ans.selected_options_text_vn or ans.selected_options_text_en or ""
            selected_opts = ans.selected_options
            if selected_opts:
                selected_opts = json.loads(selected_opts) if isinstance(selected_opts, str) else selected_opts
            else:
                selected_opts = []
            answers_list.append({
                "question_id": ans.question_id,
                "question_text_vn": ans.question_text_vn,
                "question_text_en": ans.question_text_en,
                "answer": answer_text,
                "selected_options": selected_opts
            })
        submission_data["answers"] = answers_list
        
        return single_item_response(
            data=submission_data,
            message="Lấy thông tin đơn tái ghi danh thành công"
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Parent Portal Get Student Re-enrollment Error")
        return error_response(
            message=f"Lỗi khi lấy thông tin đơn tái ghi danh: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def submit_re_enrollment():
    """
    Nộp đơn tái ghi danh cho học sinh.
    Phụ huynh gọi API này để submit form tái ghi danh.
    """
    logs = []
    
    try:
        # Lấy data từ request
        if frappe.request.is_json:
            data = frappe.request.json or {}
        else:
            data = frappe.form_dict
        
        logs.append(f"Nhận request submit tái ghi danh: {json.dumps(data, default=str)}")
        
        # Validate required fields
        required_fields = ['student_id', 'decision']
        for field in required_fields:
            if field not in data or data[field] is None:
                return validation_error_response(
                    f"Thiếu trường bắt buộc: {field}",
                    {field: [f"Trường {field} là bắt buộc"]}
                )
        
        student_id = data['student_id']
        decision = data['decision']
        agreement_accepted = data.get('agreement_accepted', False)
        
        # Validate decision
        if decision not in DECISION_TYPES:
            return validation_error_response(
                "Quyết định không hợp lệ",
                {"decision": [f"Quyết định phải là một trong: {', '.join(DECISION_TYPES)}"]}
            )
        
        # Validate agreement chỉ bắt buộc cho re_enroll
        if decision == 're_enroll' and not agreement_accepted:
            return validation_error_response(
                "Bạn cần đồng ý với điều khoản",
                {"agreement_accepted": ["Vui lòng đọc và đồng ý với điều khoản"]}
            )
        
        # Validate conditional fields
        if decision == 're_enroll':
            if 'payment_type' not in data or not data['payment_type']:
                return validation_error_response(
                    "Vui lòng chọn phương thức thanh toán",
                    {"payment_type": ["Phương thức thanh toán là bắt buộc khi tái ghi danh"]}
                )
            if data['payment_type'] not in ['annual', 'semester']:
                return validation_error_response(
                    "Phương thức thanh toán không hợp lệ",
                    {"payment_type": ["Phương thức phải là 'annual' hoặc 'semester'"]}
                )
        
        # Validate reason cho considering và not_re_enroll
        if decision in ['considering', 'not_re_enroll']:
            reason = data.get('reason') or data.get('not_re_enroll_reason') or ''
            if not reason.strip():
                return validation_error_response(
                    "Vui lòng nhập lý do",
                    {"reason": ["Lý do là bắt buộc"]}
                )
        
        # Get current parent
        parent_id = _get_current_parent()
        if not parent_id:
            return error_response("Không tìm thấy thông tin phụ huynh", logs=logs)
        
        logs.append(f"Parent: {parent_id}")
        
        # Kiểm tra học sinh thuộc phụ huynh này
        relationship = frappe.db.exists(
            "CRM Family Relationship",
            {"guardian": parent_id, "student": student_id}
        )
        
        if not relationship:
            return error_response(
                "Bạn không có quyền nộp đơn cho học sinh này",
                logs=logs
            )
        
        # Lấy thông tin học sinh và campus
        student = frappe.get_doc("CRM Student", student_id)
        campus_id = student.campus_id
        
        # Tìm config đang active
        config = frappe.db.get_value(
            "SIS Re-enrollment Config",
            {"is_active": 1, "campus_id": campus_id},
            ["name", "start_date", "end_date"],
            as_dict=True
        )
        
        if not config:
            return error_response(
                "Không có đợt tái ghi danh nào đang mở",
                logs=logs
            )
        
        # Kiểm tra thời gian
        today = getdate(nowdate())
        if config.start_date and today < getdate(config.start_date):
            return error_response(
                f"Chưa đến thời gian tái ghi danh. Bắt đầu: {config.start_date}",
                logs=logs
            )
        
        if config.end_date and today > getdate(config.end_date):
            return error_response(
                f"Đã hết thời gian tái ghi danh. Kết thúc: {config.end_date}",
                logs=logs
            )
        
        logs.append(f"Config: {config.name}")
        
        # Tìm bản ghi tái ghi danh đã được tạo sẵn cho học sinh
        existing_record = frappe.db.get_value(
            "SIS Re-enrollment",
            {"student_id": student_id, "config_id": config.name},
            ["name", "submitted_at"],
            as_dict=True
        )
        
        if not existing_record:
            return error_response(
                "Không tìm thấy bản ghi tái ghi danh cho học sinh này. Vui lòng liên hệ nhà trường.",
                logs=logs
            )
        
        # Kiểm tra đã nộp chưa (submitted_at có giá trị = đã nộp)
        if existing_record.submitted_at:
            return error_response(
                f"Học sinh đã nộp đơn tái ghi danh. Mã đơn: {existing_record.name}",
                logs=logs
            )
        
        logs.append(f"Found existing record: {existing_record.name}")
        
        # Lấy lớp hiện tại
        current_class_info = _get_student_current_class(student_id, campus_id)
        current_class = current_class_info.get("class_title") if current_class_info else None
        
        # Lấy lý do từ request
        reason_value = data.get('reason') or data.get('not_re_enroll_reason') or None
        
        # Cập nhật bản ghi hiện có (không tạo mới)
        re_enrollment_doc = frappe.get_doc("SIS Re-enrollment", existing_record.name)
        re_enrollment_doc.guardian_id = parent_id
        re_enrollment_doc.current_class = current_class
        re_enrollment_doc.decision = decision
        re_enrollment_doc.payment_type = data.get('payment_type') if decision == 're_enroll' else None
        re_enrollment_doc.selected_discount_id = data.get('selected_discount_id') if decision == 're_enroll' else None
        re_enrollment_doc.not_re_enroll_reason = reason_value if decision in ['considering', 'not_re_enroll'] else None
        re_enrollment_doc.agreement_accepted = 1 if agreement_accepted else 0
        re_enrollment_doc.submitted_at = now()  # Đánh dấu đã nộp
        
        # Lưu thông tin chi tiết của discount (name, percent) nếu có
        if decision == 're_enroll' and data.get('selected_discount_id'):
            try:
                config_doc = frappe.get_doc("SIS Re-enrollment Config", config.name)
                payment_type = data.get('payment_type')
                for discount in config_doc.discounts:
                    if discount.name == data.get('selected_discount_id'):
                        re_enrollment_doc.selected_discount_name = discount.description
                        re_enrollment_doc.selected_discount_deadline = discount.deadline
                        # Lấy % giảm dựa trên payment_type
                        if payment_type == 'annual':
                            re_enrollment_doc.selected_discount_percent = discount.annual_discount
                        else:
                            re_enrollment_doc.selected_discount_percent = discount.semester_discount
                        break
            except Exception as e:
                logs.append(f"Lỗi khi lấy thông tin ưu đãi: {str(e)}")
        
        # Lấy tên phụ huynh để ghi log
        guardian_name = frappe.db.get_value("CRM Guardian", parent_id, "guardian_name") or "Phụ huynh"
        
        # Tạo log hệ thống - Phụ huynh nộp đơn
        decision_display = DECISION_DISPLAY_MAP_VI.get(decision, decision)
        log_content = f"Phụ huynh {guardian_name} đã nộp đơn tái ghi danh.\n• Quyết định: {decision_display}"
        if decision == 're_enroll':
            payment_display = "Đóng theo năm" if data.get('payment_type') == 'annual' else "Đóng theo kỳ"
            log_content += f"\n• Phương thức thanh toán: {payment_display}"
        elif decision in ['considering', 'not_re_enroll'] and reason_value:
            log_content += f"\n• Lý do: {reason_value}"
        
        re_enrollment_doc.append("notes", {
            "note_type": "system_log",
            "note": log_content,
            "created_by_name": guardian_name,
            "created_at": now()
        })
        
        # Xử lý answers (câu trả lời khảo sát) nếu có
        if decision == 're_enroll' and 'answers' in data:
            answers_data = data['answers']
            if isinstance(answers_data, str):
                answers_data = json.loads(answers_data)
            
            # Lấy config để map question info
            config_doc = frappe.get_doc("SIS Re-enrollment Config", config.name)
            questions_map = {q.name: q for q in config_doc.questions}
            
            # Clear existing answers
            re_enrollment_doc.answers = []
            
            # Add new answers
            for answer_item in answers_data:
                question_id = answer_item.get('question_id')
                answer_value = answer_item.get('answer')  # Có thể là string hoặc array
                
                # Lấy thông tin question
                question = questions_map.get(question_id)
                question_vn = question.question_vn if question else ''
                question_en = question.question_en if question else ''
                
                # Xử lý selected_options (có thể là string hoặc array)
                if isinstance(answer_value, list):
                    selected_options = answer_value
                    selected_text_vn = ', '.join(answer_value)
                    selected_text_en = ', '.join(answer_value)
                else:
                    selected_options = [answer_value] if answer_value else []
                    selected_text_vn = answer_value or ''
                    selected_text_en = answer_value or ''
                
                re_enrollment_doc.append("answers", {
                    "question_id": question_id,
                    "question_text_vn": question_vn,
                    "question_text_en": question_en,
                    "selected_options": json.dumps(selected_options),
                    "selected_options_text_vn": selected_text_vn,
                    "selected_options_text_en": selected_text_en
                })
            
            logs.append(f"Đã lưu {len(answers_data)} câu trả lời khảo sát")
        
        # Save với bypass permission
        re_enrollment_doc.flags.ignore_permissions = True
        re_enrollment_doc.save()
        
        frappe.db.commit()
        
        logs.append(f"Đã cập nhật đơn: {re_enrollment_doc.name}")
        
        # Lấy thông tin discount nếu có
        discount_name = None
        discount_percent = None
        if decision == 're_enroll' and data.get('selected_discount_id'):
            config_doc = frappe.get_doc("SIS Re-enrollment Config", config.name)
            for discount in config_doc.discounts:
                if discount.name == data.get('selected_discount_id'):
                    discount_name = discount.description
                    discount_percent = discount.annual_discount if data.get('payment_type') == 'annual' else discount.semester_discount
                    break
        
        # Lấy năm học
        school_year = ""
        try:
            config_doc = frappe.get_doc("SIS Re-enrollment Config", config.name) if not 'config_doc' in dir() else config_doc
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
        
        # Tạo announcement và gửi push notification
        try:
            # Lấy answers từ document để gửi vào announcement
            answers_for_announcement = []
            for answer in re_enrollment_doc.answers:
                answers_for_announcement.append({
                    'question_text_vn': answer.question_text_vn,
                    'question_text_en': answer.question_text_en,
                    'selected_options_text_vn': answer.selected_options_text_vn,
                    'selected_options_text_en': answer.selected_options_text_en
                })
            
            _create_re_enrollment_announcement(
                student_id=student_id,
                student_name=student.student_name,
                student_code=student.student_code,
                submission_data={
                    'decision': decision,
                    'payment_type': data.get('payment_type'),
                    'discount_name': discount_name,
                    'discount_percent': discount_percent,
                    'discount_deadline': str(re_enrollment_doc.selected_discount_deadline) if re_enrollment_doc.selected_discount_deadline else None,
                    'reason': reason_value,  # Lý do (cho considering/not_re_enroll)
                    'school_year': school_year,
                    'submitted_at': str(re_enrollment_doc.submitted_at),
                    'status': 'pending',
                    'answers': answers_for_announcement  # Câu trả lời khảo sát
                },
                is_update=False
            )
            logs.append("Đã tạo thông báo cho phụ huynh")
        except Exception as notif_err:
            logs.append(f"Lỗi tạo thông báo: {str(notif_err)}")
            frappe.logger().error(f"Error creating re-enrollment notification: {str(notif_err)}")
        
        # Chuẩn bị response
        decision_display_map = {
            're_enroll': 'Tái ghi danh',
            'considering': 'Đang cân nhắc',
            'not_re_enroll': 'Không tái ghi danh'
        }
        decision_display = decision_display_map.get(decision, decision)
        payment_display = ""
        if decision == 're_enroll':
            payment_display = "Đóng theo năm" if data.get('payment_type') == 'annual' else "Đóng theo kỳ"
        
        return success_response(
            data={
                "id": re_enrollment_doc.name,
                "student_id": student_id,
                "student_name": student.student_name,
                "decision": decision,
                "decision_display": decision_display,
                "payment_type": data.get('payment_type'),
                "payment_display": payment_display,
                "submitted_at": str(re_enrollment_doc.submitted_at)
            },
            message=f"Đã gửi đăng ký tái ghi danh thành công cho {student.student_name}",
            logs=logs
        )
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Parent Portal Submit Re-enrollment Error")
        return error_response(
            message=f"Lỗi khi nộp đơn tái ghi danh: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def get_my_re_enrollments():
    """
    Lấy danh sách tất cả đơn tái ghi danh của phụ huynh.
    Dùng để hiển thị lịch sử đơn đã nộp.
    """
    logs = []
    
    try:
        parent_id = _get_current_parent()
        if not parent_id:
            return error_response("Không tìm thấy thông tin phụ huynh", logs=logs)
        
        logs.append(f"Parent: {parent_id}")
        
        # Lấy tất cả học sinh của phụ huynh
        relationships = frappe.get_all(
            "CRM Family Relationship",
            filters={"guardian": parent_id},
            fields=["student"]
        )
        student_ids = [rel.student for rel in relationships]
        
        if not student_ids:
            return list_response([])
        
        # Lấy tất cả đơn tái ghi danh
        submissions = frappe.get_all(
            "SIS Re-enrollment",
            filters={"student_id": ["in", student_ids]},
            fields=[
                "name", "config_id", "student_id", "student_name", "student_code",
                "current_class", "decision", "payment_type", "not_re_enroll_reason",
                "status", "submitted_at"
            ],
            order_by="submitted_at desc"
        )
        
        # Thêm thông tin config cho mỗi đơn
        for submission in submissions:
            config_info = frappe.db.get_value(
                "SIS Re-enrollment Config",
                submission.config_id,
                ["title", "school_year_id"],
                as_dict=True
            )
            submission["config_title"] = config_info.title if config_info else None
            
            # Display values
            decision_display_map = {
                're_enroll': 'Tái ghi danh',
                'considering': 'Đang cân nhắc',
                'not_re_enroll': 'Không tái ghi danh'
            }
            submission["decision_display"] = decision_display_map.get(submission.decision, submission.decision)
            if submission.payment_type:
                submission["payment_display"] = "Đóng theo năm" if submission.payment_type == 'annual' else "Đóng theo kỳ"
            
            # Status display
            status_map = {
                "pending": "Chờ xử lý",
                "approved": "Đã duyệt",
                "rejected": "Từ chối"
            }
            submission["status_display"] = status_map.get(submission.status, submission.status)
        
        logs.append(f"Tìm thấy {len(submissions)} đơn")
        
        return list_response(submissions)
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Parent Portal Get My Re-enrollments Error")
        return error_response(
            message=f"Lỗi khi lấy danh sách đơn tái ghi danh: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def request_adjustment():
    """
    Phụ huynh yêu cầu điều chỉnh đơn tái ghi danh.
    Chỉ được yêu cầu khi đơn đã được nộp (submitted_at có giá trị).
    
    POST body: { "re_enrollment_id": "SIS-REENROLL-00001" }
    """
    logs = []
    
    try:
        # Lấy data từ request
        if frappe.request.is_json:
            data = frappe.request.json or {}
        else:
            data = frappe.form_dict
        
        re_enrollment_id = data.get('re_enrollment_id')
        
        if not re_enrollment_id:
            return validation_error_response(
                "Thiếu re_enrollment_id",
                {"re_enrollment_id": ["Re-enrollment ID là bắt buộc"]}
            )
        
        logs.append(f"Yêu cầu điều chỉnh đơn: {re_enrollment_id}")
        
        # Lấy thông tin phụ huynh
        parent_id = _get_current_parent()
        if not parent_id:
            return error_response("Không tìm thấy thông tin phụ huynh", logs=logs)
        
        logs.append(f"Parent ID: {parent_id}")
        
        # Kiểm tra đơn tồn tại
        if not frappe.db.exists("SIS Re-enrollment", re_enrollment_id):
            return not_found_response("Không tìm thấy đơn tái ghi danh")
        
        # Lấy thông tin đơn
        re_enrollment = frappe.get_doc("SIS Re-enrollment", re_enrollment_id)
        
        # Kiểm tra quyền: phụ huynh phải có quan hệ với học sinh trong đơn
        relationship = frappe.db.exists(
            "CRM Family Relationship",
            {"guardian": parent_id, "student": re_enrollment.student_id}
        )
        
        if not relationship:
            return error_response(
                "Bạn không có quyền yêu cầu điều chỉnh đơn này",
                logs=logs
            )
        
        # Kiểm tra đơn đã được nộp chưa
        if not re_enrollment.submitted_at:
            return error_response(
                "Đơn chưa được nộp, không thể yêu cầu điều chỉnh",
                logs=logs
            )
        
        # Kiểm tra đã yêu cầu điều chỉnh chưa
        if re_enrollment.adjustment_status == 'requested':
            return error_response(
                "Đơn đã được yêu cầu điều chỉnh trước đó",
                logs=logs
            )
        
        # Cập nhật trạng thái điều chỉnh
        re_enrollment.adjustment_status = 'requested'
        re_enrollment.adjustment_requested_at = now()
        
        # Lấy tên phụ huynh để ghi log
        guardian_name = frappe.db.get_value("CRM Guardian", parent_id, "guardian_name") or "Phụ huynh"
        
        # Tạo log hệ thống
        re_enrollment.append("notes", {
            "note_type": "system_log",
            "note": f"Phụ huynh {guardian_name} đã yêu cầu điều chỉnh đơn tái ghi danh.",
            "created_by_name": guardian_name,
            "created_at": now()
        })
        
        re_enrollment.flags.ignore_permissions = True
        re_enrollment.save()
        frappe.db.commit()
        
        logs.append(f"Đã cập nhật trạng thái điều chỉnh cho đơn: {re_enrollment_id}")
        
        # Gửi email thông báo đến bộ phận tuyển sinh
        try:
            email_result = _send_adjustment_notification_email(
                student_name=re_enrollment.student_name,
                student_code=re_enrollment.student_code,
                requested_at=re_enrollment.adjustment_requested_at,
                re_enrollment_id=re_enrollment_id,
                config_id=re_enrollment.config_id
            )
            if email_result.get('success'):
                logs.append("Đã gửi email thông báo đến bộ phận tuyển sinh")
            else:
                logs.append(f"Không thể gửi email thông báo: {email_result.get('message')}")
        except Exception as email_err:
            # Không throw lỗi nếu gửi email thất bại - vẫn trả về success cho user
            logs.append(f"Lỗi gửi email thông báo: {str(email_err)}")
            frappe.logger().error(f"Failed to send adjustment notification email: {str(email_err)}")
        
        return success_response(
            data={
                "re_enrollment_id": re_enrollment_id,
                "adjustment_status": "requested",
                "adjustment_requested_at": str(re_enrollment.adjustment_requested_at)
            },
            message="Yêu cầu điều chỉnh đã được gửi thành công. Bộ phận tuyển sinh sẽ liên hệ với bạn.",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Parent Portal Request Adjustment Error")
        return error_response(
            message=f"Lỗi khi yêu cầu điều chỉnh: {str(e)}",
            logs=logs
        )

