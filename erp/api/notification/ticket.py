"""
Ticket Notification Handler
Xử lý notifications cho ticket events từ ticket-service
"""

import frappe
from frappe import _
import json
from datetime import datetime
import redis
from erp.common.doctype.erp_notification.erp_notification import create_notification
from erp.api.parent_portal.realtime_notification import emit_notification_to_user, emit_unread_count_update
from erp.api.erp_sis.mobile_push_notification import send_mobile_notification


@frappe.whitelist(allow_guest=True, methods=['POST'])
def handle_ticket_event():
	"""
	Handle ticket events từ ticket-service
	Endpoint: /api/method/erp.api.notification.ticket.handle_ticket_event
	"""
	try:
		# Verify service authentication
		service_token = frappe.get_request_header('X-Service-Token') or frappe.get_request_header('Authorization', '').replace('Bearer ', '')

		expected_token = frappe.conf.get('TICKET_SERVICE_TOKEN') or frappe.conf.get('JWT_SECRET')
		if not service_token or service_token != expected_token:
			frappe.throw(_("Unauthorized service"), frappe.PermissionError)

		# Get request data
		if frappe.request.method != 'POST':
			frappe.throw(_("Method not allowed"), frappe.PermissionError)

		data = frappe.form_dict
		if not data:
			data = json.loads(frappe.local.request.get_data() or '{}')

		event_type = data.get('event_type')
		event_data = data.get('event_data', {})

		frappe.logger().info(f"🎫 [Ticket Event] Received API event: {event_type}")

		if not event_type:
			frappe.throw(_("Missing event_type"), frappe.ValidationError)

		# Route to appropriate handler
		if event_type == 'ticket_status_changed':
			handle_ticket_status_change(event_data)
		elif event_type == 'new_ticket_created':
			handle_new_ticket_created(event_data)
		elif event_type == 'user_reply':
			handle_user_reply(event_data)
		elif event_type == 'ticket_cancelled':
			handle_ticket_cancelled(event_data)
		elif event_type == 'completion_confirmed':
			handle_completion_confirmed(event_data)
		elif event_type == 'ticket_feedback_received':
			handle_ticket_feedback_received(event_data)
		else:
			frappe.logger().warning(f"⚠️ [Ticket Event] Unknown event type: {event_type}")
			return {"success": False, "message": f"Unknown event type: {event_type}"}

		return {"success": True, "message": f"Processed {event_type} event via API"}

	except Exception as e:
		frappe.logger().error(f"❌ [Ticket Event] Error processing API event: {str(e)}")
		frappe.log_error(message=str(e), title="Ticket Event Processing Error")
		return {"success": False, "message": str(e)}


def handle_ticket_status_change(event_data):
	"""
	Handle ticket status change event
	"""
	try:
		ticket_id = event_data.get('ticketId')
		ticket_code = event_data.get('ticketCode', 'Unknown')
		old_status = event_data.get('oldStatus')
		new_status = event_data.get('newStatus')
		changed_by = event_data.get('changedBy')
		recipients = event_data.get('recipients', [])
		priority = event_data.get('priority', 'normal')
		category = event_data.get('category', 'Unknown')
		creator = event_data.get('creator')
		assigned_to = event_data.get('assignedTo')

		notification = event_data.get('notification', {})
		title = notification.get('title', f'Ticket {new_status}')
		body = notification.get('body', f'Ticket {ticket_code} status changed to {new_status}')
		action = notification.get('action', 'ticket_status_changed')
		notification_data = notification.get('data', {})

		frappe.logger().info(f"📝 [Ticket Status] Processing {ticket_code}: {old_status} → {new_status}")

		# Skip if no recipients
		if not recipients or len(recipients) == 0:
			frappe.logger().info(f"⚠️ [Ticket Status] No recipients for {ticket_code}")
			return

		# Recipients are already email addresses from ticket-service
		recipient_emails = recipients

		if not recipient_emails:
			frappe.logger().warning(f"⚠️ [Ticket Status] No recipients provided")
			return

		frappe.logger().info(f"👥 [Ticket Status] Sending to {len(recipient_emails)} users: {recipient_emails}")

		# Create notification data
		ticket_notification_data = {
			"type": action,
			"ticketId": ticket_id,
			"ticketCode": ticket_code,
			"oldStatus": old_status,
			"newStatus": new_status,
			"changedBy": changed_by,
			"priority": priority,
			"category": category,
			"creator": creator,
			"assignedTo": assigned_to,
			"timestamp": event_data.get('timestamp', datetime.now().isoformat())
		}

		# Send notifications to each recipient
		for email in recipient_emails:
			try:
				send_ticket_notification_to_user(
					email,
					title,
					body,
					ticket_notification_data,
					action
				)
			except Exception as e:
				frappe.logger().error(f"❌ [Ticket Status] Failed to send to {email}: {str(e)}")

		frappe.logger().info(f"✅ [Ticket Status] Processed status change for {ticket_code}")

	except Exception as e:
		frappe.logger().error(f"❌ [Ticket Status] Error in handle_ticket_status_change: {str(e)}")
		frappe.log_error(message=str(e), title="Ticket Status Change Error")


