import frappe
from frappe import _
from frappe.model.document import Document
from datetime import datetime, timedelta


class SISStudentLeaveRequest(Document):
	def before_save(self):
		"""Calculate total days and validate dates"""
		self.calculate_total_days()
		self.validate_dates()

	def calculate_total_days(self):
		"""Calculate total leave days"""
		if self.start_date and self.end_date:
			start = datetime.strptime(str(self.start_date), '%Y-%m-%d')
			end = datetime.strptime(str(self.end_date), '%Y-%m-%d')
			# Include both start and end dates
			self.total_days = (end - start).days + 1

	def validate_dates(self):
		"""Validate start and end dates"""
		if self.start_date and self.end_date:
			if self.start_date > self.end_date:
				frappe.throw(_("Ngày kết thúc phải sau hoặc bằng ngày bắt đầu"))

	def validate(self):
		"""Additional validations"""
		self.validate_parent_student_relationship()
		self.populate_student_info()
		self.populate_parent_info()

	def validate_parent_student_relationship(self):
		"""Validate that parent has relationship with the student"""
		if not frappe.db.exists("CRM Family Relationship", {
			"parent": self.parent_id,
			"student": self.student_id
		}):
			frappe.throw(_("Phụ huynh không có quyền gửi đơn cho học sinh này"))

	def populate_student_info(self):
		"""Populate student name and code from student_id"""
		if self.student_id:
			student = frappe.get_doc("CRM Student", self.student_id)
			self.student_name = student.student_name
			self.student_code = student.student_code

	def populate_parent_info(self):
		"""Populate parent name from parent_id"""
		if self.parent_id:
			parent = frappe.get_doc("CRM Guardian", self.parent_id)
			self.parent_name = parent.guardian_name

	@frappe.whitelist()
	def can_edit(self):
		"""Check if this leave request can still be edited by parent"""
		if not self.submitted_at:
			return True

		# Check if within 24 hours
		submitted_time = datetime.strptime(str(self.submitted_at), '%Y-%m-%d %H:%M:%S.%f')
		time_diff = datetime.now() - submitted_time

		return time_diff.total_seconds() <= (24 * 60 * 60)  # 24 hours in seconds

	def after_insert(self):
		"""Auto-sync leave to attendance after creation"""
		frappe.logger().info(f"🔄 [Leave] Auto-syncing leave {self.name} to attendance")
		try:
			self.sync_to_attendance()
		except Exception as e:
			frappe.logger().error(f"❌ [Leave] Failed to sync to attendance: {str(e)}")
			# Don't block leave creation if sync fails
			frappe.log_error(
				title=f"Leave Sync Error: {self.name}",
				message=f"Failed to sync leave to attendance: {str(e)}\n\n{frappe.get_traceback()}"
			)

	def on_update(self):
		"""Re-sync attendance when leave is updated"""
		if self.has_value_changed('start_date') or self.has_value_changed('end_date'):
			frappe.logger().info(f"🔄 [Leave] Dates changed, re-syncing leave {self.name}")
			try:
				# Delete old attendance records first
				self.delete_synced_attendance()
				# Re-sync
				self.sync_to_attendance()
			except Exception as e:
				frappe.logger().error(f"❌ [Leave] Failed to re-sync: {str(e)}")
				frappe.log_error(
					title=f"Leave Re-sync Error: {self.name}",
					message=f"Failed to re-sync leave: {str(e)}\n\n{frappe.get_traceback()}"
				)

	def on_trash(self):
		"""Delete synced attendance when leave is deleted"""
		frappe.logger().info(f"🗑️ [Leave] Deleting synced attendance for leave {self.name}")
		try:
			self.delete_synced_attendance()
		except Exception as e:
			frappe.logger().error(f"❌ [Leave] Failed to delete attendance: {str(e)}")

	def sync_to_attendance(self):
		"""Sync leave to homeroom attendance for each day in the leave period"""
		if not self.start_date or not self.end_date or not self.student_id:
			return

		frappe.logger().info(f"📅 [Leave] Syncing {self.total_days} days for student {self.student_id}")

		# Get student's class
		class_student = frappe.get_value(
			"SIS Class Student",
			filters={"student_id": self.student_id},
			fieldname=["name", "class_id"],
			as_dict=True
		)

		if not class_student:
			frappe.logger().warning(f"⚠️ [Leave] Student {self.student_id} not in any class")
			return

		class_id = class_student.class_id
		student_name = self.student_name
		student_code = self.student_code

		# Iterate through each day in the leave period
		current_date = datetime.strptime(str(self.start_date), '%Y-%m-%d')
		end_date = datetime.strptime(str(self.end_date), '%Y-%m-%d')

		synced_count = 0
		while current_date <= end_date:
			date_str = current_date.strftime('%Y-%m-%d')

			try:
				# Check if homeroom attendance already exists for this date
				existing = frappe.db.exists("SIS Class Attendance", {
					"student_id": self.student_id,
					"class_id": class_id,
					"date": date_str,
					"period": "homeroom"
				})

				if existing:
					# Update existing record
					doc = frappe.get_doc("SIS Class Attendance", existing)
					doc.status = "excused"
					doc.remarks = f"Đơn nghỉ phép: {self.reason_display} (ID: {self.name})"
					doc.flags.ignore_permissions = True
					doc.save()
					frappe.logger().info(f"✅ [Leave] Updated attendance for {date_str}")
				else:
					# Create new attendance record
					attendance_doc = frappe.get_doc({
						"doctype": "SIS Class Attendance",
						"student_id": self.student_id,
						"student_name": student_name,
						"student_code": student_code,
						"class_id": class_id,
						"date": date_str,
						"period": "homeroom",
						"status": "excused",
						"remarks": f"Đơn nghỉ phép: {self.reason_display} (ID: {self.name})"
					})
					attendance_doc.flags.ignore_permissions = True
					attendance_doc.insert()
					frappe.logger().info(f"✅ [Leave] Created attendance for {date_str}")

				synced_count += 1

			except Exception as e:
				frappe.logger().error(f"❌ [Leave] Failed to sync date {date_str}: {str(e)}")
				# Continue with next date

			current_date += timedelta(days=1)

		frappe.logger().info(f"✨ [Leave] Successfully synced {synced_count}/{self.total_days} days")

	def delete_synced_attendance(self):
		"""Delete all attendance records created by this leave"""
		if not self.name:
			return

		# Find all attendance records with this leave ID in remarks
		attendance_records = frappe.get_all(
			"SIS Class Attendance",
			filters={
				"student_id": self.student_id,
				"remarks": ["like", f"%ID: {self.name}%"]
			},
			pluck="name"
		)

		frappe.logger().info(f"🗑️ [Leave] Deleting {len(attendance_records)} attendance records")

		for record_name in attendance_records:
			try:
				frappe.delete_doc("SIS Class Attendance", record_name, force=True, ignore_permissions=True)
			except Exception as e:
				frappe.logger().error(f"❌ [Leave] Failed to delete {record_name}: {str(e)}")

	@property
	def reason_display(self):
		"""Get Vietnamese display name for reason"""
		mapping = {
			'sick_child': 'Con ốm',
			'family_matters': 'Gia đình có việc bận',
			'other': 'Lý do khác'
		}
		return mapping.get(self.reason, self.reason)
