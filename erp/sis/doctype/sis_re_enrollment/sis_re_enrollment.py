# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import nowdate, getdate, now


class SISReenrollment(Document):
	"""
	Đơn tái ghi danh của học sinh.
	Phụ huynh nộp đơn qua Parent Portal.
	Admin/Tuyển sinh có thể chỉnh sửa trực tiếp.
	"""
	
	def validate(self):
		"""Validate trước khi lưu"""
		self.validate_config_active()
		self.validate_duplicate()
		self.set_student_info()
		self.set_submission_time()
	
	def validate_config_active(self):
		"""Kiểm tra config có đang mở không"""
		# Skip validation nếu admin đang tạo records (qua sync)
		if self.flags.get("skip_config_validation"):
			return
		
		if self.config_id:
			config = frappe.get_doc("SIS Re-enrollment Config", self.config_id)
			
			# Chỉ validate khi tạo mới (không phải admin sửa)
			if self.is_new():
				if not config.is_active:
					frappe.throw("Đợt tái ghi danh này đã đóng")
				
				if not config.is_within_period():
					frappe.throw(
						f"Chưa đến hoặc đã hết thời gian tái ghi danh. "
						f"Thời gian: {config.start_date} - {config.end_date}"
					)
	
	def validate_duplicate(self):
		"""Kiểm tra học sinh đã nộp đơn cho đợt này chưa"""
		if self.is_new() and self.student_id and self.config_id:
			existing = frappe.db.exists(
				"SIS Re-enrollment",
				{
					"student_id": self.student_id,
					"config_id": self.config_id
				}
			)
			
			if existing:
				frappe.throw(
					f"Học sinh này đã nộp đơn tái ghi danh cho đợt này. "
					f"Mã đơn: {existing}"
				)
	
	def set_student_info(self):
		"""Tự động lấy thông tin học sinh"""
		if self.student_id:
			# Lấy thông tin học sinh
			student = frappe.get_doc("CRM Student", self.student_id)
			self.student_name = student.student_name
			self.student_code = student.student_code
			self.campus_id = student.campus_id
			
			# Lấy lớp hiện tại của học sinh
			if not self.current_class:
				self.current_class = self.get_current_class()
	
	def get_current_class(self):
		"""Lấy lớp hiện tại của học sinh"""
		if not self.student_id:
			return None
		
		# Lấy năm học hiện tại (đang active)
		current_school_year = frappe.db.get_value(
			"SIS School Year",
			{"is_enable": 1, "campus_id": self.campus_id},
			"name",
			order_by="start_date desc"
		)
		
		if not current_school_year:
			return None
		
		# Tìm lớp regular của học sinh trong năm học hiện tại
		class_student = frappe.db.get_value(
			"SIS Class Student",
			{
				"student_id": self.student_id,
				"school_year_id": current_school_year,
				"class_type": ["in", ["regular", "", None]]
			},
			["class_id"],
			as_dict=True
		)
		
		if class_student and class_student.class_id:
			# Lấy tên lớp
			class_title = frappe.db.get_value("SIS Class", class_student.class_id, "title")
			return class_title
		
		return None
	
	def set_submission_time(self):
		"""Đặt thời gian nộp đơn
		
		Chỉ set submitted_at khi:
		1. Phụ huynh thực sự nộp đơn (có decision)
		2. KHÔNG set khi admin tạo record trắng tự động
		
		Điều này đảm bảo record trắng có submitted_at = None -> hiển thị "Chưa nộp"
		"""
		# Chỉ set submitted_at khi có decision (phụ huynh đã chọn quyết định)
		# Record trắng (không có decision) sẽ có submitted_at = None
		if self.is_new() and not self.submitted_at and self.decision:
			self.submitted_at = now()
		
		# Đặt thông tin ưu đãi nếu chọn tái ghi danh
		if self.decision == "re_enroll" and self.config_id and not self.selected_discount_deadline:
			config = frappe.get_doc("SIS Re-enrollment Config", self.config_id)
			current_discount = config.get_current_discount()
			if current_discount:
				self.selected_discount_deadline = current_discount.get("deadline")
	
	def before_save(self):
		"""Trước khi lưu - kiểm tra nếu là admin sửa"""
		if not self.is_new():
			# Đây là update, kiểm tra xem có phải admin sửa không
			old_doc = self.get_doc_before_save()
			if old_doc:
				# Kiểm tra xem có thay đổi các trường quan trọng không
				important_fields = ["decision", "payment_type", "not_re_enroll_reason", "status"]
				for field in important_fields:
					if getattr(self, field) != getattr(old_doc, field):
						# Có thay đổi, ghi nhận admin đã sửa
						self.modified_by_admin = frappe.session.user
						self.admin_modified_at = now()
						break


def get_student_current_class(student_id, campus_id=None):
	"""
	Hàm helper để lấy lớp hiện tại của học sinh.
	Có thể được gọi từ API.
	"""
	if not student_id:
		return None
	
	# Lấy campus_id nếu chưa có
	if not campus_id:
		campus_id = frappe.db.get_value("CRM Student", student_id, "campus_id")
	
	if not campus_id:
		return None
	
	# Lấy năm học hiện tại
	current_school_year = frappe.db.get_value(
		"SIS School Year",
		{"is_enable": 1, "campus_id": campus_id},
		"name",
		order_by="start_date desc"
	)
	
	if not current_school_year:
		return None
	
	# Tìm lớp regular
	class_student = frappe.db.sql("""
		SELECT cs.class_id, c.title as class_title
		FROM `tabSIS Class Student` cs
		INNER JOIN `tabSIS Class` c ON cs.class_id = c.name
		WHERE cs.student_id = %s
		AND cs.school_year_id = %s
		AND (c.class_type = 'regular' OR c.class_type IS NULL OR c.class_type = '')
		LIMIT 1
	""", (student_id, current_school_year), as_dict=True)
	
	if class_student:
		return {
			"class_id": class_student[0].class_id,
			"class_title": class_student[0].class_title
		}
	
	return None

