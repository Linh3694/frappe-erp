"""
Notification Center API for Parent Portal
Xử lý notification center - lấy, đánh dấu đã đọc, xóa notifications
Query directly from Frappe ERP Notification DocType
"""

import frappe
import json
from frappe import _
from datetime import datetime
from erp.common.doctype.erp_notification.erp_notification import (
	get_user_notifications,
	get_unread_count as get_unread_count_internal,
	mark_notification_as_read,
	mark_all_as_read as mark_all_as_read_internal,
	delete_notification
)


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
		limit = int(limit) if limit else 200  # Default 200 for compatibility
		offset = int(offset) if offset else 0
		
		frappe.logger().info(f"📥 [Notification Center] Getting notifications for user: {user}, limit: {limit}")
		
		# Build filters
		filters = {"recipient_user": user}
		
		# Map frontend type to notification_type
		if type and type != 'all':
			mapped_type = map_frontend_type_to_db(type)
			if mapped_type:
				filters["notification_type"] = mapped_type
		
		# Filter by read status
		if status == 'unread':
			filters["read_status"] = "unread"
		elif status == 'read':
			filters["read_status"] = "read"
		elif not include_read:
			filters["read_status"] = "unread"
		
		# Exclude archived
		filters["read_status"] = ["!=", "archived"]
		
		# Query notifications
		raw_notifications = frappe.get_all(
			"ERP Notification",
			filters=filters,
			fields=["*"],
			order_by="event_timestamp desc, creation desc",
			limit_start=offset,
			limit_page_length=limit
		)
		
		# Get total count
		total = frappe.db.count("ERP Notification", filters=filters)
		
		frappe.logger().info(f"📊 [Notification Center] Raw notifications count: {len(raw_notifications)}, total: {total}")
		
		# Transform notifications
		notifications = []
		for notif in raw_notifications:
			try:
				# Parse JSON fields
				title = parse_json_field(notif.title)
				message = parse_json_field(notif.message)
				data = parse_json_field(notif.data)
				
				# Extract student info from data
				notif_student_id = data.get('student_id') or data.get('studentId') or data.get('studentCode')
				student_name = data.get('student_name') or data.get('studentName') or data.get('employeeName')
				
				# Filter by student_id if specified
				if student_id:
					# Only include notifications for this student OR general notifications
					if notif_student_id and notif_student_id != student_id:
						continue
				
				# Map type to frontend format
				frontend_type = map_db_type_to_frontend(notif.notification_type, data)
				
				notification = {
					"id": notif.name,
					"type": frontend_type,
					"title": title,
					"message": message,
					"status": "read" if notif.read_status == "read" else "unread",
					"priority": notif.priority or "normal",
					"created_at": notif.event_timestamp.isoformat() if notif.event_timestamp else notif.creation.isoformat(),
					"read_at": notif.read_at.isoformat() if notif.read_at else None,
					"student_id": notif_student_id,
					"student_name": student_name,
					"action_url": generate_action_url(frontend_type, data, notif_student_id),
					"data": data
				}
				
				notifications.append(notification)
				
			except Exception as e:
				frappe.logger().error(f"Error processing notification {notif.name}: {str(e)}")
				continue
		
		# Get unread count
		unread_filters = {"recipient_user": user, "read_status": "unread"}
		if student_id:
			# Need to filter by student_id in data field - requires custom query
			unread_count = get_unread_count_for_student(user, student_id)
		else:
			unread_count = frappe.db.count("ERP Notification", filters=unread_filters)
		
		frappe.logger().info(f"✅ [Notification Center] Filtered notifications count: {len(notifications)}, unread: {unread_count}")
		
		return {
			"success": True,
			"data": {
				"notifications": notifications,
				"unread_count": unread_count,
				"total": total
			}
		}
		
	except Exception as e:
		frappe.log_error(f"Error getting notifications: {str(e)}", "Notification Center Error")
		frappe.logger().error(f"❌ [Notification Center] Error: {str(e)}")
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
		
		if student_id:
			unread_count = get_unread_count_for_student(user, student_id)
		else:
			unread_count = frappe.db.count(
				"ERP Notification",
				filters={
					"recipient_user": user,
					"read_status": "unread"
				}
			)
		
		frappe.logger().info(f"✅ [Notification Center] Unread count for student {student_id}: {unread_count}")
		
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
				json_data = json.loads(
					frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data
				)
				notification_id = json_data.get('notification_id')
				frappe.logger().info(f"📥 [Notification Center] Parsed notification_id from JSON body: {notification_id}")
			except Exception as e:
				frappe.logger().error(f"Failed to parse JSON body: {str(e)}")
		
		if not notification_id:
			return {
				"success": False,
				"message": "notification_id is required"
			}
		
		# Mark as read
		mark_notification_as_read(notification_id, user)
		
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
		
		# Mark all as read for this user
		count = mark_all_as_read_internal(user)
		
		return {
			"success": True,
			"message": f"Marked {count} notifications as read"
		}
		
	except Exception as e:
		frappe.log_error(f"Error marking all as read: {str(e)}", "Notification Center Error")
		return {
			"success": False,
			"message": str(e)
		}


