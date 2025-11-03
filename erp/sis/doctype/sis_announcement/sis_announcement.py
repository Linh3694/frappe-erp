# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
import json
from datetime import datetime


class SISAnnouncement(Document):
	"""
	SIS Announcement DocType for managing announcements sent to parents/students
	"""
	
	def validate(self):
		"""Validate announcement data before save"""
		self.validate_required_fields()
		self.validate_recipients()
	
	def validate_required_fields(self):
		"""Validate that all required fields are filled"""
		if not self.title_en or not self.title_en.strip():
			frappe.throw("English title is required")
		
		if not self.title_vn or not self.title_vn.strip():
			frappe.throw("Vietnamese title is required")
		
		if not self.content_en or not self.content_en.strip():
			frappe.throw("English content is required")
		
		if not self.content_vn or not self.content_vn.strip():
			frappe.throw("Vietnamese content is required")
	
	def validate_recipients(self):
		"""Validate recipients JSON"""
		if not self.recipients:
			return
		
		try:
			if isinstance(self.recipients, str):
				recipients = json.loads(self.recipients)
			else:
				recipients = self.recipients
			
			if not isinstance(recipients, list):
				frappe.throw("Recipients must be a JSON array")
			
			if len(recipients) == 0 and self.recipient_type == "specific":
				frappe.throw("At least one recipient is required for specific announcements")
		
		except json.JSONDecodeError:
			frappe.throw("Recipients must be valid JSON")
	
	def before_save(self):
		"""Actions to perform before saving"""
		# Ensure campus_id is set
		if not self.campus_id:
			from erp.utils.campus_utils import get_current_campus_from_context
			campus_id = get_current_campus_from_context()
			if campus_id:
				self.campus_id = campus_id
		
		# Set created_at and created_by on insert
		if not self.creation:
			self.created_at = datetime.now()
			self.created_by = frappe.session.user
		
		# Update updated_at and updated_by on every save
		self.updated_at = datetime.now()
		self.updated_by = frappe.session.user
	
	def on_update(self):
		"""Actions to perform after update"""
		frappe.clear_cache(doctype=self.doctype)
