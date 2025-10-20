"""
Notification Center API for Parent Portal
Xử lý notification center - lấy, đánh dấu đã đọc, xóa notifications
Kết nối với notification-service (MongoDB) để lấy data
"""

import frappe
import json
import requests
from frappe import _
from datetime import datetime

def get_notification_service_url():
    """Lấy URL của notification service từ config"""
    return frappe.conf.get("notification_service_url", "http://172.16.20.115:5001")


@frappe.whitelist(allow_guest=False, methods=["POST"])
def get_notifications(student_id=None, type=None, status=None, limit=10, offset=0, include_read=True):
    """
    Lấy danh sách thông báo cho parent portal
    
    Args:
        student_id: ID của học sinh (optional, nếu không có sẽ lấy tất cả con của guardian)
        type: Loại thông báo (attendance, contact_log, report_card, announcement, news, leave, system)
        status: Trạng thái (unread, read)
        limit: Số lượng notifications
        offset: Vị trí bắt đầu
        include_read: Có bao gồm tin đã đọc không
        
    Returns:
        {
            "success": True,
            "data": {
                "notifications": [...],
                "unread_count": 5,
                "total": 100
            }
        }
    """
    try:
        user = frappe.session.user
        
        # Parse limit và offset
        limit = int(limit) if limit else 10
        offset = int(offset) if offset else 0
        
        # Tính page từ offset - TẠM THỜI lấy tất cả (limit = 200)
        limit = 200  # Lấy nhiều notifications
        page = (offset // limit) + 1 if limit > 0 else 1
        
        print(f"📥 [Notification Center] Getting notifications for user: {user}, limit: {limit}")
        
        # Gọi notification-service API để lấy notifications
        notification_service_url = get_notification_service_url()
        api_url = f"{notification_service_url}/api/notifications/user/{user}"
        
        params = {
            "page": page,
            "limit": limit
        }
        
        print(f"📡 [Notification Center] Calling: {api_url} with params: {params}")
        
        response = requests.get(api_url, params=params, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        print(f"✅ [Notification Center] Got response from notification-service")
        
        # Parse notifications từ response
        raw_notifications = data.get('notifications', [])
        
        print(f"📊 [Notification Center] Raw notifications count: {len(raw_notifications)}")
        
        # Transform notifications sang format frontend cần
        notifications = []
        error_count = 0
        
        for idx, notif in enumerate(raw_notifications):
            try:
                print(f"🔄 [Notification Center] Processing notification {idx + 1}/{len(raw_notifications)}")
                print(f"   Raw notif keys: {list(notif.keys())}")
                print(f"   Type: {notif.get('type')}, Title: {notif.get('title')}")
                
                # Xác định type dựa vào notif.type và notif.data
                notif_type = map_notification_type(notif.get('type'), notif.get('data', {}))
                
                # Check read status
                is_read = notif.get('read', False)
                
                # Build notification object TRƯỚC KHI filter
                notification = {
                    "id": str(notif.get('_id', '')),
                    "type": notif_type,
                    "title": notif.get('title', 'No title'),
                    "message": notif.get('message', 'No message'),
                    "status": "read" if is_read else "unread",
                    "priority": notif.get('priority', 'normal'),
                    "created_at": notif.get('createdAt', notif.get('timestamp', datetime.now().isoformat())),
                    "read_at": notif.get('readAt') if is_read else None,
                    "student_id": get_student_id_from_notification(notif),
                    "student_name": get_student_name_from_notification(notif),
                    "action_url": generate_action_url(notif_type, notif.get('data', {})),
                    "data": notif.get('data', {})
                }
                
                print(f"   ✅ Built notification: {notification['id']}, type: {notification['type']}")
                
                # KHÔNG FILTER GÌ CẢ - lấy hết để debug
                # Filter sẽ được làm ở client side
                notifications.append(notification)
                
            except Exception as e:
                error_count += 1
                print(f"❌ [Notification Center] Error processing notification {idx + 1}: {str(e)}")
                import traceback
                print(traceback.format_exc())
                continue
        
        print(f"📊 [Notification Center] Processed: {len(notifications)} success, {error_count} errors")
        
        # Calculate unread count từ raw data
        unread_count = sum(1 for n in raw_notifications if not n.get('read', False))
        
        print(f"✅ [Notification Center] Filtered notifications count: {len(notifications)}, unread: {unread_count}")
        
        return {
            "success": True,
            "data": {
                "notifications": notifications,
                "unread_count": unread_count,
                "total": data.get('pagination', {}).get('total', len(notifications))
            }
        }
        
    except requests.exceptions.RequestException as e:
        frappe.log_error(f"Error calling notification service: {str(e)}", "Notification Center Error")
        print(f"❌ [Notification Center] Request error: {str(e)}")
        return {
            "success": False,
            "data": {
                "notifications": [],
                "unread_count": 0,
                "total": 0
            },
            "message": "Cannot connect to notification service"
        }
    except Exception as e:
        frappe.log_error(f"Error getting notifications: {str(e)}", "Notification Center Error")
        print(f"❌ [Notification Center] Error: {str(e)}")
        return {
            "success": False,
            "data": {
                "notifications": [],
                "unread_count": 0,
                "total": 0
            },
            "message": str(e)
        }


@frappe.whitelist(allow_guest=False, methods=["POST"])
def get_unread_count(student_id=None):
    """
    Lấy số lượng thông báo chưa đọc
    
    Args:
        student_id: ID của học sinh (optional)
        
    Returns:
        {
            "success": True,
            "data": {
                "unread_count": 5
            }
        }
    """
    try:
        user = frappe.session.user
        
        # Gọi notification-service
        notification_service_url = get_notification_service_url()
        api_url = f"{notification_service_url}/api/notifications/user/{user}/unread-count"
        
        response = requests.get(api_url, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        unread_count = data.get('unreadCount', 0)
        
        return {
            "success": True,
            "data": {
                "unread_count": unread_count
            }
        }
        
    except Exception as e:
        frappe.log_error(f"Error getting unread count: {str(e)}", "Notification Center Error")
        return {
            "success": False,
            "data": {
                "unread_count": 0
            },
            "message": str(e)
        }


@frappe.whitelist(allow_guest=False, methods=["POST"])
def mark_as_read(notification_id=None):
    """
    Đánh dấu một thông báo là đã đọc
    
    Args:
        notification_id: ID của notification
        
    Returns:
        {
            "success": True,
            "message": "Notification marked as read"
        }
    """
    try:
        user = frappe.session.user
        
        if not notification_id:
            return {
                "success": False,
                "message": "notification_id is required"
            }
        
        # Gọi notification-service để mark as read
        notification_service_url = get_notification_service_url()
        api_url = f"{notification_service_url}/api/notifications/{notification_id}/read"
        
        payload = {
            "userId": user
        }
        
        response = requests.post(api_url, json=payload, timeout=10)
        response.raise_for_status()
        
        return {
            "success": True,
            "message": "Notification marked as read"
        }
        
    except Exception as e:
        frappe.log_error(f"Error marking notification as read: {str(e)}", "Notification Center Error")
        return {
            "success": False,
            "message": str(e)
        }


@frappe.whitelist(allow_guest=False, methods=["POST"])
def mark_all_as_read(student_id=None):
    """
    Đánh dấu tất cả thông báo là đã đọc
    
    Args:
        student_id: ID của học sinh (optional)
        
    Returns:
        {
            "success": True,
            "message": "All notifications marked as read"
        }
    """
    try:
        user = frappe.session.user
        
        # Gọi notification-service để mark all as read
        notification_service_url = get_notification_service_url()
        api_url = f"{notification_service_url}/api/notifications/user/{user}/mark-all-read"
        
        response = requests.post(api_url, timeout=10)
        response.raise_for_status()
        
        return {
            "success": True,
            "message": "All notifications marked as read"
        }
        
    except Exception as e:
        frappe.log_error(f"Error marking all as read: {str(e)}", "Notification Center Error")
        return {
            "success": False,
            "message": str(e)
        }


@frappe.whitelist(allow_guest=False, methods=["POST"])
def delete_notification(notification_id=None):
    """
    Xóa một thông báo (soft delete)
    
    Args:
        notification_id: ID của notification
        
    Returns:
        {
            "success": True,
            "message": "Notification deleted"
        }
    """
    try:
        user = frappe.session.user
        
        if not notification_id:
            return {
                "success": False,
                "message": "notification_id is required"
            }
        
        # Đối với parent portal, chúng ta chỉ mark as deleted trong NotificationRead
        # Không xóa notification gốc trong notification-service
        notification_service_url = get_notification_service_url()
        api_url = f"{notification_service_url}/api/notifications/{notification_id}/delete"
        
        payload = {
            "userId": user
        }
        
        response = requests.post(api_url, json=payload, timeout=10)
        response.raise_for_status()
        
        return {
            "success": True,
            "message": "Notification deleted"
        }
        
    except Exception as e:
        frappe.log_error(f"Error deleting notification: {str(e)}", "Notification Center Error")
        return {
            "success": False,
            "message": str(e)
        }


# Helper functions

def map_notification_type(notif_type, data):
    """
    Map notification type từ notification-service sang frontend type
    
    notification-service types: attendance, ticket, chat, system, post
    frontend types: attendance, contact_log, report_card, announcement, news, leave, system
    """
    # Check data.type hoặc data.notificationType trước
    custom_type = data.get('type') or data.get('notificationType')
    
    print(f"🔍 [map_notification_type] notif_type={notif_type}, custom_type={custom_type}")
    
    if custom_type == 'contact_log':
        return 'contact_log'
    elif custom_type == 'report_card':
        return 'report_card'
    elif custom_type == 'student_attendance' or custom_type == 'attendance':
        return 'attendance'
    elif custom_type == 'announcement':
        return 'announcement'
    elif custom_type == 'news':
        return 'news'
    elif custom_type == 'leave':
        return 'leave'
    
    # Fallback to notif_type
    if notif_type == 'attendance':
        return 'attendance'
    elif notif_type == 'post':
        return 'news'
    elif notif_type == 'system':
        # Nếu trong data có type khác, ưu tiên type đó
        if 'type' in data:
            return data['type']
        return 'system'
    
    print(f"⚠️ [map_notification_type] Unknown type, defaulting to system")
    return 'system'


def get_student_id_from_notification(notif):
    """Extract student_id từ notification data"""
    data = notif.get('data', {})
    student_id = data.get('student_id') or data.get('studentId') or data.get('studentCode')
    print(f"🔍 [get_student_id] Extracted: {student_id} from data: {list(data.keys())}")
    return student_id


def get_student_name_from_notification(notif):
    """Extract student_name từ notification data"""
    data = notif.get('data', {})
    return data.get('student_name') or data.get('studentName') or data.get('employeeName')


def generate_action_url(notif_type, data):
    """
    Generate action URL để navigate khi click vào notification
    """
    student_id = data.get('student_id') or data.get('studentId')
    
    if notif_type == 'attendance':
        return f"/attendance?student={student_id}" if student_id else "/attendance"
    
    elif notif_type == 'contact_log':
        return f"/communication?student={student_id}" if student_id else "/communication"
    
    elif notif_type == 'report_card':
        report_id = data.get('report_card_id') or data.get('reportId')
        if report_id and student_id:
            return f"/report-card?student={student_id}&report={report_id}"
        return f"/report-card?student={student_id}" if student_id else "/report-card"
    
    elif notif_type == 'news':
        news_id = data.get('news_id') or data.get('newsId')
        return f"/news/{news_id}" if news_id else "/news"
    
    elif notif_type == 'leave':
        return f"/leave?student={student_id}" if student_id else "/leave"
    
    return None

