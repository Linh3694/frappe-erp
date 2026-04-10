# Copyright (c) 2026, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class ERPAdministrativeSupportAssignment(Document):
	# Phân công PIC theo khu vực + danh mục hỗ trợ (một khu vực + danh mục có thể nhiều PIC — nhiều dòng)
	def validate(self):
		area = (self.area_title or "").strip()
		if not area:
			frappe.throw(_("Thiếu tên khu vực"))
		self.area_title = area

		filters = {
			"area_title": area,
			"support_category": self.support_category,
			"pic": self.pic,
		}
		if getattr(self, "name", None):
			filters["name"] = ("!=", self.name)
		dup = frappe.db.exists("ERP Administrative Support Assignment", filters)
		if dup:
			frappe.throw(_("Đã có phân công trùng: cùng khu vực, danh mục và PIC"))
