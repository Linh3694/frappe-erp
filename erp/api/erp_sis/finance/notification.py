"""
Fee Notification APIs
Quản lý thông báo phí đến phụ huynh.
"""

import frappe
from frappe import _
import json

from erp.utils.api_response import (
    validation_error_response,
    list_response,
    error_response,
    success_response
)

from .utils import (
    _check_admin_permission, 
    _get_request_data,
    _format_currency_vnd, 
    _apply_mail_merge
)


@frappe.whitelist()
def create_fee_notification():
    """
    Tạo thông báo phí với mail merge cho từng học sinh.
    
    Request body:
    - order_id: ID của Finance Order
    - title_en: Tiêu đề tiếng Anh (có thể chứa mail merge placeholders)
    - title_vn: Tiêu đề tiếng Việt (có thể chứa mail merge placeholders)
    - content_en: Nội dung tiếng Anh (có thể chứa mail merge placeholders)
    - content_vn: Nội dung tiếng Việt (có thể chứa mail merge placeholders)
    - student_ids: Danh sách order_student_id hoặc "all" để gửi tất cả
    - include_debit_note: Có đính kèm link Debit Note không
    - send_immediately: Gửi ngay hay lưu nháp
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền truy cập", logs=logs)
        
        # Lấy dữ liệu từ request
        data = _get_request_data()
        logs.append(f"Received data keys: {list(data.keys())}")
        
        order_id = data.get("order_id")
        title_en = data.get("title_en", "").strip()
        title_vn = data.get("title_vn", "").strip()
        content_en = data.get("content_en", "").strip()
        content_vn = data.get("content_vn", "").strip()
        student_ids = data.get("student_ids", [])
        include_debit_note = data.get("include_debit_note", False)
        send_immediately = data.get("send_immediately", False)
        
        # Validate dữ liệu đầu vào
        if not order_id:
            return validation_error_response("Thiếu order_id", {"order_id": ["Bắt buộc"]})
        
        if not title_en or not title_vn:
            return validation_error_response(
                "Cần có tiêu đề cả tiếng Anh và tiếng Việt",
                {"title": ["Bắt buộc"]}
            )
        
        if not content_en or not content_vn:
            return validation_error_response(
                "Cần có nội dung cả tiếng Anh và tiếng Việt",
                {"content": ["Bắt buộc"]}
            )
        
        # Lấy thông tin order
        order_doc = frappe.get_doc("SIS Finance Order", order_id)
        logs.append(f"Order: {order_doc.title}")
        
        # Lấy campus_id từ finance_year
        finance_year = frappe.get_doc("SIS Finance Year", order_doc.finance_year)
        campus_id = finance_year.campus_id or "campus-1"
        
        # Lấy deadline gần nhất từ milestones
        nearest_deadline = ""
        milestones = frappe.get_all(
            "SIS Finance Deadline Milestone",
            filters={"parent": order_id},
            fields=["deadline_date", "title"],
            order_by="deadline_date asc"
        )
        if milestones:
            # Tìm milestone gần nhất chưa qua
            today = frappe.utils.today()
            for m in milestones:
                if m.deadline_date and str(m.deadline_date) >= today:
                    nearest_deadline = frappe.utils.format_date(m.deadline_date, "dd/MM/yyyy")
                    break
            # Nếu tất cả đã qua, lấy cái cuối cùng
            if not nearest_deadline and milestones:
                nearest_deadline = frappe.utils.format_date(milestones[-1].deadline_date, "dd/MM/yyyy")
        
        logs.append(f"Nearest deadline: {nearest_deadline}")
        
        # Lấy danh sách học sinh cần gửi
        if student_ids == "all" or (isinstance(student_ids, list) and len(student_ids) == 0):
            # Lấy tất cả học sinh trong order
            order_students = frappe.get_all(
                "SIS Finance Order Student",
                filters={"parent": order_id},
                fields=["name", "finance_student_id", "total_amount"]
            )
        else:
            # Lấy học sinh theo danh sách
            if isinstance(student_ids, str):
                student_ids = json.loads(student_ids)
            order_students = frappe.get_all(
                "SIS Finance Order Student",
                filters={"name": ["in", student_ids]},
                fields=["name", "finance_student_id", "total_amount"]
            )
        
        if not order_students:
            return validation_error_response(
                "Không tìm thấy học sinh nào",
                {"student_ids": ["Không có học sinh"]}
            )
        
        logs.append(f"Processing {len(order_students)} students")
        
        # Tạo announcement cho từng học sinh
        created_announcements = []
        
        for os in order_students:
            # Lấy thông tin chi tiết học sinh
            finance_student = frappe.get_doc("SIS Finance Student", os.finance_student_id)
            
            # Chuẩn bị dữ liệu mail merge
            student_data = {
                "student_name": finance_student.student_name or "",
                "student_code": finance_student.student_code or "",
                "class_name": finance_student.class_title or "",
                "total_amount": os.total_amount or 0,
                "deadline": nearest_deadline,
            }
            
            # Áp dụng mail merge cho tiêu đề và nội dung
            merged_title_en = _apply_mail_merge(title_en, student_data)
            merged_title_vn = _apply_mail_merge(title_vn, student_data)
            merged_content_en = _apply_mail_merge(content_en, student_data)
            merged_content_vn = _apply_mail_merge(content_vn, student_data)
            
            # Tạo announcement
            announcement = frappe.get_doc({
                "doctype": "SIS Announcement",
                "campus_id": campus_id,
                "announcement_type": "fee_notification",
                "finance_order_id": order_id,
                "finance_student_id": os.finance_student_id,
                "order_student_id": os.name,
                "include_debit_note_link": 1 if include_debit_note else 0,
                "title_en": merged_title_en,
                "title_vn": merged_title_vn,
                "content_en": merged_content_en,
                "content_vn": merged_content_vn,
                "recipient_type": "specific",
                "recipients": json.dumps([{
                    "id": finance_student.student_id,
                    "type": "student"
                }]),
                "status": "draft",
                "sent_by": frappe.session.user,
            })
            
            announcement.insert()
            logs.append(f"Created announcement {announcement.name} for {finance_student.student_name}")
            
            # Nếu gửi ngay
            if send_immediately:
                try:
                    from erp.utils.notification_handler import send_bulk_parent_notifications
                    
                    notification_result = send_bulk_parent_notifications(
                        recipient_type="announcement",
                        recipients_data={
                            "student_ids": [finance_student.student_id],
                            "recipients": [{"id": finance_student.student_id, "type": "student"}],
                            "announcement_id": announcement.name
                        },
                        title="Thông báo phí",
                        body=merged_title_vn,
                        icon="/icon.png",
                        data={
                            "type": "fee_notification",
                            "announcement_id": announcement.name,
                            "order_id": order_id,
                            "order_student_id": os.name,
                            "include_debit_note": include_debit_note,
                            "url": f"/announcement/{announcement.name}"
                        }
                    )
                    
                    announcement.status = "sent"
                    announcement.sent_at = frappe.utils.now()
                    announcement.sent_count = notification_result.get("total_parents", 0)
                    announcement.save()
                    
                    logs.append(f"Sent notification for {announcement.name}")
                    
                except Exception as e:
                    logs.append(f"Error sending notification: {str(e)}")
            
            created_announcements.append({
                "name": announcement.name,
                "student_name": finance_student.student_name,
                "status": announcement.status,
            })
        
        frappe.db.commit()
        
        return success_response(
            message=f"Đã tạo {len(created_announcements)} thông báo phí",
            data={
                "announcements": created_announcements,
                "total": len(created_announcements),
                "sent_immediately": send_immediately
            },
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        import traceback
        logs.append(traceback.format_exc())
        return error_response(f"Lỗi: {str(e)}", logs=logs)


@frappe.whitelist()
def get_fee_notifications(order_id=None):
    """
    Lấy danh sách thông báo phí của một order.
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền truy cập", logs=logs)
        
        if not order_id:
            order_id = frappe.request.args.get('order_id')
        
        if not order_id:
            return validation_error_response("Thiếu order_id", {"order_id": ["Bắt buộc"]})
        
        # Lấy danh sách thông báo phí
        notifications = frappe.get_all(
            "SIS Announcement",
            filters={
                "announcement_type": "fee_notification",
                "finance_order_id": order_id
            },
            fields=[
                "name", "title_vn", "title_en", "status", "sent_at", "sent_by",
                "finance_student_id", "order_student_id", "include_debit_note_link",
                "recipient_count", "sent_count", "creation"
            ],
            order_by="creation desc"
        )
        
        # Enrich với thông tin học sinh
        for notif in notifications:
            if notif.get("finance_student_id"):
                try:
                    fs = frappe.get_doc("SIS Finance Student", notif["finance_student_id"])
                    notif["student_name"] = fs.student_name
                    notif["student_code"] = fs.student_code
                    notif["class_title"] = fs.class_title
                except:
                    pass
            
            # Thêm thông tin người gửi
            if notif.get("sent_by"):
                try:
                    user = frappe.get_doc("User", notif["sent_by"])
                    notif["sent_by_fullname"] = user.full_name or notif["sent_by"]
                except:
                    notif["sent_by_fullname"] = notif["sent_by"]
        
        return list_response(notifications, logs=logs)
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        return error_response(f"Lỗi: {str(e)}", logs=logs)


