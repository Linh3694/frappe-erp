# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import re

import frappe
from frappe import _
from frappe.model.document import Document


# Định dạng mã vật lý: {short_title_tòa}.{số_phòng} — ví dụ B1A.303
PHYSICAL_CODE_PATTERN = re.compile(r"^[A-Za-z0-9]+\.[A-Za-z0-9]+$")
ROOM_NUMBER_PATTERN = re.compile(r"^[A-Za-z0-9]+$")


def _normalize_room_number_raw(room_number: str) -> str:
	"""Chuẩn hóa số phòng trước khi validate: dữ liệu cũ/migration đôi khi lưu nhầm cả mã vật lý (vd B1A.303) vào room_number."""
	rn = str(room_number).strip().upper()
	if "." in rn:
		rn = rn.split(".")[-1].strip()
	return rn


def compose_physical_code(building_id: str, room_number: str) -> str:
	"""Ghép mã phòng vật lý từ short_title tòa và số phòng."""
	if not building_id or not room_number:
		return ""
	st = (frappe.db.get_value("ERP Administrative Building", building_id, "short_title") or "").strip()
	rn = str(room_number).strip().upper()
	if not st or not rn:
		return ""
	return f"{st}.{rn}"


class ERPAdministrativeRoom(Document):
	def validate(self):
		self._sync_physical_code_and_titles()
		self.validate_physical_code_unique_per_campus()
		self.validate_capacity()

	def _sync_physical_code_and_titles(self):
		"""Tính physical_code từ building + room_number; đồng bộ title legacy nếu trống."""
		if self.building_id and self.room_number:
			rn = _normalize_room_number_raw(self.room_number)
			if not ROOM_NUMBER_PATTERN.match(rn):
				frappe.throw(_("Số phòng chỉ gồm chữ và số (ví dụ 303)."))
			code = compose_physical_code(self.building_id, rn)
			if not code:
				frappe.throw(_("Không lấy được ký hiệu tòa (short_title)."))
			if not PHYSICAL_CODE_PATTERN.match(code):
				frappe.throw(_("Mã vật lý không hợp lệ: {0}").format(code))
			self.room_number = rn
			self.physical_code = code
		elif self.physical_code and not self.room_number:
			# Bản ghi cũ sau patch: chỉ có physical_code
			pass
		elif not self.physical_code and self.title_vn:
			# Legacy: dùng title làm fallback mã tạm
			self.physical_code = self.title_vn.strip()
			self.needs_review = 1

		# Fallback tiêu đề hiển thị list / báo cáo cũ
		if not (self.title_vn or "").strip():
			self.title_vn = self.physical_code or ""
		if not (self.title_en or "").strip():
			self.title_en = self.title_vn
		if not (self.short_title or "").strip():
			self.short_title = self.physical_code or self.title_vn or ""

	def validate_physical_code_unique_per_campus(self):
		if not self.campus_id or not self.physical_code:
			return
		existing = frappe.db.sql(
			"""
			SELECT name FROM `tabERP Administrative Room`
			WHERE campus_id = %s AND physical_code = %s AND name != %s
			LIMIT 1
			""",
			(self.campus_id, self.physical_code, self.name or ""),
		)
		if existing:
			frappe.throw(
				_("Đã tồn tại phòng với mã vật lý {0} trên campus này.").format(self.physical_code)
			)

	def validate_capacity(self):
		if self.capacity and self.capacity <= 0:
			frappe.throw(_("Capacity must be a positive number"))

	def before_save(self):
		if self.building_id and not self.campus_id:
			self.campus_id = frappe.db.get_value(
				"ERP Administrative Building", self.building_id, "campus_id"
			)

	def on_update(self):
		try:
			self.create_activity_log("update", f"Room {self.physical_code or self.name} information updated")
		except Exception:
			pass

	def create_activity_log(self, activity_type, description, details=None):
		try:
			frappe.log_error(
				title=f"Room Activity: {activity_type}",
				message=f"{description} - Room: {self.physical_code or self.title_vn}",
				reference_doctype=self.doctype,
				reference_name=self.name,
			)
		except Exception as e:
			frappe.log_error(f"Failed to create activity log: {str(e)}")

	@frappe.whitelist()
	def get_devices_by_room(self):
		devices = {
			"laptops": [],
			"monitors": [],
			"projectors": [],
			"printers": [],
			"tools": [],
			"phones": [],
		}
		return {
			"room_id": self.name,
			"title_vn": self.title_vn,
			"title_en": self.title_en,
			"physical_code": self.physical_code,
			"building_id": self.building_id,
			"devices": devices,
		}

	@frappe.whitelist()
	def get_room_utilization(self):
		return {
			"room_id": self.name,
			"title_vn": self.title_vn,
			"physical_code": self.physical_code,
			"capacity": self.capacity,
			"utilization_percentage": 0,
		}
