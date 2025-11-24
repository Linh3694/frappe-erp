"""
Real-time Notification Handler
Uses Frappe SocketIO to push real-time notifications to connected clients
"""

import frappe
import json
from frappe import _


def emit_notification_to_user(user_email, notification_data):
	"""
	Emit real-time notification to a specific user via Frappe SocketIO
	
	Args:
		user_email: User email to send notification to
		notification_data: Notification data dict
	
	Usage:
		from erp.api.parent_portal.realtime_notification import emit_notification_to_user
		
		emit_notification_to_user(
			"parent@wellspring.edu.vn",
			{
				"id": "NOTIF-00001",
				"type": "attendance",
				"title": "Điểm danh",
				"message": "Con đã đến trường",
				...
			}
		)
	"""
	try:
		# Use frappe.publish_realtime to emit event to specific user
		frappe.publish_realtime(
			event="new_notification",
			message=notification_data,
			user=user_email,
			after_commit=True
		)
		
		frappe.logger().info(f"📡 [Realtime] Emitted notification to {user_email}")
		return True
		
	except Exception as e:
		frappe.logger().error(f"❌ [Realtime] Failed to emit notification to {user_email}: {str(e)}")
		return False


def emit_notification_to_users(user_emails, notification_data):
	"""
	Emit real-time notification to multiple users
	
	Args:
		user_emails: List of user emails
		notification_data: Notification data dict
	
	Returns:
		dict: {"success_count": int, "failed_count": int}
	"""
	success_count = 0
	failed_count = 0
	
	for user_email in user_emails:
		if emit_notification_to_user(user_email, notification_data):
			success_count += 1
		else:
			failed_count += 1
	
	frappe.logger().info(f"📡 [Realtime] Emitted to {success_count}/{len(user_emails)} users")
	
	return {
		"success_count": success_count,
		"failed_count": failed_count,
		"total": len(user_emails)
	}


def emit_unread_count_update(user_email, unread_count):
	"""
	Emit unread count update to user
	
	Args:
		user_email: User email
		unread_count: New unread count
	"""
	try:
		frappe.publish_realtime(
			event="notification_unread_count",
			message={"unread_count": unread_count},
			user=user_email,
			after_commit=True
		)
		
		frappe.logger().info(f"📡 [Realtime] Updated unread count for {user_email}: {unread_count}")
		return True
		
	except Exception as e:
		frappe.logger().error(f"❌ [Realtime] Failed to emit unread count to {user_email}: {str(e)}")
		return False


def broadcast_notification(notification_data, room=None):
	"""
	Broadcast notification to all connected clients or specific room
	
	Args:
		notification_data: Notification data dict
		room: Optional room name to broadcast to
	"""
	try:
		frappe.publish_realtime(
			event="new_notification",
			message=notification_data,
			room=room,
			after_commit=True
		)
		
		frappe.logger().info(f"📡 [Realtime] Broadcasted notification to room: {room or 'all'}")
		return True
		
	except Exception as e:
		frappe.logger().error(f"❌ [Realtime] Failed to broadcast notification: {str(e)}")
		return False


@frappe.whitelist()
def test_realtime_notification():
	"""
	Test endpoint to send realtime notification to current user
	"""
	user = frappe.session.user
	
	notification_data = {
		"id": "TEST-" + frappe.generate_hash(length=5),
		"type": "system",
		"title": "🎉 Test Real-time Notification",
		"message": f"This is a test real-time notification for {user}",
		"status": "unread",
		"priority": "normal",
		"created_at": frappe.utils.now(),
		"data": {
			"type": "test",
			"timestamp": frappe.utils.now()
		}
	}
	
	result = emit_notification_to_user(user, notification_data)
	
	return {
		"success": result,
		"message": "Real-time notification sent" if result else "Failed to send notification",
		"user": user,
		"notification": notification_data
	}


