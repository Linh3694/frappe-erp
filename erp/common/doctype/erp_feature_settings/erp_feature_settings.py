# Copyright (c) 2026, Dinox Technologies and contributors
# For license information, please see license.txt

import json

import frappe
from frappe import _
from frappe.model.document import Document


class ERPFeatureSettings(Document):
	def validate(self):
		self._validate_campus_overrides()

	def _validate_campus_overrides(self):
		"""campus_overrides_json phải là object {campus_id: {feat_x: bool}}.

		Sai định dạng ở đây sẽ làm API bootstrap trả sai cho toàn bộ client,
		nên chặn ngay lúc lưu thay vì để lỗi phát sinh lúc đọc.
		"""
		raw = self.campus_overrides_json
		if not raw:
			return

		if isinstance(raw, str):
			raw = raw.strip()
			if not raw:
				return
			try:
				data = json.loads(raw)
			except ValueError:
				frappe.throw(_("Ghi đè theo campus phải là JSON hợp lệ"))
		else:
			data = raw

		if not isinstance(data, dict):
			frappe.throw(_("Ghi đè theo campus phải là object dạng {campus_id: {feat_x: true/false}}"))

		valid_fields = {f.fieldname for f in self.meta.fields if f.fieldname.startswith("feat_")}
		for campus_id, overrides in data.items():
			if not isinstance(overrides, dict):
				frappe.throw(
					_("Ghi đè của campus {0} phải là object dạng {{feat_x: true/false}}").format(campus_id)
				)
			for key, value in overrides.items():
				if key not in valid_fields:
					frappe.throw(
						_("Campus {0}: không có cờ tính năng nào tên {1}").format(campus_id, key)
					)
				if not isinstance(value, bool):
					frappe.throw(
						_("Campus {0}, cờ {1}: giá trị phải là true hoặc false").format(campus_id, key)
					)

	def on_update(self):
		from erp.api.erp_common_system.config import clear_bootstrap_cache

		clear_bootstrap_cache()
