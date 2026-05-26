# Copyright (c) 2026, Wellspring International School and contributors
# Phân quyền DocType ticket IT — creator / assigned / staff IT

import frappe

_STAFF_ROLES = ("System Manager", "SIS IT", "SIS BOD")


def it_support_ticket_query(user):
	"""Lọc danh sách ticket: staff xem tất cả; user thường chỉ ticket của mình."""
	if not user:
		user = frappe.session.user
	if user == "Administrator":
		return ""
	roles = frappe.get_roles(user) or []
	if any(r in roles for r in _STAFF_ROLES):
		return ""
	email = frappe.db.get_value("User", user, "email") or ""
	conds = [f"`tabERP IT Support Ticket`.assigned_to = {frappe.db.escape(user)}"]
	if email:
		conds.append(f"`tabERP IT Support Ticket`.creator_email = {frappe.db.escape(email)}")
	return f"({' OR '.join(conds)})"


def has_it_support_ticket_permission(doc, ptype, user):
	if not user:
		user = frappe.session.user
	if user == "Administrator":
		return True
	roles = frappe.get_roles(user) or []
	if any(r in roles for r in _STAFF_ROLES):
		return True
	email = (frappe.db.get_value("User", user, "email") or "").strip()
	if ptype in ("read", "write", "create"):
		if doc.creator_email and doc.creator_email == email:
			return True
		if doc.assigned_to == user:
			return True
	return False
