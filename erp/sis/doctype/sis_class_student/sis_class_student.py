# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class SISClassStudent(Document):
	def validate(self):
		"""Validate before insert/update"""
		self.validate_no_duplicate_regular_classes()
	
	def validate_no_duplicate_regular_classes(self):
		"""
		Validate that a student cannot be assigned to multiple Regular classes
		in the same school year.
		
		Business Rule: One student can only belong to ONE Regular class per school year.
		Students can be in multiple Mixed/Special classes, but only ONE Regular class.
		"""
		if not self.student_id or not self.class_id or not self.school_year_id:
			return
		
		# Get the class type of current class
		current_class = frappe.db.get_value(
			"SIS Class", 
			self.class_id, 
			["class_type", "title"], 
			as_dict=True
		)
		
		if not current_class:
			return
		
		# Only validate if current class is Regular (or NULL which defaults to Regular)
		if current_class.get("class_type") not in ["regular", None, ""]:
			# This is a Mixed/Special class - allow multiple assignments
			return
		
		# Check for existing assignments in other Regular classes in same school year
		existing_regular_classes = frappe.db.sql("""
			SELECT 
				cs.name,
				cs.class_id,
				c.title as class_title,
				c.class_type
			FROM `tabSIS Class Student` cs
			INNER JOIN `tabSIS Class` c ON cs.class_id = c.name
			WHERE cs.student_id = %s
			AND cs.school_year_id = %s
			AND cs.name != %s
			AND cs.class_id != %s
			AND (c.class_type = 'regular' OR c.class_type IS NULL OR c.class_type = '')
		""", (self.student_id, self.school_year_id, self.name or "", self.class_id), as_dict=True)
		
		if existing_regular_classes:
			# Found conflict - student already in another Regular class
			conflict_classes = [f"{c.class_title} ({c.class_id})" for c in existing_regular_classes]
			
			frappe.throw(
				msg=(
					f"<strong>Lỗi:</strong> Học sinh <strong>{self.student_id}</strong> đã tồn tại trong lớp Regular khác: "
					f"<strong>{', '.join(conflict_classes)}</strong>.<br><br>"
					f"<strong>Quy tắc:</strong> Một học sinh chỉ có thể thuộc <u>1 lớp Regular</u> trong cùng năm học.<br>"
					f"Học sinh có thể tham gia nhiều lớp Mixed/Special, nhưng chỉ 1 lớp Regular.<br><br>"
					f"<strong>Giải pháp:</strong> Vui lòng xóa học sinh khỏi lớp cũ trước khi thêm vào lớp <strong>{current_class.get('title')}</strong>."
				),
				title="Duplicate Regular Class Assignment"
			)
	
	def on_trash(self):
		"""
		When a Class Student assignment is deleted, cleanup related Student Subject records.
		This ensures data consistency.
		"""
		if not self.student_id or not self.class_id:
			return
		
		try:
			# Delete Student Subject records for this student in this class
			frappe.db.sql("""
				DELETE FROM `tabSIS Student Subject`
				WHERE student_id = %s
				AND class_id = %s
			""", (self.student_id, self.class_id))
			
			frappe.msgprint(
				f"Đã xóa {frappe.db.sql_list('SELECT COUNT(*) FROM `tabSIS Student Subject` WHERE student_id = %s AND class_id = %s', (self.student_id, self.class_id))[0] if frappe.db.sql_list('SELECT COUNT(*) FROM `tabSIS Student Subject` WHERE student_id = %s AND class_id = %s', (self.student_id, self.class_id)) else 0} "
				f"Student Subject records liên quan."
			)
		except Exception as e:
			frappe.log_error(f"Error cleaning up Student Subject on Class Student deletion: {str(e)}")
