# Copyright (c) 2025, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class Feedback(Document):
	def validate(self):
		"""Validate feedback before save"""
		# Skip rating validation for "Góp ý" type
		if self.feedback_type == "Góp ý":
			# Clear rating fields to avoid validation errors
			if hasattr(self, 'rating'):
				self.rating = None
			if hasattr(self, 'rating_comment'):
				self.rating_comment = None
		
		# Validate rating for "Đánh giá" type
		if self.feedback_type == "Đánh giá":
			if not self.rating or self.rating == 0:
				frappe.throw("Rating là bắt buộc cho loại Đánh giá")
		
		# Auto-set status for Rating type
		if self.feedback_type == "Đánh giá" and self.status == "Mới":
			self.status = "Hoàn thành"
		
		# Update conversation count
		if self.replies:
			self.conversation_count = len(self.replies)
		else:
			self.conversation_count = 0
		
		# Update last_reply_date if there are replies
		if self.replies:
			last_reply = max(self.replies, key=lambda x: x.reply_date or self.creation)
			self.last_reply_date = last_reply.reply_date or self.creation
		
		# Update last_updated
		from frappe.utils import now
		self.last_updated = now()
		
		# Set first_response_date when first reply is added by staff
		if self.replies and not self.first_response_date:
			staff_replies = [r for r in self.replies if r.reply_by_type == "Staff"]
			if staff_replies:
				first_staff_reply = min(staff_replies, key=lambda x: x.reply_date or self.creation)
				self.first_response_date = first_staff_reply.reply_date or self.creation
		
		# Calculate deadline based on priority (only for Góp ý)
		if self.feedback_type == "Góp ý" and self.priority and not self.deadline:
			self._calculate_deadline()
		
		# Update SLA status
		if self.feedback_type == "Góp ý" and self.deadline:
			self._update_sla_status()
	
	def _calculate_deadline(self):
		"""Calculate deadline based on priority"""
		from frappe.utils import add_to_date, get_datetime, now
		from datetime import datetime, timedelta
		
		# Priority to hours mapping
		priority_hours = {
			"Khẩn cấp": 6,
			"Cao": 12,
			"Trung bình": 24,
			"Thấp": 48
		}
		
		hours = priority_hours.get(self.priority, 24)
		
		# Start from assigned_date or submitted_at
		start_date = self.assigned_date or self.submitted_at or now()
		start_datetime = get_datetime(start_date)
		
		# Add business hours (exclude Sat-Sun)
		deadline = start_datetime
		hours_added = 0
		
		while hours_added < hours:
			deadline = deadline + timedelta(hours=1)
			# Skip weekends (Saturday=5, Sunday=6)
			if deadline.weekday() < 5:  # Monday-Friday
				hours_added += 1
		
		self.deadline = deadline
	
	def _update_sla_status(self):
		"""Update SLA status based on deadline"""
		from frappe.utils import get_datetime, now
		
		if not self.deadline:
			return
		
		deadline_dt = get_datetime(self.deadline)
		now_dt = get_datetime(now())
		
		# Calculate hours until deadline
		hours_until_deadline = (deadline_dt - now_dt).total_seconds() / 3600
		
		if hours_until_deadline < 0:
			self.sla_status = "Overdue"
		elif hours_until_deadline <= 6:
			self.sla_status = "Warning"
		else:
			self.sla_status = "On time"
	
	def before_insert(self):
		"""Set default values before insert"""
		from frappe.utils import now
		
		if not self.submitted_at:
			self.submitted_at = now()
		
		if not self.last_updated:
			self.last_updated = now()
	
	def on_update(self):
		"""Handle status changes"""
		from frappe.utils import now
		
		# Set closed_at when status changes to Đóng or Tự động đóng
		if self.status in ["Đóng", "Tự động đóng"] and not self.closed_at:
			self.closed_at = now()

