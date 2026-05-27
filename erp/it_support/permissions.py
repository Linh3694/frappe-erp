# Copyright (c) 2026, Wellspring International School and contributors
# Phân quyền DocType ticket IT — creator / assigned / staff IT

import frappe

_STAFF_ROLES = ("System Manager", "SIS IT", "SIS BOD")


def it_support_ticket_query(user):
	"""Lọc ticket: staff theo campus; user thường chỉ ticket của mình (cùng campus)."""
	if not user:
		user = frappe.session.user
	if user == "Administrator":
		return ""

	from erp.sis.utils.permission_query import get_campus_permission_query

	campus_filter = get_campus_permission_query("ERP IT Support Ticket", user)
	roles = frappe.get_roles(user) or []

	if any(r in roles for r in _STAFF_ROLES):
		return campus_filter

	email = frappe.db.get_value("User", user, "email") or ""
	conds = [f"`tabERP IT Support Ticket`.assigned_to = {frappe.db.escape(user)}"]
	if email:
		conds.append(f"`tabERP IT Support Ticket`.creator_email = {frappe.db.escape(email)}")
	user_cond = f"({' OR '.join(conds)})"
	if campus_filter:
		return f"({user_cond}) AND ({campus_filter})"
	return user_cond


def has_it_support_ticket_permission(doc, ptype, user):
	if not user:
		user = frappe.session.user
	if user == "Administrator":
		return True
	roles = frappe.get_roles(user) or []
	# Xóa ticket: staff IT — không lọc campus (System Manager thường quản trị đa campus)
	if ptype == "delete":
		return any(r in roles for r in _STAFF_ROLES)
	if any(r in roles for r in _STAFF_ROLES):
		# Staff vẫn phải thuộc campus của ticket
		doc_campus = getattr(doc, "campus_id", None)
		if doc_campus:
			from erp.utils.campus_utils import get_active_campus_id

			active = get_active_campus_id(user)
			if active:
				return doc_campus == active
			from erp.sis.utils.campus_permissions import get_user_campuses

			if doc_campus not in (get_user_campuses(user) or []):
				return False
		return True
	email = (frappe.db.get_value("User", user, "email") or "").strip()
	if ptype in ("read", "write", "create"):
		if doc.creator_email and doc.creator_email == email:
			return True
		if doc.assigned_to == user:
			return True
	return False
