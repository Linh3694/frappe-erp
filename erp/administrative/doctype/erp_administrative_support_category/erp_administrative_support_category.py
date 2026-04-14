# Copyright (c) 2026, Wellspring International School and contributors
# For license information, please see license.txt

import re

import frappe
from frappe import _
from frappe.model.document import Document


class ERPAdministrativeSupportCategory(Document):
	# Danh mục hỗ trợ CSVC — có Prefix để sinh mã ticket (VD: KT → KT-0001)

	def validate(self):
		raw = (self.ticket_code_prefix or "").strip()
		if not raw:
			self.ticket_code_prefix = None
		else:
			p = raw.upper()
			if not re.match(r"^[A-Z0-9]{2,32}$", p):
				frappe.throw(_("Prefix chỉ gồm chữ và số (A–Z, 0–9), độ dài 2–32 ký tự"))
			self.ticket_code_prefix = p
			dup = frappe.db.exists(
				"ERP Administrative Support Category",
				{"ticket_code_prefix": p, "name": ["!=", self.name]},
			)
			if dup:
				frappe.throw(_("Prefix «{0}» đã được dùng cho danh mục khác").format(p))

		seen = set()
		for row in self.get("team_leaders") or []:
			uid = (row.user or "").strip()
			if not uid:
				continue
			if uid in seen:
				frappe.throw(_("Không trùng Team Leader trong cùng danh mục"))
			seen.add(uid)
			roles = frappe.get_roles(uid) or []
			if "SIS Administrative" not in roles:
				frappe.throw(
					_("Team Leader {0} phải có role SIS Administrative").format(uid)
				)