def handle_new_ticket_created(event_data):
	"""
	Handle new ticket created event
	"""
	try:
		ticket_id = event_data.get('ticketId')
		ticket_code = event_data.get('ticketCode', 'Unknown')
		title = event_data.get('title', 'New Ticket')
		category = event_data.get('category', 'Unknown')
		priority = event_data.get('priority', 'Medium')
		creator = event_data.get('creator')
		assigned_to = event_data.get('assignedTo')
		recipients = event_data.get('recipients', [])

		notification = event_data.get('notification', {})
		notification_title = notification.get('title', '🎫 Ticket mới')
		body = notification.get('body', f'Ticket mới #{ticket_code}: {title}')
		action = notification.get('action', 'new_ticket_admin')

		frappe.logger().info(f"🆕 [New Ticket] Processing {ticket_code} for {len(recipients)} recipients")

		# Recipients are already email addresses from ticket-service
		recipient_emails = recipients

		if not recipient_emails:
			frappe.logger().warning(f"⚠️ [New Ticket] No recipients provided")
			return

		# Create notification data
		ticket_notification_data = {
			"type": action,
			"ticketId": ticket_id,
			"ticketCode": ticket_code,
			"title": title,
			"category": category,
			"priority": priority,
			"creator": creator,
			"assignedTo": assigned_to,
			"timestamp": event_data.get('timestamp', datetime.now().isoformat())
		}

		# Send to all recipients
		for email in recipient_emails:
			try:
				send_ticket_notification_to_user(
					email,
					notification_title,
					body,
					ticket_notification_data,
					action
				)
			except Exception as e:
				frappe.logger().error(f"❌ [New Ticket] Failed to send to {email}: {str(e)}")

		frappe.logger().info(f"✅ [New Ticket] Processed new ticket {ticket_code}")

	except Exception as e:
		frappe.logger().error(f"❌ [New Ticket] Error in handle_new_ticket_created: {str(e)}")
		frappe.log_error(message=str(e), title="New Ticket Created Error")


def handle_user_reply(event_data):
	"""
	Handle user reply to ticket
	"""
	try:
		ticket_id = event_data.get('ticketId')
		ticket_code = event_data.get('ticketCode', 'Unknown')
		title = event_data.get('title', 'Ticket Reply')
		assigned_to = event_data.get('assignedTo')
		message_sender = event_data.get('messageSender')
		recipients = event_data.get('recipients', [])

		notification = event_data.get('notification', {})
		notification_title = notification.get('title', '💬 Người dùng đã phản hồi')
		body = notification.get('body', f'Ticket #{ticket_code} có phản hồi mới')
		action = notification.get('action', 'user_reply')

		frappe.logger().info(f"💬 [User Reply] Processing {ticket_code}")

		# Recipients are already email addresses from ticket-service
		recipient_emails = recipients

		if not recipient_emails:
			frappe.logger().warning(f"⚠️ [User Reply] No recipients provided")
			return

		# Create notification data
		ticket_notification_data = {
			"type": action,
			"ticketId": ticket_id,
			"ticketCode": ticket_code,
			"title": title,
			"assignedTo": assigned_to,
			"messageSender": message_sender,
			"timestamp": event_data.get('timestamp', datetime.now().isoformat())
		}

		# Send to all recipients
		for email in recipient_emails:
			try:
				send_ticket_notification_to_user(
					email,
					notification_title,
					body,
					ticket_notification_data,
					action
				)
			except Exception as e:
				frappe.logger().error(f"❌ [User Reply] Failed to send to {email}: {str(e)}")

		frappe.logger().info(f"✅ [User Reply] Processed user reply for {ticket_code}")

	except Exception as e:
		frappe.logger().error(f"❌ [User Reply] Error in handle_user_reply: {str(e)}")
		frappe.log_error(message=str(e), title="User Reply Error")


