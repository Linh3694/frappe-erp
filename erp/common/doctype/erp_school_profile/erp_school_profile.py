# Copyright (c) 2026, Dinox Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class ERPSchoolProfile(Document):
	def validate(self):
		self._normalize_domain()

	def _normalize_domain(self):
		"""Bỏ scheme/khoảng trắng, hạ chữ thường cho domain email định danh."""
		raw = (self.identity_email_domain or "").strip().lower()
		for prefix in ("https://", "http://"):
			if raw.startswith(prefix):
				raw = raw[len(prefix):]
		self.identity_email_domain = raw.strip("/@ ")

	def on_update(self):
		from erp.api.erp_common_system.config import clear_bootstrap_cache

		clear_bootstrap_cache()
