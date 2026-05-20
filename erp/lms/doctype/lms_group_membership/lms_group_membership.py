import frappe
from frappe.model.document import Document


class LMSGroupMembership(Document):
	def validate(self):
		# Mỗi HS chỉ thuộc một nhóm trong cùng section (qua group.section)
		section = frappe.db.get_value("LMS Group", self.group, "section")
		existing = frappe.db.sql(
			"""
			SELECT m.name FROM `tabLMS Group Membership` m
			INNER JOIN `tabLMS Group` g ON g.name = m.group
			WHERE m.student_id = %s AND g.section = %s AND m.name != %s
			LIMIT 1
			""",
			(self.student_id, section, self.name or ""),
		)
		if existing:
			frappe.throw("Học sinh đã thuộc nhóm khác trong section này")
