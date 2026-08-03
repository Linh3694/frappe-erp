# Copyright (c) 2026, Dinox Technologies and contributors
# For license information, please see license.txt

import re

import frappe
from frappe import _
from frappe.model.document import Document

HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


class ERPBrandingSettings(Document):
	def validate(self):
		for field in ("color_primary", "color_secondary", "color_on_primary"):
			value = (self.get(field) or "").strip()
			if value and not HEX_RE.match(value):
				frappe.throw(_("Trường {0} phải là mã màu hex hợp lệ, ví dụ #F05023").format(field))
			self.set(field, value.upper() if value else value)

		if self.seasonal_from and self.seasonal_to and self.seasonal_from > self.seasonal_to:
			frappe.throw(_("Ngày bắt đầu theme phải trước ngày kết thúc"))

	def on_update(self):
		from erp.api.erp_common_system.config import clear_bootstrap_cache

		clear_bootstrap_cache()
