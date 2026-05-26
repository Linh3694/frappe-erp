# Copyright (c) 2026, Wellspring International School and contributors
# API đội hỗ trợ IT

from __future__ import annotations

import json

import frappe
from frappe import _

from erp.api.erp_it_support.utils import (
	SUPPORT_ROLES,
	TEAM_DOCTYPE,
	_is_it_staff,
	_parse_json_body,
	_parse_json_field,
	_team_member_to_dict,
	get_available_roles_list,
)
from erp.utils.api_response import (
	error_response,
	forbidden_response,
	not_found_response,
	success_response,
	validation_error_response,
)


def _require_it_staff():
	if not _is_it_staff():
		frappe.throw(_("Chỉ đội IT mới thực hiện thao tác này"), frappe.PermissionError)


@frappe.whitelist(allow_guest=False)
def get_all_team_members(role=None, search=None):
	try:
		_require_it_staff()
		role = (role or frappe.form_dict.get("role") or "").strip()
		search = (search or frappe.form_dict.get("search") or "").strip().lower()

		rows = frappe.get_all(
			TEAM_DOCTYPE,
			filters={"is_active": 1},
			fields=[
				"name",
				"user",
				"email",
				"full_name",
				"avatar_url",
				"department",
				"roles_json",
				"is_active",
				"total_tickets",
				"resolved_tickets",
				"average_rating",
				"notes",
				"creation",
				"modified",
			],
			order_by="full_name asc",
		)
		members = []
		for r in rows:
			roles = _parse_json_field(r.get("roles_json"))
			if role and role not in roles:
				continue
			doc = frappe.get_doc(TEAM_DOCTYPE, r.name)
			m = _team_member_to_dict(doc)
			if search:
				hay = f"{m.get('fullname','')} {m.get('email','')}".lower()
				if search not in hay:
					continue
			members.append(m)
		return success_response({"members": members, "total": len(members)}, "OK")
	except frappe.PermissionError as e:
		return forbidden_response(str(e))
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "it_support.get_all_team_members")
		return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def get_team_member(user=None, user_id=None):
	try:
		uid = user or user_id or frappe.form_dict.get("user") or frappe.form_dict.get("user_id")
		if not uid:
			return validation_error_response(_("Thiếu userId"))
		name = uid
		if not frappe.db.exists(TEAM_DOCTYPE, uid):
			name = frappe.db.get_value(TEAM_DOCTYPE, {"user": uid}, "name")
		if not name:
			return not_found_response(_("Không tìm thấy thành viên"))
		doc = frappe.get_doc(TEAM_DOCTYPE, name)
		return success_response({"member": _team_member_to_dict(doc)}, "OK")
	except Exception as e:
		return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def get_available_roles():
	try:
		return success_response({"roles": get_available_roles_list()}, "OK")
	except Exception as e:
		return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def create_or_update_team_member():
	try:
		_require_it_staff()
		data = _parse_json_body()
		user_id = (data.get("userId") or data.get("user") or "").strip()
		if not user_id or not frappe.db.exists("User", user_id):
			return validation_error_response(_("User không hợp lệ"))
		roles = data.get("roles") or []
		if isinstance(roles, str):
			try:
				roles = json.loads(roles)
			except Exception:
				roles = [roles]
		invalid = [r for r in roles if r not in SUPPORT_ROLES]
		if invalid:
			return validation_error_response(_("Role không hợp lệ: {0}").format(", ".join(invalid)))

		existing = frappe.db.get_value(TEAM_DOCTYPE, {"user": user_id}, "name")
		if existing:
			doc = frappe.get_doc(TEAM_DOCTYPE, existing)
			doc.roles_json = json.dumps(roles, separators=(",", ":"))
			doc.notes = (data.get("notes") or doc.notes or "").strip()
			doc.is_active = 1
			doc.save(ignore_permissions=True)
		else:
			doc = frappe.get_doc(
				{
					"doctype": TEAM_DOCTYPE,
					"user": user_id,
					"roles_json": json.dumps(roles, separators=(",", ":")),
					"notes": (data.get("notes") or "").strip(),
					"is_active": 1,
				}
			)
			doc.insert(ignore_permissions=True)
		frappe.db.commit()
		return success_response({"member": _team_member_to_dict(doc)}, "OK")
	except frappe.PermissionError as e:
		return forbidden_response(str(e))
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "it_support.create_or_update_team_member")
		return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def update_team_member_roles():
	try:
		_require_it_staff()
		data = _parse_json_body()
		user_id = (data.get("userId") or data.get("user") or "").strip()
		roles = data.get("roles") or []
		name = frappe.db.get_value(TEAM_DOCTYPE, {"user": user_id}, "name")
		if not name:
			return not_found_response(_("Không tìm thấy thành viên"))
		doc = frappe.get_doc(TEAM_DOCTYPE, name)
		doc.roles_json = json.dumps(roles, separators=(",", ":"))
		doc.save(ignore_permissions=True)
		frappe.db.commit()
		return success_response({"member": _team_member_to_dict(doc)}, "OK")
	except frappe.PermissionError as e:
		return forbidden_response(str(e))
	except Exception as e:
		return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def delete_team_member(user=None, user_id=None):
	try:
		_require_it_staff()
		uid = user or user_id or frappe.form_dict.get("user") or frappe.form_dict.get("user_id")
		name = frappe.db.get_value(TEAM_DOCTYPE, {"user": uid}, "name") or uid
		if not frappe.db.exists(TEAM_DOCTYPE, name):
			return not_found_response(_("Không tìm thấy thành viên"))
		frappe.delete_doc(TEAM_DOCTYPE, name, ignore_permissions=True)
		frappe.db.commit()
		return success_response({"success": True}, "OK")
	except frappe.PermissionError as e:
		return forbidden_response(str(e))
	except Exception as e:
		return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def get_members_by_role(role=None):
	try:
		role = (role or frappe.form_dict.get("role") or "").strip()
		if not role:
			return validation_error_response(_("Thiếu role"))
		resp = get_all_team_members(role=role)
		if not resp.get("success"):
			return resp
		return success_response({"members": resp.get("data", {}).get("members", [])}, "OK")
	except Exception as e:
		return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def update_member_stats(user=None, stats=None):
	"""Cập nhật thống kê thành viên (tùy chọn — thường tính runtime)."""
	try:
		_require_it_staff()
		data = _parse_json_body()
		uid = user or data.get("user") or data.get("userId")
		stats = stats or data.get("stats") or {}
		if isinstance(stats, str):
			stats = json.loads(stats)
		name = frappe.db.get_value(TEAM_DOCTYPE, {"user": uid}, "name")
		if not name:
			return not_found_response(_("Không tìm thấy thành viên"))
		doc = frappe.get_doc(TEAM_DOCTYPE, name)
		if "totalTickets" in stats:
			doc.total_tickets = int(stats["totalTickets"])
		if "resolvedTickets" in stats:
			doc.resolved_tickets = int(stats["resolvedTickets"])
		if "averageRating" in stats:
			doc.average_rating = float(stats["averageRating"])
		doc.save(ignore_permissions=True)
		frappe.db.commit()
		return success_response({"member": _team_member_to_dict(doc)}, "OK")
	except frappe.PermissionError as e:
		return forbidden_response(str(e))
	except Exception as e:
		return error_response(str(e))
