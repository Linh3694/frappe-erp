# Copyright (c) 2026, Wellspring International School and contributors
# For license information, please see license.txt

import re

import frappe
from frappe import _
from frappe.model.document import Document

# Mặc định khi danh mục không khai báo prefix (tương thích HC-TKT-{#####} cũ)
DEFAULT_TICKET_PREFIX = "HC-TKT"


def _normalize_ticket_prefix(raw):
	if not raw:
		return DEFAULT_TICKET_PREFIX
	s = str(raw).strip().upper()
	if not re.match(r"^[A-Z0-9]{2,32}$", s):
		return DEFAULT_TICKET_PREFIX
	return s


def _next_ticket_name_for_prefix(prefix: str) -> str:
	"""Sinh mã PREFIX-NNNN (4 chữ số, tăng theo max hiện có cùng prefix)."""
	pat = re.compile(rf"^{re.escape(prefix)}-(\d+)$")
	names = frappe.get_all(
		"ERP Administrative Ticket",
		filters={"name": ["like", f"{prefix}-%"]},
		pluck="name",
	)
	max_n = 0
	for n in names:
		m = pat.match(n)
		if m:
			max_n = max(max_n, int(m.group(1)))
	return f"{prefix}-{max_n + 1:04d}"


class ERPAdministrativeTicket(Document):
	# Yêu cầu hỗ trợ Hành chính — mã theo Prefix danh mục (KT-0001) hoặc HC-TKT-0001

	def autoname(self):
		if not self.category:
			frappe.throw(_("Chọn danh mục"))
		raw_prefix = frappe.db.get_value(
			"ERP Administrative Support Category",
			self.category,
			"ticket_code_prefix",
		)
		prefix = _normalize_ticket_prefix(raw_prefix)
		self.name = _next_ticket_name_for_prefix(prefix)
		self.ticket_code = self.name

	def validate(self):
		if self.name:
			self.ticket_code = self.name
