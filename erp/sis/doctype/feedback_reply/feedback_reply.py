# Copyright (c) 2025, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class FeedbackReply(Document):
	def validate(self):
		"""Validate reply before save"""
		from frappe.utils import now
		
		# Set reply_date if not set
		if not self.reply_date:
			self.reply_date = now()
		
		# Auto-detect reply_by_type if not set
		if not self.reply_by_type and self.reply_by:
			# Check if user is guardian
			user_roles = frappe.get_roles(self.reply_by)
			if "Guardian" in user_roles:
				self.reply_by_type = "Guardian"
			else:
				self.reply_by_type = "Staff"