def handle_ticket_cancelled(event_data):
	"""
	Handle ticket cancelled event
	"""
	try:
		ticket_id = event_data.get('ticketId')
		ticket_code = event_data.get('ticketCode', 'Unknown')
		title = event_data.get('title', 'Ticket Cancelled')
		cancelled_by = event_data.get('cancelledBy')
		cancellation_reason = event_data.get('cancellationReason')
		recipients = event_data.get('recipients', [])

		notification = event_data.get('notification', {})
		notification_title = notification.get('title', '❌ Ticket đã bị hủy')
		body = notification.get('body', f'Ticket #{ticket_code} đã bị hủy')
		action = notification.get('action', 'ticket_cancelled_admin')

		frappe.logger().info(f"❌ [Ticket Cancelled] Processing {ticket_code}")

		# Recipients are already email addresses from ticket-service
		recipient_emails = recipients

		if not recipient_emails:
			frappe.logger().warning(f"⚠️ [Ticket Cancelled] No recipients provided")
			return

		# Create notification data
		ticket_notification_data = {
			"type": action,
			"ticketId": ticket_id,
			"ticketCode": ticket_code,
			"title": title,
			"cancelledBy": cancelled_by,
			"cancellationReason": cancellation_reason,
			"timestamp": event_data.get('timestamp', datetime.now().isoformat())
		}

		# Send to all recipients
		for email in recipient_emails:
			try:
				send_ticket_notification_to_user(
					email,
					notification_title,
					body,
					ticket_notification_data,
					action
				)
			except Exception as e:
				frappe.logger().error(f"❌ [Ticket Cancelled] Failed to send to {email}: {str(e)}")

		frappe.logger().info(f"✅ [Ticket Cancelled] Processed ticket cancellation for {ticket_code}")

	except Exception as e:
		frappe.logger().error(f"❌ [Ticket Cancelled] Error in handle_ticket_cancelled: {str(e)}")
		frappe.log_error(message=str(e), title="Ticket Cancelled Error")


def handle_completion_confirmed(event_data):
	"""
	Handle ticket completion confirmed event
	"""
	try:
		ticket_id = event_data.get('ticketId')
		ticket_code = event_data.get('ticketCode', 'Unknown')
		title = event_data.get('title', 'Completion Confirmed')
		assigned_to = event_data.get('assignedTo')
		confirmed_by = event_data.get('confirmedBy')
		recipients = event_data.get('recipients', [])

		notification = event_data.get('notification', {})
		notification_title = notification.get('title', '✅ Ticket đã được xác nhận hoàn thành')
		body = notification.get('body', f'Ticket #{ticket_code} đã được xác nhận hoàn thành')
		action = notification.get('action', 'completion_confirmed')

		frappe.logger().info(f"✅ [Completion Confirmed] Processing {ticket_code}")

		# Recipients are already email addresses from ticket-service
		recipient_emails = recipients

		if not recipient_emails:
			frappe.logger().warning(f"⚠️ [Completion Confirmed] No recipients provided")
			return

		# Create notification data
		ticket_notification_data = {
			"type": action,
			"ticketId": ticket_id,
			"ticketCode": ticket_code,
			"title": title,
			"assignedTo": assigned_to,
			"confirmedBy": confirmed_by,
			"timestamp": event_data.get('timestamp', datetime.now().isoformat())
		}

		# Send to all recipients
		for email in recipient_emails:
			try:
				send_ticket_notification_to_user(
					email,
					notification_title,
					body,
					ticket_notification_data,
					action
				)
			except Exception as e:
				frappe.logger().error(f"❌ [Completion Confirmed] Failed to send to {email}: {str(e)}")

		frappe.logger().info(f"✅ [Completion Confirmed] Processed completion confirmation for {ticket_code}")

	except Exception as e:
		frappe.logger().error(f"❌ [Completion Confirmed] Error in handle_completion_confirmed: {str(e)}")
		frappe.log_error(message=str(e), title="Completion Confirmed Error")


