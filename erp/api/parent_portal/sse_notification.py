"""
Server-Sent Events (SSE) for Real-time Notifications
Đơn giản hơn SocketIO, chỉ cần 1 chiều (server → client)
"""

import frappe
import json
import time
from frappe import _


@frappe.whitelist(allow_guest=True)
def notification_stream():
	"""
	SSE endpoint để stream real-time notifications
	
	Client connect đến endpoint này và giữ connection mở
	Server sẽ push notifications qua SSE format
	
	Usage:
		GET /api/method/erp.api.parent_portal.sse_notification.notification_stream?token=<jwt_token>
	"""
	frappe.response['type'] = 'sse'
	
	# Set SSE headers
	frappe.local.response.headers = {
		'Content-Type': 'text/event-stream',
		'Cache-Control': 'no-cache',
		'Connection': 'keep-alive',
		'X-Accel-Buffering': 'no',  # Disable nginx buffering
	}
	
	# Authenticate từ token trong query parameter
	# EventSource không support custom headers, nên phải dùng query param
	token = frappe.form_dict.get('token')
	
	if not token:
		yield f"event: error\ndata: {json.dumps({'error': 'No token provided'})}\n\n"
		return
	
	# Validate JWT token
	try:
		from erp.api.erp_common_user.auth import verify_jwt_token
		payload = verify_jwt_token(token)
		
		if not payload:
			yield f"event: error\ndata: {json.dumps({'error': 'Invalid or expired token'})}\n\n"
			return
		
		user_email = payload.get('user')
		if not user_email:
			yield f"event: error\ndata: {json.dumps({'error': 'Invalid token payload'})}\n\n"
			return
			
	except Exception as e:
		frappe.logger().error(f"❌ [SSE] Token validation error: {str(e)}")
		yield f"event: error\ndata: {json.dumps({'error': 'Authentication failed'})}\n\n"
		return
	
	frappe.logger().info(f"📡 [SSE] User {user_email} connected to notification stream")
	
	# Send initial connection success event
	yield f"event: connected\ndata: {json.dumps({'status': 'connected', 'user': user_email})}\n\n"
	
	# Track last check time
	last_check = frappe.utils.now()
	
	# Keep connection alive and check for new notifications
	while True:
		try:
			# Check for new notifications since last check
			new_notifications = get_new_notifications_since(user_email, last_check)
			
			if new_notifications:
				for notification in new_notifications:
					# Format notification data
					notification_data = format_notification_for_sse(notification)
					
					# Send notification event
					yield f"event: new_notification\ndata: {json.dumps(notification_data)}\n\n"
					
					frappe.logger().info(f"📤 [SSE] Sent notification {notification.name} to {user_email}")
			
			# Update last check time
			last_check = frappe.utils.now()
			
			# Send heartbeat to keep connection alive
			yield f"event: heartbeat\ndata: {json.dumps({'timestamp': last_check})}\n\n"
			
			# Wait before next check (polling interval: 3 seconds)
			time.sleep(3)
			
		except GeneratorExit:
			# Client disconnected
			frappe.logger().info(f"📡 [SSE] User {user_email} disconnected from notification stream")
			break
		except Exception as e:
			frappe.logger().error(f"❌ [SSE] Error in notification stream for {user_email}: {str(e)}")
			yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
			break


def get_new_notifications_since(user, since_time):
	"""
	Lấy notifications mới từ thời điểm since_time
	
	Args:
		user: User email
		since_time: Datetime string
	
	Returns:
		List of ERP Notification documents
	"""
	try:
		notifications = frappe.get_all(
			'ERP Notification',
			filters={
				'recipient_user': user,
				'creation': ['>', since_time],
				'read_status': 'unread'
			},
			fields=['name', 'title', 'message', 'notification_type', 'priority', 
					'event_timestamp', 'creation', 'data', 'read_status'],
			order_by='creation desc',
			limit=10
		)
		
		# Get full documents
		return [frappe.get_doc('ERP Notification', n.name) for n in notifications]
		
	except Exception as e:
		frappe.logger().error(f"Error getting new notifications: {str(e)}")
		return []


