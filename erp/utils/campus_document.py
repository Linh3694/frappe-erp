"""
Hook before_insert: tự gán campus_id từ context nếu DocType có field và chưa set.
"""

from __future__ import annotations

import frappe

from erp.utils.campus_utils import get_current_campus_from_context


def inject_campus_id(doc, method=None):
	"""Gán campus_id mặc định khi tạo document mới."""
	if doc.get("__islocal") is False:
		return

	meta = frappe.get_meta(doc.doctype)
	if not meta.get_field("campus_id"):
		return

	if doc.get("campus_id"):
		return

	campus_id = get_current_campus_from_context()
	if campus_id:
		doc.campus_id = campus_id