def handle_ticket_feedback_received(event_data):
	"""
	Handle ticket feedback received event
	"""
	try:
		ticket_id = event_data.get('ticketId')
		ticket_code = event_data.get('ticketCode', 'Unknown')
		title = event_data.get('title', 'Feedback Received')
		assigned_to = event_data.get('assignedTo')
		rating = event_data.get('rating')
		feedback_comment = event_data.get('feedbackComment')
		recipients = event_data.get('recipients', [])

		notification = event_data.get('notification', {})
		notification_title = notification.get('title', '⭐ Ticket nhận được đánh giá')
		body = notification.get('body', f'Ticket #{ticket_code} nhận được {rating} sao')
		action = notification.get('action', 'ticket_feedback_received')

		frappe.logger().info(f"⭐ [Feedback Received] Processing {ticket_code} - {rating} stars")

		# Recipients are already email addresses from ticket-service
		recipient_emails = recipients

		if not recipient_emails:
			frappe.logger().warning(f"⚠️ [Feedback Received] No recipients provided")
			return

		# Create notification data
		ticket_notification_data = {
			"type": action,
			"ticketId": ticket_id,
			"ticketCode": ticket_code,
			"title": title,
			"assignedTo": assigned_to,
			"rating": rating,
			"feedbackComment": feedback_comment,
			"timestamp": event_data.get('timestamp', datetime.now().isoformat())
		}

		# Send to all recipients
		for email in recipient_emails:
			try:
				send_ticket_notification_to_user(
					email,
					notification_title,
					body,
					ticket_notification_data,
					action
				)
			except Exception as e:
				frappe.logger().error(f"❌ [Feedback Received] Failed to send to {email}: {str(e)}")

		frappe.logger().info(f"✅ [Feedback Received] Processed feedback for {ticket_code}")

	except Exception as e:
		frappe.logger().error(f"❌ [Feedback Received] Error in handle_ticket_feedback_received: {str(e)}")
		frappe.log_error(message=str(e), title="Feedback Received Error")


def send_ticket_notification_to_user(user_email, title, body, data, notification_type):
	"""
	Send ticket notification to a specific user
	"""
	try:
		frappe.logger().info(f"📤 [Ticket Notification] Sending to {user_email}: {title}")

		# Create notification data
		notification_data = {
			"type": data.get('type', notification_type),
			"ticketId": data.get('ticketId'),
			"ticketCode": data.get('ticketCode'),
			"priority": data.get('priority', 'normal'),
			"timestamp": data.get('timestamp', datetime.now().isoformat()),
			# Include additional data based on notification type
			**{k: v for k, v in data.items() if k not in ['type', 'ticketId', 'ticketCode', 'priority', 'timestamp']}
		}

		# Create ERP Notification record (similar to attendance)
		try:
			from frappe import get_doc
			notification_doc = get_doc({
				"doctype": "ERP Notification",
				"title": title,
				"message": body,
				"recipient_user": user_email,
				"recipients": json.dumps([user_email]),
				"notification_type": notification_type,
				"priority": data.get('priority', 'normal'),
				"data": json.dumps(notification_data),
				"channel": "push",
				"status": "sent",
				"delivery_status": "pending",
				"sent_at": frappe.utils.now(),
				"event_timestamp": data.get('timestamp', frappe.utils.now())
			})
			notification_doc.insert(ignore_permissions=True)
			frappe.db.commit()
			frappe.logger().info(f"✅ Created notification record: {notification_doc.name}")
		except Exception as create_error:
			frappe.logger().error(f"❌ Failed to create notification record: {str(create_error)}")
			return

		# Send mobile push notification
		try:
			mobile_result = send_mobile_notification(
				user_email=user_email,
				title=title,
				body=body,
				data=notification_data
			)
			frappe.logger().info(f"📱 Mobile notification sent to {user_email}: {mobile_result}")
		except Exception as mobile_error:
			frappe.logger().error(f"❌ Failed to send mobile notification to {user_email}: {str(mobile_error)}")

		# Send realtime notification for PWA/web users
		try:
			emit_notification_to_user(user_email, {
				"id": notification_doc.name,
				"type": notification_type,
				"title": title,
				"message": body,
				"status": "unread",
				"priority": data.get('priority', 'normal'),
				"created_at": data.get('timestamp', datetime.now().isoformat()),
				"data": notification_data
			})

			# Update unread count
			emit_unread_count_update(user_email)

		except Exception as realtime_error:
			frappe.logger().error(f"❌ Failed to send realtime notification to {user_email}: {str(realtime_error)}")

		frappe.logger().info(f"✅ [Ticket Notification] Sent to {user_email}")

	except Exception as e:
		frappe.logger().error(f"❌ [Ticket Notification] Error sending to {user_email}: {str(e)}")
		frappe.log_error(message=str(e), title="Ticket Notification Error")


