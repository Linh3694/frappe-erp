# Copyright (c) 2026, Wellspring International School
import frappe
from frappe import _
from frappe.model.document import Document

VALID_STATUSES = ("Active", "Standby", "Broken", "PendingDocumentation")
VALID_DEVICE_TYPES = ("laptop", "monitor", "printer", "projector", "phone", "tool")


class ERPInventoryDevice(Document):
	def validate(self):
		if self.device_type not in VALID_DEVICE_TYPES:
			frappe.throw(_("Loại thiết bị không hợp lệ"))
		if self.status not in VALID_STATUSES:
			frappe.throw(_("Trạng thái không hợp lệ"))
		if not (self.serial or "").strip():
			frappe.throw(_("Serial là bắt buộc"))
		self._validate_unique_serial()
		if self.device_type == "phone" and self.specs_phone:
			for row in self.specs_phone:
				if not (row.imei1 or "").strip():
					frappe.throw(_("IMEI 1 là bắt buộc cho điện thoại"))

	def _validate_unique_serial(self):
		existing = frappe.db.get_value(
			"ERP Inventory Device",
			{"serial": self.serial, "device_type": self.device_type, "name": ["!=", self.name or ""]},
			"name",
		)
		if existing:
			frappe.throw(_("Serial {0} đã tồn tại cho loại {1}").format(self.serial, self.device_type))
