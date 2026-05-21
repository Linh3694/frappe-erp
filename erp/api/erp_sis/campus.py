import frappe
from frappe import _

from erp.utils.api_response import error_response, list_response, single_item_response, success_response
from erp.utils.campus_utils import get_all_campus_ids_from_user_roles
from erp.sis.utils.campus_permissions import (
	assign_campus_role_to_user,
	get_current_user_campus,
	get_user_campuses,
	remove_campus_role_from_user,
	set_current_user_campus,
)


def _resolve_user_from_jwt() -> str | None:
	try:
		auth_header = frappe.get_request_header("Authorization") or ""
		token = None
		if auth_header.lower().startswith("bearer "):
			token = auth_header.split(" ", 1)[1].strip()
		if token:
			from erp.api.erp_common_user.auth import verify_jwt_token

			payload = verify_jwt_token(token)
			if payload:
				user_email = payload.get("email") or payload.get("user") or payload.get("sub")
				if user_email and frappe.db.exists("User", user_email):
					return user_email
	except Exception:
		pass
	return None


def _resolve_request_user() -> str:
	user = frappe.session.user
	jwt_user = _resolve_user_from_jwt()
	if jwt_user:
		user = jwt_user
	return user


def _campus_row(campus_doc) -> dict:
	return {
		"name": campus_doc.name,
		"title_vn": campus_doc.title_vn,
		"title_en": campus_doc.title_en,
		"short_title": campus_doc.short_title,
	}


def _get_accessible_campus_rows(user: str | None = None) -> list[dict]:
	"""Lấy danh sách campus user được truy cập, kèm short_title."""
	if not user:
		user = _resolve_request_user()

	user_campuses = get_user_campuses(user)
	if not user_campuses:
		return []

	return frappe.get_all(
		"SIS Campus",
		filters={"name": ["in", user_campuses]},
		fields=["name", "title_vn", "title_en", "short_title"],
		order_by="title_vn asc",
	)


@frappe.whitelist(allow_guest=False)
def get_accessible_campuses():
	"""Campus user được truy cập — endpoint chính cho frontend SIS."""
	try:
		rows = _get_accessible_campus_rows()
		return list_response(rows, "Accessible campuses fetched successfully")
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "Get Accessible Campuses Error")
		return error_response(_("Error getting accessible campuses: {0}").format(str(e)))


@frappe.whitelist(allow_guest=False)
def get_campuses(only_user: bool = True):
	"""Return list of campuses user can access (or all if only_user=False)."""
	try:
		user = _resolve_request_user()

		if only_user:
			rows = _get_accessible_campus_rows(user)
			if rows:
				return list_response(rows, "Campuses fetched successfully")

			# Fallback: build from roles if campus docs not found
			campus_ids = get_all_campus_ids_from_user_roles(user) or []
			try:
				role_list = frappe.get_roles(user) or []
			except Exception:
				role_list = []
			campus_titles = [
				r.replace("Campus ", "").strip()
				for r in role_list
				if isinstance(r, str) and r.startswith("Campus ")
			]

			if not campus_ids:
				campus_ids = [f"campus-{i + 1}" for i in range(len(campus_titles))]

			n = max(len(campus_ids), len(campus_titles))
			fallback_rows = []
			for i in range(n):
				cid = campus_ids[i] if i < len(campus_ids) else f"campus-{i + 1}"
				title = campus_titles[i] if i < len(campus_titles) else cid
				fallback_rows.append({
					"name": cid,
					"title_vn": title,
					"title_en": title,
					"short_title": title,
				})

			return list_response(fallback_rows, "Campuses fetched successfully")

		rows = frappe.get_all(
			"SIS Campus",
			fields=["name", "title_vn", "title_en", "short_title"],
			order_by="title_vn asc",
		)
		return list_response(rows or [], "Campuses fetched successfully")
	except Exception as e:
		return error_response(f"Error fetching campuses: {str(e)}")


@frappe.whitelist(allow_guest=False)
def get_current_campus():
	"""Campus đang chọn của user hiện tại."""
	try:
		current_campus = get_current_user_campus()
		if not current_campus:
			return single_item_response(None, "No current campus selected")

		campus_doc = frappe.get_doc("SIS Campus", current_campus)
		return single_item_response(_campus_row(campus_doc), "Current campus fetched successfully")
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "Get Current Campus Error")
		return error_response(_("Error getting current campus: {0}").format(str(e)))


@frappe.whitelist(allow_guest=False)
def set_current_campus(campus):
	"""Đặt campus hiện tại cho user."""
	try:
		if set_current_user_campus(campus):
			campus_doc = frappe.get_doc("SIS Campus", campus)
			return success_response(
				data={
					"message": f"Đã chuyển sang campus: {campus_doc.title_vn}",
					"campus": _campus_row(campus_doc),
				},
				message=f"Đã chuyển sang campus: {campus_doc.title_vn}",
			)
		return error_response(_("Failed to set current campus"))
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "Set Current Campus Error")
		return error_response(_("Error setting current campus: {0}").format(str(e)))


@frappe.whitelist(allow_guest=False)
def assign_campus_access(user, campus, role_type="staff"):
	"""Gán quyền truy cập campus cho user."""
	try:
		if not frappe.has_permission("SIS Campus", "write"):
			frappe.throw(_("You don't have permission to manage campus access"))

		assign_campus_role_to_user(user, campus, role_type)
		return success_response(
			message=f"Đã gán quyền truy cập campus {campus} cho user {user}",
		)
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "Assign Campus Access Error")
		return error_response(_("Error assigning campus access: {0}").format(str(e)))


@frappe.whitelist(allow_guest=False)
def remove_campus_access(user, campus):
	"""Xóa quyền truy cập campus khỏi user."""
	try:
		if not frappe.has_permission("SIS Campus", "write"):
			frappe.throw(_("You don't have permission to manage campus access"))

		remove_campus_role_from_user(user, campus)
		return success_response(
			message=f"Đã xóa quyền truy cập campus {campus} khỏi user {user}",
		)
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "Remove Campus Access Error")
		return error_response(_("Error removing campus access: {0}").format(str(e)))


@frappe.whitelist(allow_guest=False)
def get_campus_users(campus):
	"""Danh sách user có quyền truy cập campus."""
	try:
		if not frappe.has_permission("SIS Campus", "read"):
			frappe.throw(_("You don't have permission to view campus users"))

		campus_doc = frappe.get_doc("SIS Campus", campus)
		role_name = campus_doc.get_campus_role_name()

		users = frappe.get_all(
			"Has Role",
			filters={"role": role_name},
			fields=["parent as user"],
		)
		user_list = [u.user for u in users]

		if user_list:
			user_details = frappe.get_all(
				"User",
				filters={"name": ["in", user_list], "enabled": 1},
				fields=["name", "full_name", "email"],
			)
			return list_response(user_details, "Campus users fetched successfully")

		return list_response([], "Campus users fetched successfully")
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "Get Campus Users Error")
		return error_response(_("Error getting campus users: {0}").format(str(e)))
