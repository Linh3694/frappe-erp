# Copyright (c) 2026, Wellspring International School and contributors
# Thành viên đội hỗ trợ IT — roles theo hạng mục ticket

import json

import frappe
from frappe import _
from frappe.model.document import Document

# Role hỗ trợ — khớp ticket-service Node.js
SUPPORT_ROLES = (
	"Overall",
	"Account",
	"Camera System",
	"Network System",
	"Bell System",
	"Software",
	"Email Ticket",
)


class ERPITSupportTeamMember(Document):
	def validate(self):
		roles = _normalize_roles_json(self.roles_json)
		if not roles:
			frappe.throw(_("Phải chọn ít nhất một role hỗ trợ"))
		invalid = [r for r in roles if r not in SUPPORT_ROLES]
		if invalid:
			frappe.throw(_("Role không hợp lệ: {0}").format(", ".join(invalid)))
		self.roles_json = json.dumps(roles, separators=(",", ":"))


def _normalize_roles_json(raw):
	if raw is None:
		return []
	if isinstance(raw, list):
		return [str(x).strip() for x in raw if x]
	if isinstance(raw, str):
		try:
			parsed = json.loads(raw)
			if isinstance(parsed, list):
				return [str(x).strip() for x in parsed if x]
		except Exception:
			pass
	return []