@frappe.whitelist(allow_guest=False, methods=["POST"])
def delete_notification_api(notification_id=None):
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
				json_data = json.loads(
					frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data
				)
				notification_id = json_data.get('notification_id')
				frappe.logger().info(f"📥 [Notification Center] Parsed notification_id from JSON body: {notification_id}")
			except Exception as e:
				frappe.logger().error(f"Failed to parse JSON body: {str(e)}")
		
		if not notification_id:
			return {
				"success": False,
				"message": "notification_id is required"
			}
		
		# Delete (soft delete by archiving)
		delete_notification(notification_id, user)
		
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

def parse_json_field(field_value):
	"""Parse JSON field - return dict or string"""
	if not field_value:
		return {}
	
	if isinstance(field_value, dict):
		return field_value
	
	if isinstance(field_value, str):
		try:
			return json.loads(field_value)
		except:
			return field_value
	
	return field_value


def map_frontend_type_to_db(frontend_type):
	"""Map frontend type to database notification_type"""
	type_mapping = {
		'attendance': 'attendance',
		'contact_log': 'contact_log',
		'report_card': 'report_card',
		'announcement': 'announcement',
		'news': 'news',
		'leave': 'system',  # Leave uses system type
		'system': 'system'
	}
	return type_mapping.get(frontend_type, frontend_type)


def map_db_type_to_frontend(db_type, data):
	"""Map database notification_type to frontend type"""
	# Check data.type or data.notificationType first
	custom_type = data.get('type') or data.get('notificationType')
	
	# Handle ticket type explicitly
	if custom_type == 'ticket':
		return 'ticket'
	
	if custom_type in ['contact_log', 'report_card', 'student_attendance', 'attendance', 'announcement', 'news', 'leave']:
		if custom_type == 'student_attendance':
			return 'attendance'
		return custom_type
	
	# Check if it's a ticket-related action
	if db_type and db_type.startswith('ticket_') or db_type in ['new_ticket_admin', 'user_reply', 'completion_confirmed']:
		return 'ticket'
	
	# Fallback to db_type
	type_mapping = {
		'attendance': 'attendance',
		'contact_log': 'contact_log',
		'report_card': 'report_card',
		'announcement': 'announcement',
		'news': 'news',
		'ticket': 'ticket',
		'chat': 'system',
		'post': 'news',
		'system': 'system'
	}
	
	return type_mapping.get(db_type, 'system')


def generate_action_url(notif_type, data, student_id=None):
	"""
	Generate action URL để navigate khi click vào notification
	Bao gồm student parameter để tự động chọn học sinh
	"""
	# Extract student_id if not provided
	if not student_id:
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
		return "/announcement"
	
	elif notif_type == 'news':
		base_url = "/news"
		news_id = data.get('news_id') or data.get('newsId') or data.get('postId') or data.get('article_id')
		if news_id:
			return f"{base_url}/{news_id}"
		return base_url
	
	elif notif_type == 'leave':
		return "/leave"
	
	# Default
	return "/dashboard"


def get_unread_count_for_student(user, student_id):
	"""Get unread count filtered by student_id in data field"""
	# Query all unread notifications for this user
	notifications = frappe.get_all(
		"ERP Notification",
		filters={
			"recipient_user": user,
			"read_status": "unread"
		},
		fields=["name", "data"]
	)
	
	# Filter by student_id in data
	count = 0
	for notif in notifications:
		data = parse_json_field(notif.data)
		notif_student_id = data.get('student_id') or data.get('studentId') or data.get('studentCode')
		
		# Count if matches student or is general notification
		if not notif_student_id or notif_student_id == student_id:
			count += 1
	
	return count
