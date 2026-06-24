# Copyright (c) 2026, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_time

# Thứ mặc định (Monday = T2 theo lịch tuần FE)
DEFAULT_WEEKDAYS = [
	"Monday",
	"Tuesday",
	"Wednesday",
	"Thursday",
	"Friday",
	"Saturday",
	"Sunday",
]


class ERPRoomBookingConfig(Document):
	"""Cấu hình phòng được phép đặt + khung giờ khả dụng theo từng thứ."""

	def validate(self):
		# Đồng bộ campus từ phòng
		if self.room_id:
			room_building = frappe.db.get_value(
				"ERP Administrative Room", self.room_id, ["building_id", "campus_id"], as_dict=True
			)
			if room_building:
				if self.building_id and room_building.building_id != self.building_id:
					frappe.throw(_("Phòng không thuộc tòa nhà đã chọn"))
				if not self.building_id:
					self.building_id = room_building.building_id
				if room_building.campus_id and not self.campus_id:
					self.campus_id = room_building.campus_id

		# Mỗi phòng chỉ một cấu hình
		if self.room_id:
			dup = frappe.db.exists(
				"ERP Room Booking Config",
				{"room_id": self.room_id, "name": ["!=", self.name or ""]},
			)
			if dup:
				frappe.throw(_("Phòng này đã có cấu hình đặt phòng"))

		self._ensure_availability_rows()
		self._validate_availability()

	def _ensure_availability_rows(self):
		"""Đảm bảo có đủ 7 dòng theo thứ nếu thiếu."""
		if not self.availability:
			self.availability = []
		existing = {(row.day_of_week or "").strip() for row in self.availability}
		for day in DEFAULT_WEEKDAYS:
			if day not in existing:
				self.append(
					"availability",
					{
						"day_of_week": day,
						"is_closed": 0,
						"start_time": "07:00:00",
						"end_time": "18:00:00",
					},
				)

	def _validate_availability(self):
		seen = set()
		for row in self.availability or []:
			day = (row.day_of_week or "").strip()
			if not day:
				frappe.throw(_("Thiếu thứ trong khung giờ khả dụng"))
			if day in seen:
				frappe.throw(_("Trùng cấu hình cho thứ {0}").format(day))
			seen.add(day)
			if row.is_closed:
				continue
			st = get_time(row.start_time) if row.start_time else None
			et = get_time(row.end_time) if row.end_time else None
			if not st or not et:
				frappe.throw(_("Thiếu giờ mở/đóng cho thứ {0}").format(day))
			if et <= st:
				frappe.throw(_("Giờ đóng phải sau giờ mở cho thứ {0}").format(day))
