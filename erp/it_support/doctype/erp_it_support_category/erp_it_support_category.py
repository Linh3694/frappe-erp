# Copyright (c) 2026, Wellspring International School and contributors
# Danh mục ticket IT Support — prefix mã + role auto-assign

import re

import frappe
from frappe import _
from frappe.model.document import Document


class ERPITSupportCategory(Document):
	def validate(self):
		raw = (self.ticket_code_prefix or "").strip()
		if not raw:
			frappe.throw(_("Prefix mã ticket là bắt buộc"))
		p = raw.upper()
		if not re.match(r"^[A-Z0-9]{2,32}$", p):
			frappe.throw(_("Prefix chỉ gồm chữ và số (A–Z, 0–9), độ dài 2–32 ký tự"))
		self.ticket_code_prefix = p
		dup = frappe.db.exists(
			"ERP IT Support Category",
			{"ticket_code_prefix": p, "name": ["!=", self.name]},
		)
		if dup:
			frappe.throw(_("Prefix «{0}» đã được dùng cho danh mục khác").format(p))

		sr = (self.support_role or "").strip()
		if not sr:
			frappe.throw(_("Support role là bắt buộc"))
		self.support_role = sr

		seen = set()
		for row in self.get("team_leaders") or []:
			uid = (row.user or "").strip()
			if not uid:
				continue
			if uid in seen:
				frappe.throw(_("Không trùng Team Leader trong cùng danh mục"))
			seen.add(uid)
			roles = frappe.get_roles(uid) or []
			if "SIS IT" not in roles and "System Manager" not in roles:
				frappe.throw(_("Team Leader {0} phải có role SIS IT hoặc System Manager").format(uid))
