# Copyright (c) 2026, Dinox Technologies and contributors
# For license information, please see license.txt

import json

import frappe
from frappe import _
from frappe.model.document import Document


class ERPFeatureSettings(Document):
	def validate(self):
		self._validate_campus_overrides()
		self._validate_pp_modules()

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

	# ------------------------------------------------------------------
	# Hiển thị module Parent Portal
	# ------------------------------------------------------------------
	PP_STATES = ("on", "off", "beta")
	PP_PLATFORMS = ("web", "mobile")
	#: Khoá dùng được ở cả nền chung lẫn trong `platforms.<nền>`
	PP_RULE_KEYS = ("state", "phones", "campuses", "min_app_version")

	def _validate_pp_modules(self):
		"""pp_modules_json phải là {module_key: {state, phones, campuses, platforms}}.

		Chặn ngay lúc lưu thay vì để lỗi phát sinh lúc đọc: sai định dạng ở đây
		làm menu của toàn bộ phụ huynh hiển thị sai.
		"""
		data = self._parse_json_field(
			self.pp_modules_json,
			_("Module Parent Portal phải là JSON hợp lệ"),
		)
		if data is None:
			return

		if not isinstance(data, dict):
			frappe.throw(_("Module Parent Portal phải là object dạng {module_key: {...}}"))

		for module_key, cfg in data.items():
			if not isinstance(cfg, dict):
				frappe.throw(
					_("Module {0}: cấu hình phải là object dạng {{state, phones, campuses}}").format(
						module_key
					)
				)

			platforms = cfg.get("platforms")
			self._validate_pp_rule(module_key, None, cfg)

			if platforms is None:
				continue
			if not isinstance(platforms, dict):
				frappe.throw(
					_("Module {0}: `platforms` phải là object dạng {{web|mobile: {{...}}}}").format(
						module_key
					)
				)
			for platform, override in platforms.items():
				if platform not in self.PP_PLATFORMS:
					frappe.throw(
						_("Module {0}: nền tảng {1} không hợp lệ (chỉ có web, mobile)").format(
							module_key, platform
						)
					)
				if not isinstance(override, dict):
					frappe.throw(
						_("Module {0}, nền tảng {1}: ghi đè phải là object").format(module_key, platform)
					)
				if "platforms" in override:
					frappe.throw(
						_("Module {0}, nền tảng {1}: không lồng `platforms` bên trong ghi đè").format(
							module_key, platform
						)
					)
				# Ghi đè merge CẠN lên nền chung, nên phải kiểm tra kết quả ĐÃ MERGE:
				# `platforms.mobile = {"state": "beta"}` thừa hưởng `phones` của nền chung.
				self._validate_pp_rule(module_key, platform, {**cfg, **override})

	def _validate_pp_rule(self, module_key, platform, rule):
		where = (
			_("Module {0}").format(module_key)
			if platform is None
			else _("Module {0}, nền tảng {1}").format(module_key, platform)
		)

		for key in rule:
			if key not in self.PP_RULE_KEYS and key != "platforms":
				frappe.throw(_("{0}: không có thuộc tính nào tên {1}").format(where, key))

		state = rule.get("state", "on")
		if state not in self.PP_STATES:
			frappe.throw(
				_("{0}: state phải là một trong {1}").format(where, ", ".join(self.PP_STATES))
			)

		phones = self._validate_pp_str_list(where, "phones", rule.get("phones"))
		campuses = self._validate_pp_str_list(where, "campuses", rule.get("campuses"))

		min_version = rule.get("min_app_version")
		if min_version is not None and not isinstance(min_version, str):
			frappe.throw(_("{0}: min_app_version phải là chuỗi, ví dụ \"1.0.19\"").format(where))

		# `beta` mà không ai lọt whitelist thì tắt với TẤT CẢ — đúng ngược với quy
		# ước "danh sách rỗng = mở cho tất cả" của club_beta_access.py. Bắt khai
		# `off` cho rõ ràng thay vì để cấu hình trông như đang chạy thử.
		if state == "beta" and not phones and not campuses:
			frappe.throw(
				_(
					"{0}: state=beta nhưng whitelist rỗng nên sẽ ẩn với TẤT CẢ phụ huynh. "
					"Thêm phones/campuses, hoặc dùng state=off nếu thực sự muốn tắt hẳn."
				).format(where)
			)

	def _validate_pp_str_list(self, where, field, value):
		if value is None:
			return []
		if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
			frappe.throw(_("{0}: {1} phải là mảng chuỗi").format(where, field))
		return [x for x in value if x.strip()]

	@staticmethod
	def _parse_json_field(raw, error_message):
		"""Trả dict/list đã parse, hoặc None khi field để trống."""
		if not raw:
			return None
		if isinstance(raw, str):
			raw = raw.strip()
			if not raw:
				return None
			try:
				return json.loads(raw)
			except ValueError:
				frappe.throw(error_message)
		return raw

	def on_update(self):
		from erp.api.erp_common_system.config import clear_bootstrap_cache
		from erp.api.parent_portal.module_access import clear_module_config_cache

		clear_bootstrap_cache()
		clear_module_config_cache()
