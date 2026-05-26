# Copyright (c) 2026, Wellspring International School and contributors
# Ticket IT Support — mã theo prefix danh mục (OVR-0001, CAM-0002, ...)

import re

import frappe
from frappe import _
from frappe.model.document import Document

DEFAULT_TICKET_PREFIX = "IT"

FEEDBACK_BADGES = (
	"Nhiệt Huyết",
	"Chu Đáo",
	"Vui Vẻ",
	"Tận Tình",
	"Chuyên Nghiệp",
)


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
		"ERP IT Support Ticket",
		filters={"name": ["like", f"{prefix}-%"]},
		pluck="name",
	)
	max_n = 0
	for n in names:
		m = pat.match(n)
		if m:
			max_n = max(max_n, int(m.group(1)))
	return f"{prefix}-{max_n + 1:04d}"


class ERPITSupportTicket(Document):
	def autoname(self):
		# Cho phép migrate giữ ticketCode cũ (name đã set trước insert)
		if self.name and self.name != "New ERP IT Support Ticket":
			self.ticket_code = self.name
			return
		if not self.category:
			frappe.throw(_("Chọn danh mục"))
		raw_prefix = frappe.db.get_value(
			"ERP IT Support Category",
			self.category,
			"ticket_code_prefix",
		)
		prefix = _normalize_ticket_prefix(raw_prefix)
		self.name = _next_ticket_name_for_prefix(prefix)
		self.ticket_code = self.name

	def validate(self):
		if self.name:
			self.ticket_code = self.name
		if self.feedback_rating and (self.feedback_rating < 1 or self.feedback_rating > 5):
			frappe.throw(_("Điểm đánh giá phải từ 1 đến 5"))
