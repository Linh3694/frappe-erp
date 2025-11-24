# Copyright (c) 2024, Your Organization and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe import _
import json


class ERPNotification(Document):
	"""
	Notification Document
	Supports bilingual notifications and various notification types
	"""
	
	def before_insert(self):
		"""Set default values before insert"""
		if not self.sender:
			self.sender = frappe.session.user
		
		if not self.sent_at and self.status == "sent":
			self.sent_at = frappe.utils.now()
		
		if not self.delivery_status:
			self.delivery_status = "pending"
	
	def mark_as_read(self, user=None):
		"""Mark notification as read for a specific user"""
		if not user:
			user = frappe.session.user
		
		if self.recipient_user == user:
			self.read_status = "read"
			self.read_at = frappe.utils.now()
			self.save(ignore_permissions=True)
			frappe.db.commit()
			return True
		
		return False
	
	def mark_as_delivered(self):
		"""Mark notification as delivered"""
		self.delivery_status = "delivered"
		self.delivered_at = frappe.utils.now()
		self.save(ignore_permissions=True)
		frappe.db.commit()
	
	def mark_as_failed(self, error_message=None):
		"""Mark notification as failed"""
		self.delivery_status = "failed"
		if error_message and self.data:
			try:
				data = json.loads(self.data) if isinstance(self.data, str) else self.data or {}
				data['delivery_error'] = error_message
				self.data = json.dumps(data)
			except:
				pass
		self.save(ignore_permissions=True)
		frappe.db.commit()
	
	def get_title_text(self, language='vi'):
		"""Get title text in specific language"""
		if isinstance(self.title, str):
			try:
				title_obj = json.loads(self.title)
				if isinstance(title_obj, dict):
					return title_obj.get(language) or title_obj.get('vi') or title_obj.get('en') or self.title
			except:
				pass
		return self.title
	
	def get_message_text(self, language='vi'):
		"""Get message text in specific language"""
		if isinstance(self.message, str):
			try:
				message_obj = json.loads(self.message)
				if isinstance(message_obj, dict):
					return message_obj.get(language) or message_obj.get('vi') or message_obj.get('en') or self.message
			except:
				pass
		return self.message


@frappe.whitelist()
def create_notification(
	title,
	message,
	recipient_user=None,
	recipients=None,
	notification_type="system",
	priority="medium",
	data=None,
	channel="system",
	event_timestamp=None,
	reference_doctype=None,
	reference_name=None
):
	"""
	Create a new notification
	
	Args:
		title: String or dict {vi, en} for bilingual support
		message: String or dict {vi, en} for bilingual support
		recipient_user: Primary recipient user email
		recipients: List of recipient emails (JSON)
		notification_type: Type of notification
		priority: Priority level
		data: Additional data (JSON)
		channel: Notification channel
		event_timestamp: Actual event timestamp
		reference_doctype: Reference document type
		reference_name: Reference document name
	"""
	notification = frappe.get_doc({
		"doctype": "ERP Notification",
		"title": json.dumps(title) if isinstance(title, dict) else title,
		"message": json.dumps(message) if isinstance(message, dict) else message,
		"recipient_user": recipient_user,
		"recipients": json.dumps(recipients) if isinstance(recipients, list) else recipients,
		"notification_type": notification_type,
		"priority": priority,
		"data": json.dumps(data) if isinstance(data, dict) else data,
		"channel": channel,
		"status": "sent",
		"delivery_status": "pending",
		"sent_at": frappe.utils.now(),
		"event_timestamp": event_timestamp,
		"reference_doctype": reference_doctype,
		"reference_name": reference_name
	})
	notification.insert(ignore_permissions=True)
	frappe.db.commit()
	return notification


@frappe.whitelist()
def create_bulk_notifications(notifications_data):
	"""
	Create multiple notifications at once
	
	Args:
		notifications_data: List of notification dicts
	"""
	created_notifications = []
	
	for notif_data in notifications_data:
		try:
			notification = create_notification(**notif_data)
			created_notifications.append(notification.name)
		except Exception as e:
			frappe.logger().error(f"Failed to create notification: {str(e)}")
	
	return created_notifications


@frappe.whitelist()
def get_user_notifications(user=None, notification_type=None, read_status=None, limit=50, offset=0):
	"""
	Get notifications for a user with filtering
	
	Args:
		user: User email (default: current user)
		notification_type: Filter by type
		read_status: Filter by read status
		limit: Number of records to return
		offset: Offset for pagination
	"""
	if not user:
		user = frappe.session.user
	
	filters = {"recipient_user": user}
	
	if notification_type:
		filters["notification_type"] = notification_type
	
	if read_status:
		filters["read_status"] = read_status
	
	notifications = frappe.get_all(
		"ERP Notification",
		filters=filters,
		fields=["*"],
		order_by="event_timestamp desc, creation desc",
		limit=limit,
		start=offset
	)
	
	return notifications


@frappe.whitelist()
def get_unread_count(user=None):
	"""Get count of unread notifications for a user"""
	if not user:
		user = frappe.session.user
	
	count = frappe.db.count(
		"ERP Notification",
		filters={
			"recipient_user": user,
			"read_status": "unread"
		}
	)
	
	return count


@frappe.whitelist()
def mark_notification_as_read(notification_id, user=None):
	"""Mark a specific notification as read"""
	if not user:
		user = frappe.session.user
	
	notification = frappe.get_doc("ERP Notification", notification_id)
	
	if notification.recipient_user != user:
		frappe.throw(_("Not authorized to mark this notification as read"))
	
	notification.mark_as_read(user)
	return True


@frappe.whitelist()
def mark_all_as_read(user=None, notification_type=None):
	"""Mark all notifications as read for a user"""
	if not user:
		user = frappe.session.user
	
	filters = {
		"recipient_user": user,
		"read_status": "unread"
	}
	
	if notification_type:
		filters["notification_type"] = notification_type
	
	notifications = frappe.get_all(
		"ERP Notification",
		filters=filters,
		pluck="name"
	)
	
	for notification_id in notifications:
		try:
			notification = frappe.get_doc("ERP Notification", notification_id)
			notification.mark_as_read(user)
		except Exception as e:
			frappe.logger().error(f"Failed to mark notification as read: {str(e)}")
	
	frappe.db.commit()
	return len(notifications)


@frappe.whitelist()
def delete_notification(notification_id, user=None):
	"""Delete a notification (soft delete by archiving)"""
	if not user:
		user = frappe.session.user
	
	notification = frappe.get_doc("ERP Notification", notification_id)
	
	if notification.recipient_user != user:
		frappe.throw(_("Not authorized to delete this notification"))
	
	notification.read_status = "archived"
	notification.save(ignore_permissions=True)
	frappe.db.commit()
	
	return True
