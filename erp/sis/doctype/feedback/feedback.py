# Copyright (c) 2025, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class Feedback(Document):
	def _get_missing_mandatory_fields(self):
		"""Override to skip field validation based on feedback_type"""
		missing = super()._get_missing_mandatory_fields()
		
		# Filter out fields based on feedback_type
		if self.feedback_type == "Góp ý":
			# Skip rating field for "Góp ý" type
			missing = [m for m in missing if m[0] != "rating"]
		elif self.feedback_type == "Đánh giá":
			# Skip "Góp ý" fields (department, title, content) for "Đánh giá" type
			missing = [m for m in missing if m[0] not in ["department", "title", "content", "priority"]]
		
		return missing
	
	def validate(self):
		"""Validate feedback before save"""
		# Handle fields based on feedback_type
		if self.feedback_type == "Góp ý":
			# Clear rating fields to avoid validation errors
			# Set rating to 0 instead of None because Rating fieldtype may not accept None
			if hasattr(self, 'rating'):
				self.rating = 0
			if hasattr(self, 'rating_comment'):
				self.rating_comment = None
		elif self.feedback_type == "Đánh giá":
			# Validate rating for "Đánh giá" type
			if not self.rating or self.rating == 0:
				frappe.throw("Rating là bắt buộc cho loại Đánh giá")
			# Clear "Góp ý" fields to avoid validation errors
			if hasattr(self, 'department'):
				self.department = None
			if hasattr(self, 'title'):
				self.title = None
			if hasattr(self, 'content'):
				self.content = None
			if hasattr(self, 'priority'):
				self.priority = None
		
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
		
		# Set first_response_date when first PUBLIC reply is added by staff
		if self.replies and not self.first_response_date:
			# Only consider public replies (not internal/draft)
			public_staff_replies = [r for r in self.replies if r.reply_by_type == "Staff" and not r.is_internal]
			if public_staff_replies:
				first_staff_reply = min(public_staff_replies, key=lambda x: x.reply_date or self.creation)
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

	def autoname(self):
		"""Generate custom autoname with monthly counter reset"""
		from frappe.utils import now

		# Get current year and month (YYMM format)
		current_date = now()
		yy = current_date[2:4]  # Last 2 digits of year
		mm = current_date[5:7]  # Month

		# Base name format: PP + YY + MM
		base_name = f"PP{yy}{mm}"

		# Find the highest number for this month
		existing_names = frappe.db.sql("""
			SELECT name FROM `tabFeedback`
			WHERE name LIKE %s
			ORDER BY name DESC
			LIMIT 1
		""", (f"{base_name}%",))

		if existing_names:
			# Extract the number from the last name (last 4 digits)
			last_name = existing_names[0][0]
			try:
				last_number = int(last_name[-4:])  # Last 4 digits
				next_number = last_number + 1
			except (ValueError, IndexError):
				next_number = 1
		else:
			next_number = 1

		# Format number with leading zeros (4 digits)
		formatted_number = f"{next_number:04d}"

		# Set the name
		self.name = f"{base_name}{formatted_number}"
	
	def on_update(self):
		"""Handle status changes"""
		from frappe.utils import now
		
		# Set closed_at when status changes to Đóng or Tự động đóng
		if self.status in ["Đóng", "Tự động đóng"] and not self.closed_at:
			self.closed_at = now()