def format_notification_for_sse(notification_doc):
	"""Format ERP Notification document for SSE"""
	# Parse JSON fields
	title = json.loads(notification_doc.title) if isinstance(notification_doc.title, str) and notification_doc.title.startswith('{') else notification_doc.title
	message = json.loads(notification_doc.message) if isinstance(notification_doc.message, str) and notification_doc.message.startswith('{') else notification_doc.message
	data = json.loads(notification_doc.data) if isinstance(notification_doc.data, str) else (notification_doc.data or {})
	
	# Extract student info
	student_id = data.get('student_id') or data.get('studentId') or data.get('studentCode')
	student_name = data.get('student_name') or data.get('studentName')
	
	# Helper to convert datetime to ISO string
	def to_iso_string(dt_value):
		if not dt_value:
			return None
		if isinstance(dt_value, str):
			return dt_value
		if hasattr(dt_value, 'isoformat'):
			return dt_value.isoformat()
		return str(dt_value)
	
	return {
		"id": notification_doc.name,
		"type": notification_doc.notification_type,
		"title": title,
		"message": message,
		"status": "read" if notification_doc.read_status == "read" else "unread",
		"priority": notification_doc.priority or "normal",
		"created_at": to_iso_string(notification_doc.event_timestamp) if notification_doc.event_timestamp else to_iso_string(notification_doc.creation),
		"read_at": to_iso_string(notification_doc.read_at),
		"student_id": student_id,
		"student_name": student_name,
		"data": data
	}


@frappe.whitelist()
def push_notification_via_sse(user_email, notification_data):
	"""
	Helper function để push notification qua SSE
	Được gọi từ các service khác (attendance, contact_log, etc.)

	Args:
		user_email: User email to send notification
		notification_data: Notification data dict

	Note:
		SSE hoạt động theo cơ chế polling, nên function này chỉ log
		Client sẽ tự động nhận notification khi polling
	"""
	frappe.logger().info(f"📡 [SSE] Notification ready for {user_email}: {notification_data.get('id')}")
	return True


def trigger_sse_notification_for_user(user_email, notification_doc=None, notification_data=None):
	"""
	Trigger SSE notification cho user cụ thể
	Called when ERP Notification is created

	Args:
		user_email: User email
		notification_doc: ERP Notification document (optional)
		notification_data: Pre-formatted notification data (optional)
	"""
	try:
		if not user_email:
			return

		# Format notification data if not provided
		if not notification_data and notification_doc:
			notification_data = format_notification_for_sse(notification_doc)

		if not notification_data:
			frappe.logger().warning(f"⚠️ [SSE] No notification data to trigger for {user_email}")
			return

		# Publish realtime event để trigger SSE clients (nếu có listener)
		# Và cũng để log rằng có notification mới
		frappe.publish_realtime(
			event="sse_notification_available",
			message={
				"user_email": user_email,
				"notification_id": notification_data.get('id'),
				"timestamp": frappe.utils.now()
			},
			user=user_email
		)

		frappe.logger().info(f"📡 [SSE] Triggered SSE notification for {user_email}: {notification_data.get('id')}")

	except Exception as e:
		frappe.logger().error(f"❌ [SSE] Failed to trigger SSE notification: {str(e)}")


@frappe.whitelist()
def on_notification_created_for_sse(notification_doc, method=None):
	"""
	Hook function called when ERP Notification is created
	Triggers SSE notification for the recipient
	"""
	try:
		user_email = notification_doc.recipient_user
		if user_email:
			trigger_sse_notification_for_user(user_email, notification_doc=notification_doc)
	except Exception as e:
		frappe.logger().error(f"❌ [SSE] Error in on_notification_created_for_sse: {str(e)}")


@frappe.whitelist()
def test_send_notification_to_student_parents(student_id="WS12310116"):
	"""
	Test function để gửi notification tới phụ huynh của học sinh
	Có thể chạy từ bench console: frappe.call('erp.api.parent_portal.sse_notification.test_send_notification_to_student_parents')
	"""
	try:
		print(f"🧪 [TEST] Testing notification for student: {student_id}")

		# Import notification handler
		from erp.utils.notification_handler import send_bulk_parent_notifications

		# Gửi notification test
		result = send_bulk_parent_notifications(
			recipient_type="test",
			recipients_data={
				"student_ids": [student_id]
			},
			title="Test Notification",
			body=f"Đây là notification test cho học sinh {student_id}",
			data={
				"type": "test",
				"student_id": student_id,
				"timestamp": frappe.utils.now()
			}
		)

		print(f"✅ [TEST] Notification sent result: {result}")
		return result

	except Exception as e:
		print(f"❌ [TEST] Error: {str(e)}")
		import traceback
		traceback.print_exc()
		return {"success": False, "error": str(e)}

