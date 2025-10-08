# Copyright (c) 2024, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class PushSubscription(Document):
	def before_save(self):
		"""Update last_used timestamp"""
		self.last_used = frappe.utils.now()
	
	def on_trash(self):
		"""Log when subscription is deleted"""
		frappe.log_error(
			f"Push subscription deleted for user: {self.user}",
			"Push Subscription Deleted"
		)

