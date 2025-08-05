# Copyright (c) 2024, Your Organization and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
import json


class ERPTicket(Document):
	def before_insert(self):
		# Tự động set thông tin audit khi tạo mới
		self.created_at = frappe.utils.now()
		self.creator = frappe.session.user
		if hasattr(self, 'create_at'):
			self.create_at = frappe.utils.now()
		if hasattr(self, 'create_date'):
			self.create_date = frappe.utils.now()
		if hasattr(self, 'submitted_at') and not self.submitted_at:
			self.submitted_at = frappe.utils.now()
	
	def before_save(self):
		# Tự động set thông tin audit khi cập nhật
		self.updated_at = frappe.utils.now()
		if hasattr(self, 'update_at'):
			self.update_at = frappe.utils.now()
		if hasattr(self, 'update_by'):
			self.update_by = frappe.session.user
		if hasattr(self, 'last_update'):
			self.last_update = frappe.utils.now()
		if hasattr(self, 'last_updated'):
			self.last_updated = frappe.utils.now()
		
		# Update timestamps based on status
		if self.status == "resolved" and not self.resolved_at:
			self.resolved_at = frappe.utils.now()
		elif self.status == "closed" and not self.closed_at:
			self.closed_at = frappe.utils.now()
	
	def after_insert(self):
		"""Create notification after ticket creation"""
		self.create_ticket_notification("created")
	
	def on_update(self):
		"""Handle ticket updates"""
		if self.has_value_changed("status"):
			self.create_ticket_notification("status_changed")
		
		if self.has_value_changed("assigned_to"):
			self.create_ticket_notification("assigned")
	
	def create_ticket_notification(self, event_type):
		"""Create notification for ticket events"""
		try:
			title = ""
			message = ""
			recipients = []
			
			if event_type == "created":
				title = f"Ticket mới: {self.title}"
				message = f"Ticket #{self.name} đã được tạo bởi {self.creator}"
				# Notify IT Support team
				it_users = frappe.get_all("Has Role", 
					filters={"role": "IT Support", "parenttype": "User"}, 
					fields=["parent"]
				)
				recipients = [user.parent for user in it_users]
			
			elif event_type == "status_changed":
				title = f"Ticket {self.name}: Trạng thái thay đổi"
				message = f"Trạng thái ticket đã thay đổi thành: {self.status}"
				recipients = [self.creator]
				if self.assigned_to:
					recipients.append(self.assigned_to)
			
			elif event_type == "assigned":
				title = f"Ticket {self.name}: Được giao cho bạn"
				message = f"Bạn đã được giao xử lý ticket: {self.title}"
				recipients = [self.assigned_to] if self.assigned_to else []
			
			if recipients:
				# Create notification using ERP Notification
				notification = frappe.new_doc("ERP Notification")
				notification.title = title
				notification.message = message
				notification.recipients = json.dumps(recipients)
				notification.notification_type = "system"
				notification.priority = "medium"
				notification.reference_doctype = "ERP Ticket"
				notification.reference_name = self.name
				notification.save(ignore_permissions=True)
		
		except Exception as e:
			frappe.log_error(f"Failed to create ticket notification: {str(e)}")
	
	def assign_to_user(self, user):
		"""Assign ticket to a user"""
		self.assigned_to = user
		self.status = "in_progress"
		self.save(ignore_permissions=True)
	
	def resolve_ticket(self, resolution):
		"""Resolve ticket with solution"""
		self.resolution = resolution
		self.status = "resolved"
		self.resolved_at = frappe.utils.now()
		self.save(ignore_permissions=True)
	
	def close_ticket(self):
		"""Close ticket"""
		self.status = "closed"
		self.closed_at = frappe.utils.now()
		self.save(ignore_permissions=True)


@frappe.whitelist()
def create_ticket(title, description, ticket_type="support", priority="medium", category=None):
	"""Create a new ticket"""
	ticket = frappe.new_doc("ERP Ticket")
	ticket.title = title
	ticket.description = description
	ticket.ticket_type = ticket_type
	ticket.priority = priority
	ticket.category = category
	ticket.save(ignore_permissions=True)
	
	return ticket


@frappe.whitelist()
def get_user_tickets(user=None, status=None, limit=50):
	"""Get tickets for a user"""
	if not user:
		user = frappe.session.user
	
	filters = {"creator": user}
	if status:
		filters["status"] = status
	
	tickets = frappe.get_all("ERP Ticket",
		filters=filters,
		fields=["name", "title", "status", "priority", "created_at", "assigned_to"],
		order_by="created_at desc",
		limit=limit
	)
	
	return tickets


@frappe.whitelist()
def get_assigned_tickets(user=None, status=None, limit=50):
	"""Get tickets assigned to a user"""
	if not user:
		user = frappe.session.user
	
	filters = {"assigned_to": user}
	if status:
		filters["status"] = status
	
	tickets = frappe.get_all("ERP Ticket",
		filters=filters,
		fields=["name", "title", "status", "priority", "created_at", "creator"],
		order_by="created_at desc",
		limit=limit
	)
	
	return tickets


@frappe.whitelist()
def update_ticket_status(ticket_name, status, resolution=None):
	"""Update ticket status"""
	ticket = frappe.get_doc("ERP Ticket", ticket_name)
	ticket.status = status
	
	if resolution:
		ticket.resolution = resolution
	
	if status == "resolved":
		ticket.resolved_at = frappe.utils.now()
	elif status == "closed":
		ticket.closed_at = frappe.utils.now()
	
	ticket.save(ignore_permissions=True)
	return ticket