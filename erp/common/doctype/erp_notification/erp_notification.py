# Copyright (c) 2024, Your Organization and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
import json


class ERPNotification(Document):
	def before_insert(self):
		# Tự động set thông tin audit khi tạo mới
		if hasattr(self, 'create_at'):
			self.create_at = frappe.utils.now()
		if hasattr(self, 'create_date'):
			self.create_date = frappe.utils.now()
		if hasattr(self, 'submitted_at') and not self.submitted_at:
			self.submitted_at = frappe.utils.now()
		
		# Set sender if not provided
		if not self.sender:
			self.sender = frappe.session.user
	
	def before_save(self):
		# Tự động set thông tin audit khi cập nhật
		if hasattr(self, 'update_at'):
			self.update_at = frappe.utils.now()
		if hasattr(self, 'update_by'):
			self.update_by = frappe.session.user
		if hasattr(self, 'last_update'):
			self.last_update = frappe.utils.now()
		if hasattr(self, 'last_updated'):
			self.last_updated = frappe.utils.now()
	
	def after_insert(self):
		"""Send notification after creation"""
		if self.status == "draft":
			self.send_notification()
	
	def send_notification(self):
		"""Send notification to recipients"""
		try:
			recipients = json.loads(self.recipients or "[]")
			
			if self.recipient_type == "all":
				# Send to all users
				all_users = frappe.get_all("User", filters={"enabled": 1}, fields=["name"])
				recipients = [user.name for user in all_users]
			elif self.recipient_type == "role":
				# Send to users with specific roles
				role_users = []
				for role in recipients:
					users = frappe.get_all("Has Role", 
						filters={"role": role, "parenttype": "User"}, 
						fields=["parent"]
					)
					role_users.extend([user.parent for user in users])
				recipients = list(set(role_users))
			
			# Create notification logs for each recipient
			for recipient in recipients:
				self.create_notification_log(recipient)
			
			# Update status
			self.status = "sent"
			self.sent_at = frappe.utils.now()
			self.save(ignore_permissions=True)
			
		except Exception as e:
			frappe.log_error(f"Failed to send notification: {str(e)}")
			self.status = "failed"
			self.save(ignore_permissions=True)
	
	def create_notification_log(self, recipient):
		"""Create notification log for a specific recipient"""
		log = frappe.new_doc("Notification Log")
		log.subject = self.title
		log.email_content = self.message
		log.for_user = recipient
		log.from_user = self.sender
		log.type = self.notification_type.title()
		log.document_type = self.reference_doctype
		log.document_name = self.reference_name
		log.save(ignore_permissions=True)
	
	def mark_as_read(self, user=None):
		"""Mark notification as read"""
		if not user:
			user = frappe.session.user
		
		self.read_status = "read"
		self.read_at = frappe.utils.now()
		self.save(ignore_permissions=True)


@frappe.whitelist()
def create_notification(title, message, recipients, notification_type="system", priority="medium", data=None):
	"""Create and send notification"""
	notification = frappe.new_doc("ERP Notification")
	notification.title = title
	notification.message = message
	notification.recipients = json.dumps(recipients) if isinstance(recipients, list) else recipients
	notification.notification_type = notification_type
	notification.priority = priority
	notification.data = json.dumps(data) if data else None
	notification.save(ignore_permissions=True)
	
	return notification


@frappe.whitelist()
def get_user_notifications(user=None, limit=50):
	"""Get notifications for a user"""
	if not user:
		user = frappe.session.user
	
	notifications = frappe.get_all("Notification Log",
		filters={"for_user": user},
		fields=["name", "subject", "email_content", "type", "read", "creation", "from_user"],
		order_by="creation desc",
		limit=limit
	)
	
	return notifications


@frappe.whitelist()
def mark_notification_as_read(notification_name):
	"""Mark a notification as read"""
	notification = frappe.get_doc("ERP Notification", notification_name)
	notification.mark_as_read()
	return {"status": "success"}