def send_notification_complete(notification_doc, recipients):
	"""
	Send complete notification (ERP Notification record + push + realtime)
	This is a helper function to send all types of notifications at once
	
	Args:
		notification_doc: ERP Notification document
		recipients: List of user emails
	
	Returns:
		dict: Status of each channel
	"""
	results = {
		"database": True,  # Already saved
		"realtime": False,
		"push": False
	}
	
	try:
		# Parse notification data for realtime
		notification_data = format_notification_for_realtime(notification_doc)
		
		# 1. Send realtime notification via SocketIO
		realtime_result = emit_notification_to_users(recipients, notification_data)
		results["realtime"] = realtime_result["success_count"] > 0
		
		# 2. Send push notification (enqueue for background processing)
		try:
			from erp.api.parent_portal.push_notification import send_bulk_push_notifications
			
			# Get title and message text
			title = get_notification_text(notification_doc.title)
			message = get_notification_text(notification_doc.message)
			data = json.loads(notification_doc.data) if isinstance(notification_doc.data, str) else notification_doc.data
			
			frappe.enqueue(
				send_bulk_push_notifications,
				queue="default",
				timeout=300,
				user_emails=recipients,
				title=title,
				body=message,
				icon="/icon.png",
				data=data,
				tag=notification_doc.notification_type
			)
			
			results["push"] = True
			
		except Exception as push_error:
			frappe.logger().error(f"Failed to enqueue push notifications: {str(push_error)}")
		
		frappe.logger().info(f"✅ [Send Complete] Notification sent via database + realtime + push")
		
	except Exception as e:
		frappe.logger().error(f"❌ [Send Complete] Error: {str(e)}")
	
	return results


def format_notification_for_realtime(notification_doc):
	"""Format ERP Notification document for realtime emission"""
	# Parse JSON fields
	title = json.loads(notification_doc.title) if isinstance(notification_doc.title, str) and notification_doc.title.startswith('{') else notification_doc.title
	message = json.loads(notification_doc.message) if isinstance(notification_doc.message, str) and notification_doc.message.startswith('{') else notification_doc.message
	data = json.loads(notification_doc.data) if isinstance(notification_doc.data, str) else (notification_doc.data or {})
	
	# Extract student info
	student_id = data.get('student_id') or data.get('studentId') or data.get('studentCode')
	student_name = data.get('student_name') or data.get('studentName')
	
	# Helper to convert datetime/string to ISO format
	def to_iso_string(dt_value):
		if not dt_value:
			return None
		if isinstance(dt_value, str):
			return dt_value  # Already a string
		if hasattr(dt_value, 'isoformat'):
			return dt_value.isoformat()  # datetime object
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


def get_notification_text(text_or_obj, language='vi'):
	"""Get notification text in specific language"""
	if isinstance(text_or_obj, dict):
		return text_or_obj.get(language) or text_or_obj.get('vi') or text_or_obj.get('en') or str(text_or_obj)
	return str(text_or_obj)


# Event handlers for real-time updates

def on_notification_read(notification_doc):
	"""
	Called when a notification is marked as read
	Update realtime clients
	"""
	try:
		user_email = notification_doc.recipient_user
		if user_email:
			# Convert read_at to ISO string safely
			read_at_iso = None
			if notification_doc.read_at:
				if isinstance(notification_doc.read_at, str):
					read_at_iso = notification_doc.read_at
				elif hasattr(notification_doc.read_at, 'isoformat'):
					read_at_iso = notification_doc.read_at.isoformat()
			
			# Emit notification update
			emit_notification_to_user(user_email, {
				"id": notification_doc.name,
				"status": "read",
				"read_at": read_at_iso,
				"action": "marked_read"
			})
			
			# Update unread count
			from erp.common.doctype.erp_notification.erp_notification import get_unread_count
			unread_count = get_unread_count(user_email)
			emit_unread_count_update(user_email, unread_count)
			
	except Exception as e:
		frappe.logger().error(f"Error in on_notification_read: {str(e)}")


def on_notification_created(notification_doc, method=None):
	"""
	Called when a new notification is created (Frappe hook)
	Send realtime and push notifications
	
	Args:
		notification_doc: ERP Notification document
		method: Hook method name (passed by Frappe, not used)
	"""
	try:
		recipient = notification_doc.recipient_user
		if recipient:
			# Format and emit
			notification_data = format_notification_for_realtime(notification_doc)
			emit_notification_to_user(recipient, notification_data)
			
			# Update unread count
			from erp.common.doctype.erp_notification.erp_notification import get_unread_count
			unread_count = get_unread_count(recipient)
			emit_unread_count_update(recipient, unread_count)
			
			# Send push notification directly (not enqueued to ensure immediate delivery)
			try:
				from erp.api.parent_portal.push_notification import send_push_notification
				
				title = get_notification_text(notification_doc.title)
				message = get_notification_text(notification_doc.message)
				data = json.loads(notification_doc.data) if isinstance(notification_doc.data, str) else notification_doc.data
				
				# Call directly instead of enqueue to ensure push is sent immediately
				# This is important when workers are not running
				send_push_notification(
					user_email=recipient,
					title=title,
					body=message,
					icon="/icon.png",
					data=data,
					tag=notification_doc.notification_type
				)
			except Exception as push_error:
				frappe.logger().warning(f"Failed to send push notification: {str(push_error)}")
				
	except Exception as e:
		frappe.logger().error(f"Error in on_notification_created: {str(e)}")

