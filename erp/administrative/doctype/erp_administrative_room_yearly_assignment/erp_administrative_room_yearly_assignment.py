# Copyright (c) 2026, Wellspring International School and contributors

import frappe
from frappe import _
from frappe.model.document import Document


class ERPAdministrativeRoomYearlyAssignment(Document):
	def validate(self):
		self._ensure_unique_room_year()
		self._sync_teacher_names()

	def _ensure_unique_room_year(self):
		existing = frappe.db.exists(
			"ERP Administrative Room Yearly Assignment",
			{"room": self.room, "school_year_id": self.school_year_id, "name": ("!=", self.name or "")},
		)
		if existing:
			frappe.throw(_("Đã có gán năm cho phòng này trong năm học đã chọn."))

	def _sync_teacher_names(self):
		if self.homeroom_teacher_id:
			user = frappe.db.get_value("SIS Teacher", self.homeroom_teacher_id, "user_id")
			if user:
				self.homeroom_teacher_name = frappe.get_value("User", user, "full_name") or ""
		for row in self.responsible_users or []:
			if row.user and not row.full_name:
				row.full_name = frappe.get_value("User", row.user, "full_name") or ""
