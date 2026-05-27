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


def _resolve_str_param(name: str, value=None) -> str | None:
	"""Đọc tham số string từ argument, form_dict, query, form hoặc body (JSON/urlencoded)."""
	if value not in (None, ""):
		return str(value).strip() or None

	candidates: list = []

	def _append(val):
		if val is None:
			return
		if isinstance(val, (list, tuple)):
			for item in val:
				_append(item)
			return
		text = str(val).strip()
		if text:
			candidates.append(text)

	try:
		_append(frappe.form_dict.get(name))
	except Exception:
		pass

	try:
		if frappe.local and getattr(frappe.local, "form_dict", None):
			_append(frappe.local.form_dict.get(name))
	except Exception:
		pass

	try:
		req = getattr(frappe.local, "request", None) or frappe.request
		if req:
			if getattr(req, "args", None):
				_append(req.args.get(name))
			if getattr(req, "form", None):
				_append(req.form.get(name))
	except Exception:
		pass

	try:
		req = getattr(frappe.local, "request", None) or frappe.request
		if req and req.data:
			raw_body = req.data
			if isinstance(raw_body, bytes):
				raw_body = raw_body.decode("utf-8")
			raw_body = (raw_body or "").strip()
			if raw_body.startswith("{"):
				import json
				_append(json.loads(raw_body).get(name))
			elif "=" in raw_body:
				from urllib.parse import parse_qs
				parsed = parse_qs(raw_body, keep_blank_values=False)
				_append(parsed.get(name))
	except Exception:
		pass

	return candidates[0] if candidates else None


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

		if "System Manager" not in frappe.get_roles(user):
			frappe.throw(_("Only System Manager can list all campuses"))

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
def set_current_campus(campus=None):
	"""Đặt campus hiện tại cho user."""
	try:
		campus = _resolve_str_param("campus", campus)
		if not campus:
			return error_response(_("Campus is required"))

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
def set_default_campus(campus=None, user=None):
	"""Đặt campus mặc định cho user (admin quản lý user hoặc chính user đó)."""
	try:
		campus = _resolve_str_param("campus", campus)
		user = _resolve_str_param("user", user)
		if not campus:
			return error_response(_("Campus is required"))
		if not user:
			user = frappe.session.user

		if user != frappe.session.user and "System Manager" not in frappe.get_roles():
			frappe.throw(_("You don't have permission to set default campus for other users"))

		from erp.sis.doctype.sis_user_campus_preference.sis_user_campus_preference import (
			SISUserCampusPreference,
		)
		from erp.sis.utils.campus_permissions import get_user_campuses

		user_campuses = get_user_campuses(user)
		if campus not in user_campuses:
			frappe.throw(_("User {0} doesn't have access to campus {1}").format(user, campus))

		preference = SISUserCampusPreference.get_or_create_preference(user)
		preference.default_campus = campus
		if not preference.current_campus:
			preference.current_campus = campus
		preference.flags.ignore_permissions = True
		preference.save()

		campus_doc = frappe.get_doc("SIS Campus", campus)
		return success_response(
			data={"campus": _campus_row(campus_doc), "user": user},
			message=f"Đã đặt campus mặc định: {campus_doc.title_vn}",
		)
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "Set Default Campus Error")
		return error_response(_("Error setting default campus: {0}").format(str(e)))


@frappe.whitelist(allow_guest=False)
def get_user_campus_preference(user=None):
	"""Lấy campus preference của user (current + default)."""
	try:
		if not user:
			user = frappe.session.user
		if user != frappe.session.user and "System Manager" not in frappe.get_roles():
			frappe.throw(_("You don't have permission to view campus preference for other users"))

		from erp.sis.doctype.sis_user_campus_preference.sis_user_campus_preference import (
			SISUserCampusPreference,
		)

		preference = SISUserCampusPreference.get_or_create_preference(user)
		return success_response(
			data={
				"user": user,
				"current_campus": preference.current_campus,
				"default_campus": preference.default_campus,
			},
			message="User campus preference fetched",
		)
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "Get User Campus Preference Error")
		return error_response(_("Error getting user campus preference: {0}").format(str(e)))


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
