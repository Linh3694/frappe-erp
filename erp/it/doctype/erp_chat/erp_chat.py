# Copyright (c) 2024, Your Organization and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
import json


class ERPChat(Document):
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
		
		# Set chat type based on participants
		participants = json.loads(self.participants or "[]")
		if len(participants) > 2:
			self.is_group = 1
			self.chat_type = "group"
		else:
			self.is_group = 0
			self.chat_type = "direct"
	
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
	
	def add_participant(self, user):
		"""Add a participant to the chat"""
		participants = json.loads(self.participants or "[]")
		if user not in participants:
			participants.append(user)
			self.participants = json.dumps(participants)
			
			# Update chat type if needed
			if len(participants) > 2:
				self.is_group = 1
				self.chat_type = "group"
			
			self.save(ignore_permissions=True)
	
	def remove_participant(self, user):
		"""Remove a participant from the chat"""
		participants = json.loads(self.participants or "[]")
		if user in participants:
			participants.remove(user)
			self.participants = json.dumps(participants)
			
			# Update chat type if needed
			if len(participants) <= 2:
				self.is_group = 0
				self.chat_type = "direct"
			
			self.save(ignore_permissions=True)
	
	def update_last_message(self, message, timestamp=None):
		"""Update last message info"""
		self.last_message = message[:100] + "..." if len(message) > 100 else message
		self.last_message_time = timestamp or frappe.utils.now()
		self.message_count = (self.message_count or 0) + 1
		self.save(ignore_permissions=True)
	
	def archive_chat(self):
		"""Archive the chat"""
		self.archived = 1
		self.archived_at = frappe.utils.now()
		self.save(ignore_permissions=True)
	
	def unarchive_chat(self):
		"""Unarchive the chat"""
		self.archived = 0
		self.archived_at = None
		self.save(ignore_permissions=True)


# Create ERP Chat Message doctype
@frappe.whitelist()
def create_chat_message_doctype():
	"""Create ERP Chat Message doctype if it doesn't exist"""
	if not frappe.db.exists("DocType", "ERP Chat Message"):
		doc = frappe.new_doc("DocType")
		doc.name = "ERP Chat Message"
		doc.module = "IT"
		doc.autoname = "format:MSG-{#####}"
		doc.fields = [
			{
				"fieldname": "chat",
				"fieldtype": "Link",
				"options": "ERP Chat",
				"label": "Chat",
				"reqd": 1
			},
			{
				"fieldname": "sender",
				"fieldtype": "Link",
				"options": "User",
				"label": "Người gửi",
				"reqd": 1
			},
			{
				"fieldname": "message",
				"fieldtype": "Long Text",
				"label": "Tin nhắn",
				"reqd": 1
			},
			{
				"fieldname": "message_type",
				"fieldtype": "Select",
				"options": "text\nimage\nfile\nemoji",
				"default": "text",
				"label": "Loại tin nhắn"
			},
			{
				"fieldname": "attachments",
				"fieldtype": "JSON",
				"label": "File đính kèm"
			},
			{
				"fieldname": "is_edited",
				"fieldtype": "Check",
				"default": "0",
				"label": "Đã chỉnh sửa"
			},
			{
				"fieldname": "edited_at",
				"fieldtype": "Datetime",
				"label": "Thời gian chỉnh sửa"
			},
			{
				"fieldname": "reply_to",
				"fieldtype": "Link",
				"options": "ERP Chat Message",
				"label": "Trả lời tin nhắn"
			},
			{
				"fieldname": "delivery_status",
				"fieldtype": "Select",
				"options": "sent\ndelivered\nread",
				"default": "sent",
				"label": "Trạng thái gửi"
			},
			{
				"fieldname": "sent_at",
				"fieldtype": "Datetime",
				"label": "Thời gian gửi"
			}
		]
		doc.save(ignore_permissions=True)


@frappe.whitelist()
def create_chat(chat_name, participants, chat_type="direct", description=None):
	"""Create a new chat"""
	chat = frappe.new_doc("ERP Chat")
	chat.chat_name = chat_name
	chat.participants = json.dumps(participants) if isinstance(participants, list) else participants
	chat.chat_type = chat_type
	chat.description = description
	chat.save(ignore_permissions=True)
	
	return chat


@frappe.whitelist()
def get_user_chats(user=None, limit=50):
	"""Get chats for a user"""
	if not user:
		user = frappe.session.user
	
	# Get chats where user is a participant
	chats = frappe.db.sql("""
		SELECT name, chat_name, chat_type, last_message, last_message_time, 
			   participants, is_group, archived
		FROM `tabERP Chat`
		WHERE JSON_CONTAINS(participants, %s)
		AND archived = 0
		ORDER BY last_message_time DESC
		LIMIT %s
	""", (f'"{user}"', limit), as_dict=True)
	
	return chats


@frappe.whitelist()
def send_message(chat_name, message, message_type="text", attachments=None, reply_to=None):
	"""Send a message to a chat"""
	# Create message
	msg = frappe.new_doc("ERP Chat Message")
	msg.chat = chat_name
	msg.sender = frappe.session.user
	msg.message = message
	msg.message_type = message_type
	msg.attachments = json.dumps(attachments) if attachments else None
	msg.reply_to = reply_to
	msg.sent_at = frappe.utils.now()
	msg.save(ignore_permissions=True)
	
	# Update chat last message
	chat = frappe.get_doc("ERP Chat", chat_name)
	chat.update_last_message(message, msg.sent_at)
	
	return msg


@frappe.whitelist()
def get_chat_messages(chat_name, limit=50, before_message=None):
	"""Get messages for a chat"""
	filters = {"chat": chat_name}
	
	if before_message:
		before_doc = frappe.get_doc("ERP Chat Message", before_message)
		filters["sent_at"] = ["<", before_doc.sent_at]
	
	messages = frappe.get_all("ERP Chat Message",
		filters=filters,
		fields=["name", "sender", "message", "message_type", "attachments", 
				"is_edited", "edited_at", "reply_to", "sent_at"],
		order_by="sent_at desc",
		limit=limit
	)
	
	return messages[::-1]  # Reverse to show oldest first