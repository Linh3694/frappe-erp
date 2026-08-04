# Copyright (c) 2026, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class SISClassNewsfeedPoster(Document):
	def validate(self):
		"""Chặn trùng + chỉ cho phép GV đang dạy lớp (Subject Assignment), không thêm GVCN/phó."""
		if not self.class_id or not self.school_year_id or not self.teacher_id:
			return

		cls = frappe.db.get_value(
			"SIS Class",
			self.class_id,
			["name", "campus_id", "homeroom_teacher", "vice_homeroom_teacher", "school_year_id"],
			as_dict=True,
		)
		if not cls:
			frappe.throw("Không tìm thấy lớp", title="Bảng tin lớp")

		if not self.campus_id:
			self.campus_id = cls.get("campus_id")

		homeroom_ids = {
			cls.get("homeroom_teacher"),
			cls.get("vice_homeroom_teacher"),
		}
		if self.teacher_id in homeroom_ids:
			frappe.throw(
				"Giáo viên chủ nhiệm / phó đã có quyền đăng bài mặc định — không cần thêm vào danh sách",
				title="Bảng tin lớp",
			)

		teaches = frappe.db.exists(
			"SIS Subject Assignment",
			{
				"class_id": self.class_id,
				"school_year_id": self.school_year_id,
				"teacher_id": self.teacher_id,
			},
		)
		if not teaches:
			frappe.throw(
				"Chỉ được thêm giáo viên đang dạy lớp này (phân công môn)",
				title="Bảng tin lớp",
			)

		filters = {
			"class_id": self.class_id,
			"school_year_id": self.school_year_id,
			"teacher_id": self.teacher_id,
		}
		if not self.is_new():
			filters["name"] = ["!=", self.name]
		if frappe.db.exists("SIS Class Newsfeed Poster", filters):
			frappe.throw(
				"Giáo viên này đã có trong danh sách được đăng bài của lớp",
				title="Bảng tin lớp",
			)

		if self.is_new() and not self.added_by:
			user = frappe.session.user
			if user and user != "Guest":
				self.added_by = user