@frappe.whitelist()
def delete_fee_notification():
    """
    Xóa thông báo phí.
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền truy cập", logs=logs)
        
        data = _get_request_data()
        notification_id = data.get("notification_id")
        
        if not notification_id:
            return validation_error_response("Thiếu notification_id", {"notification_id": ["Bắt buộc"]})
        
        # Kiểm tra announcement tồn tại và đúng loại
        announcement = frappe.get_doc("SIS Announcement", notification_id)
        
        if announcement.announcement_type != "fee_notification":
            return validation_error_response(
                "Chỉ có thể xóa thông báo phí",
                {"notification_id": ["Không phải thông báo phí"]}
            )
        
        # Xóa announcement
        frappe.delete_doc("SIS Announcement", notification_id)
        frappe.db.commit()
        
        logs.append(f"Đã xóa thông báo {notification_id}")
        
        return success_response(
            message="Đã xóa thông báo phí",
            logs=logs
        )
        
    except frappe.DoesNotExistError:
        return error_response("Không tìm thấy thông báo", logs=logs)
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        return error_response(f"Lỗi: {str(e)}", logs=logs)


@frappe.whitelist()
def send_fee_notification():
    """
    Gửi thông báo phí đã lưu nháp.
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền truy cập", logs=logs)
        
        data = _get_request_data()
        notification_id = data.get("notification_id")
        
        if not notification_id:
            return validation_error_response("Thiếu notification_id", {"notification_id": ["Bắt buộc"]})
        
        # Lấy announcement
        announcement = frappe.get_doc("SIS Announcement", notification_id)
        
        if announcement.announcement_type != "fee_notification":
            return validation_error_response(
                "Chỉ có thể gửi thông báo phí",
                {"notification_id": ["Không phải thông báo phí"]}
            )
        
        if announcement.status == "sent":
            return validation_error_response(
                "Thông báo đã được gửi rồi",
                {"notification_id": ["Đã gửi"]}
            )
        
        # Lấy thông tin học sinh
        finance_student = frappe.get_doc("SIS Finance Student", announcement.finance_student_id)
        
        # Gửi notification
        from erp.utils.notification_handler import send_bulk_parent_notifications
        
        notification_result = send_bulk_parent_notifications(
            recipient_type="announcement",
            recipients_data={
                "student_ids": [finance_student.student_id],
                "recipients": [{"id": finance_student.student_id, "type": "student"}],
                "announcement_id": announcement.name
            },
            title="Thông báo phí",
            body=announcement.title_vn or announcement.title_en,
            icon="/icon.png",
            data={
                "type": "fee_notification",
                "announcement_id": announcement.name,
                "order_id": announcement.finance_order_id,
                "order_student_id": announcement.order_student_id,
                "include_debit_note": announcement.include_debit_note_link,
                "url": f"/announcement/{announcement.name}"
            }
        )
        
        # Cập nhật trạng thái
        announcement.status = "sent"
        announcement.sent_at = frappe.utils.now()
        announcement.sent_count = notification_result.get("total_parents", 0)
        announcement.save()
        
        frappe.db.commit()
        
        logs.append(f"Đã gửi thông báo {notification_id}")
        
        return success_response(
            message="Đã gửi thông báo phí",
            data={
                "notification_id": notification_id,
                "sent_count": announcement.sent_count
            },
            logs=logs
        )
        
    except frappe.DoesNotExistError:
        return error_response("Không tìm thấy thông báo", logs=logs)
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        return error_response(f"Lỗi: {str(e)}", logs=logs)
