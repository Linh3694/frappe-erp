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
        
        print(f"📡 [Notification Center] Calling: {api_url}")
        print(f"   Params: {params}")
        
        response = requests.get(api_url, params=params, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        print(f"✅ [Notification Center] Response status: {response.status_code}")
        print(f"   Response keys: {list(data.keys())}")
        
        # Parse notifications từ response - check multiple possible locations
        raw_notifications = []
        
        # Try different response structures
        if 'notifications' in data:
            raw_notifications = data.get('notifications', [])
            print(f"   Found notifications in root: {len(raw_notifications)}")
        elif 'data' in data and isinstance(data['data'], list):
            raw_notifications = data['data']
            print(f"   Found notifications in data: {len(raw_notifications)}")
        elif 'data' in data and isinstance(data['data'], dict) and 'notifications' in data['data']:
            raw_notifications = data['data']['notifications']
            print(f"   Found notifications in data.notifications: {len(raw_notifications)}")
        else:
            print(f"   ⚠️ Could not find notifications in response")
            print(f"   Full response structure: {json.dumps(data, indent=2, default=str)[:500]}")
        
        print(f"   Pagination: {data.get('pagination', {})}")
        
        print(f"📊 [Notification Center] Raw notifications count: {len(raw_notifications)}")
        
        # Transform notifications sang format frontend cần
        notifications = []
        error_count = 0
        debug_logs = []
        
        debug_logs.append(f"Filter: student_id={student_id}, type={type}, status={status}, include_read={include_read}")
        debug_logs.append(f"Raw notifications count: {len(raw_notifications)}")
        
        for idx, notif in enumerate(raw_notifications):
            try:
                # Chỉ log chi tiết cho 5 notifications đầu
                if idx < 5:
                    debug_logs.append(f"Processing {idx + 1}/{len(raw_notifications)}")
                    debug_logs.append(f"  Keys: {list(notif.keys())}")
                    debug_logs.append(f"  Type: {notif.get('type')}, Title: {notif.get('title')}")
                elif idx == 5:
                    debug_logs.append(f"... (logging first 5 only, still processing all {len(raw_notifications)})")
                
                # Xác định type dựa vào notif.type và notif.data
                notif_type = map_notification_type(notif.get('type'), notif.get('data', {}))
                
                # Check read status
                is_read = notif.get('read', False)
                
                # Build notification object TRƯỚC KHI filter
                # Clean up title, message, student_name (remove extra whitespace and newlines)
                title = (notif.get('title', 'No title') or 'No title').strip()
                message = (notif.get('message', 'No message') or 'No message').strip()
                student_name = get_student_name_from_notification(notif)
                if student_name:
                    student_name = student_name.strip()
                
                notification = {
                    "id": str(notif.get('_id', '')),
                    "type": notif_type,
                    "title": title,
                    "message": message,
                    "status": "read" if is_read else "unread",
                    "priority": notif.get('priority', 'normal'),
                    "created_at": notif.get('createdAt', notif.get('timestamp', datetime.now().isoformat())),
                    "read_at": notif.get('readAt') if is_read else None,
                    "student_id": get_student_id_from_notification(notif),
                    "student_name": student_name,
                    "action_url": generate_action_url(notif_type, notif.get('data', {})),
                    "data": notif.get('data', {})
                }
                
                if idx < 5:
                    debug_logs.append(f"  ✅ Built: {notification['id']}, type: {notification['type']}")
                
                # Filter theo student_id nếu có
                if student_id:
                    notif_student_id = notification.get('student_id')
                    # Chỉ lấy notifications của student này HOẶC notifications không có student_id (general)
                    if notif_student_id and notif_student_id != student_id:
                        continue
                
                # Filter theo type nếu có
                if type and type != 'all' and notification['type'] != type:
                    continue
                
                # Filter theo status nếu có
                if status == 'unread' and notification['status'] != 'unread':
                    continue
                elif status == 'read' and notification['status'] != 'read':
                    continue
                
                # Filter theo include_read
                if not include_read and notification['status'] == 'read':
                    continue
                
                notifications.append(notification)
                
            except Exception as e:
                error_count += 1
                error_msg = f"❌ Error at {idx + 1}: {str(e)}"
                debug_logs.append(error_msg)
                import traceback
                debug_logs.append(traceback.format_exc())
                continue
        
        debug_logs.append(f"Final: {len(notifications)} success, {error_count} errors")
        
        # Calculate unread count từ raw data
        unread_count = sum(1 for n in raw_notifications if not n.get('read', False))
        
        print(f"✅ [Notification Center] Filtered notifications count: {len(notifications)}, unread: {unread_count}")
        
        return {
            "success": True,
            "data": {
                "notifications": notifications,
                "unread_count": unread_count,
                "total": data.get('pagination', {}).get('total', len(notifications))
            },
            "debug_logs": debug_logs  # Thêm logs để debug
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

        # Parse notification_id from JSON body if not provided as parameter
        if not notification_id and frappe.request.data:
            try:
                import json
                json_data = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
                notification_id = json_data.get('notification_id')
                print(f"📥 [Notification Center] Parsed notification_id from JSON body: {notification_id}")
            except Exception as e:
                print(f"❌ [Notification Center] Failed to parse JSON body: {str(e)}")

        if not notification_id:
            print(f"❌ [Notification Center] notification_id is still required after parsing")
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

        # Parse notification_id from JSON body if not provided as parameter
        if not notification_id and frappe.request.data:
            try:
                import json
                json_data = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
                notification_id = json_data.get('notification_id')
                print(f"📥 [Notification Center] Parsed notification_id from JSON body: {notification_id}")
            except Exception as e:
                print(f"❌ [Notification Center] Failed to parse JSON body: {str(e)}")

        if not notification_id:
            print(f"❌ [Notification Center] notification_id is still required after parsing")
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
    Bao gồm student parameter để tự động chọn học sinh
    """
    # Extract student_id từ nhiều field có thể
    student_id = data.get('student_id') or data.get('studentId') or data.get('studentCode')
    
    # Build base URL với student parameter
    if notif_type == 'attendance':
        base_url = "/attendance"
        return f"{base_url}?student={student_id}" if student_id else base_url
    
    elif notif_type == 'contact_log':
        base_url = "/communication"
        return f"{base_url}?student={student_id}" if student_id else base_url
    
    elif notif_type == 'report_card':
        base_url = "/report-card"
        report_id = data.get('report_card_id') or data.get('reportId')
        if student_id:
            if report_id:
                return f"{base_url}?student={student_id}&report={report_id}"
            return f"{base_url}?student={student_id}"
        return base_url
    
    elif notif_type == 'announcement':
        base_url = "/announcements"
        announcement_id = data.get('announcement_id') or data.get('announcementId')
        if announcement_id:
            return f"{base_url}/{announcement_id}"
        return base_url
    
    elif notif_type == 'news':
        base_url = "/news"
        news_id = data.get('news_id') or data.get('newsId') or data.get('postId')
        if news_id:
            return f"{base_url}/{news_id}"
        return base_url
    
    elif notif_type == 'leave':
        base_url = "/leaves"
        return f"{base_url}?student={student_id}" if student_id else base_url
    
    # Default
    return "/dashboard"

