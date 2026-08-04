"""
API cấu hình giáo viên được đăng bài bảng tin lớp (SIS Class Newsfeed Poster).

- GVCN/phó và SIS Manager / System Manager quản lý danh sách.
- social-service gọi get_class_newsfeed_permissions để enforce khi tạo bài class.
"""

from __future__ import annotations

import json

import frappe
from frappe import _

from erp.api.erp_sis.chat_scope import _resolve_teacher_id_for_user, _resolve_subject_titles
from erp.api.parent_portal.journal import _teacher_snapshot_for_chat
from erp.utils.api_response import success_response, error_response


MANAGE_ROLES = ("System Manager", "SIS Manager")
READONLY_VIEW_ROLES = ("System Manager", "SIS BOD", "SIS Manager")


def _parse_payload():
	"""Gộp form_dict + JSON body (POST từ social-service / admin web)."""
	d = dict(frappe.form_dict or {})
	if getattr(frappe, "request", None) and frappe.request.data:
		try:
			raw = (
				frappe.request.data.decode("utf-8")
				if isinstance(frappe.request.data, bytes)
				else frappe.request.data
			)
			body = json.loads(raw)
			if isinstance(body, dict):
				d.update(body)
		except Exception:
			pass
	return d


def _user_has_any_role(roles):
	user_roles = set(frappe.get_roles(frappe.session.user) or [])
	return bool(user_roles.intersection(roles))


def _get_class(class_id):
	return frappe.db.get_value(
		"SIS Class",
		class_id,
		[
			"name",
			"title",
			"short_title",
			"campus_id",
			"school_year_id",
			"homeroom_teacher",
			"vice_homeroom_teacher",
		],
		as_dict=True,
	)


def _is_homeroom_of_class(cls, teacher_id):
	if not cls or not teacher_id:
		return False
	return teacher_id in {
		cls.get("homeroom_teacher"),
		cls.get("vice_homeroom_teacher"),
	}


def _can_manage_posters(cls, teacher_id=None):
	"""GVCN/phó lớp hoặc SIS Manager / System Manager."""
	if _user_has_any_role(MANAGE_ROLES):
		return True
	if teacher_id is None:
		teacher_id, _ = _resolve_teacher_id_for_user(frappe.session.user)
	return _is_homeroom_of_class(cls, teacher_id)


def _compute_my_access(cls, class_id, school_year_id):
	"""Tính access edit|readonly|none cho session hiện tại."""
	teacher_id, _ = _resolve_teacher_id_for_user(frappe.session.user)
	is_homeroom = _is_homeroom_of_class(cls, teacher_id)
	is_poster = False
	if teacher_id and not is_homeroom:
		is_poster = bool(
			frappe.db.exists(
				"SIS Class Newsfeed Poster",
				{
					"class_id": class_id,
					"school_year_id": school_year_id,
					"teacher_id": teacher_id,
				},
			)
		)
	can_manage = _can_manage_posters(cls, teacher_id=teacher_id)
	can_edit = is_homeroom or is_poster
	can_view_ro = (not can_edit) and _user_has_any_role(READONLY_VIEW_ROLES)
	if can_edit:
		access = "edit"
	elif can_view_ro:
		access = "readonly"
	else:
		access = "none"
	return {
		"access": access,
		"can_manage_posters": can_manage,
		"is_homeroom": is_homeroom,
		"is_poster": is_poster,
		"class_id": class_id,
		"school_year_id": school_year_id,
	}


def _teacher_subjects_map(class_id, school_year_id, teacher_ids=None):
	filters = {"class_id": class_id, "school_year_id": school_year_id}
	if teacher_ids is not None:
		if not teacher_ids:
			return {}
		filters["teacher_id"] = ["in", list(teacher_ids)]
	rows = frappe.get_all(
		"SIS Subject Assignment",
		filters=filters,
		fields=["teacher_id", "actual_subject_id"],
		ignore_permissions=True,
		limit_page_length=2000,
	)
	subj_ids = {r.get("actual_subject_id") for r in rows if r.get("actual_subject_id")}
	title_map = _resolve_subject_titles(subj_ids)
	out = {}
	for row in rows:
		tid = row.get("teacher_id")
		sid = row.get("actual_subject_id")
		if not tid or not sid:
			continue
		entry = {"id": sid, "title": title_map.get(sid, sid)}
		bucket = out.setdefault(tid, [])
		if not any(item.get("id") == sid for item in bucket):
			bucket.append(entry)
	return out


def _homeroom_entries(cls):
	"""Danh sách GVCN/phó kèm email/teacherId cho social-service."""
	entries = []
	for tid, role in [
		(cls.get("homeroom_teacher"), "homeroom"),
		(cls.get("vice_homeroom_teacher"), "vice_homeroom"),
	]:
		snap = _teacher_snapshot_for_chat(tid, homeroom_role=role)
		if not snap:
			continue
		entries.append(
			{
				"teacherId": snap.get("teacherId") or tid,
				"email": (snap.get("email") or "").strip().lower(),
				"userId": snap.get("userId") or "",
				"name": snap.get("name") or tid,
				"role": role,
			}
		)
	return entries


def _poster_rows(class_id, school_year_id):
	return frappe.get_all(
		"SIS Class Newsfeed Poster",
		filters={"class_id": class_id, "school_year_id": school_year_id},
		fields=["name", "teacher_id", "added_by", "campus_id", "creation", "modified"],
		ignore_permissions=True,
		order_by="creation asc",
		limit_page_length=500,
	)


@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def get_my_class_newsfeed_access(class_id=None, school_year_id=None):
	"""Quyền bảng tin lớp của caller hiện tại: edit | readonly | none."""
	try:
		payload = _parse_payload()
		class_id = class_id or payload.get("class_id")
		school_year_id = school_year_id or payload.get("school_year_id")
		if not class_id:
			return error_response(message="Thiếu class_id", code="MISSING_CLASS")
		if not school_year_id:
			return error_response(message="Thiếu school_year_id", code="MISSING_SCHOOL_YEAR")

		user = frappe.session.user
		if not user or user == "Guest":
			return error_response(message="Vui lòng đăng nhập", code="NOT_AUTHENTICATED")

		cls = _get_class(class_id)
		if not cls:
			return error_response(message="Không tìm thấy lớp", code="CLASS_NOT_FOUND")

		return success_response(data=_compute_my_access(cls, class_id, school_year_id))
	except Exception as e:
		frappe.logger().error(f"[NewsfeedPoster] get_my_class_newsfeed_access: {e}")
		return error_response(
			message=_("Không thể kiểm tra quyền bảng tin lớp"),
			code="NEWSFEED_ACCESS_ERROR",
		)


@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def get_class_newsfeed_posters(class_id=None, school_year_id=None):
	"""Toàn bộ người được đăng bài lớp: GVCN/phó (mặc định) + GV được cấu hình thêm.

	Card ở giao diện hiển thị cả hai nhóm để người dùng thấy đúng "ai đang đăng
	được", nên GVCN/phó phải nằm trong payload dù không có bản ghi trong DocType.
	"""
	try:
		payload = _parse_payload()
		class_id = class_id or payload.get("class_id")
		school_year_id = school_year_id or payload.get("school_year_id")
		if not class_id or not school_year_id:
			return error_response(message="Thiếu class_id hoặc school_year_id", code="MISSING_PARAMS")

		cls = _get_class(class_id)
		if not cls:
			return error_response(message="Không tìm thấy lớp", code="CLASS_NOT_FOUND")

		access_data = _compute_my_access(cls, class_id, school_year_id)
		if access_data.get("access") == "none" and not access_data.get("can_manage_posters"):
			return error_response(message="Bạn không có quyền xem danh sách", code="ACCESS_DENIED")

		homeroom = []
		for tid, role in [
			(cls.get("homeroom_teacher"), "homeroom"),
			(cls.get("vice_homeroom_teacher"), "vice_homeroom"),
		]:
			snap = _teacher_snapshot_for_chat(tid, homeroom_role=role)
			if not snap:
				continue
			homeroom.append(
				{
					"teacherId": snap.get("teacherId") or tid,
					"teacherName": snap.get("name") or tid,
					"email": snap.get("email") or "",
					"avatarUrl": snap.get("avatarUrl") or "",
					"role": role,
				}
			)

		rows = _poster_rows(class_id, school_year_id)
		subjects_map = _teacher_subjects_map(
			class_id, school_year_id, [r.get("teacher_id") for r in rows if r.get("teacher_id")]
		)

		posters = []
		for row in rows:
			tid = row.get("teacher_id")
			snap = _teacher_snapshot_for_chat(tid, subjects=subjects_map.get(tid, []))
			added_by_name = ""
			if row.get("added_by"):
				added_by_name = (
					frappe.db.get_value("User", row.get("added_by"), "full_name")
					or row.get("added_by")
				)
			posters.append(
				{
					"name": row.get("name"),
					"teacherId": tid,
					"teacherName": (snap or {}).get("name") or tid,
					"email": (snap or {}).get("email") or "",
					"avatarUrl": (snap or {}).get("avatarUrl") or "",
					"subjects": (snap or {}).get("subjects") or subjects_map.get(tid, []),
					"addedBy": row.get("added_by") or "",
					"addedByName": added_by_name,
					"creation": str(row.get("creation") or ""),
				}
			)

		return success_response(
			data={
				"homeroom": homeroom,
				"posters": posters,
				"can_manage_posters": bool(access_data.get("can_manage_posters")),
			}
		)
	except Exception as e:
		frappe.logger().error(f"[NewsfeedPoster] get_class_newsfeed_posters: {e}")
		return error_response(
			message=_("Không thể tải danh sách người đăng bài"),
			code="NEWSFEED_POSTER_LIST_ERROR",
		)


@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def get_addable_teachers(class_id=None, school_year_id=None):
	"""GV bộ môn của lớp chưa có trong danh sách poster (và không phải GVCN/phó)."""
	try:
		payload = _parse_payload()
		class_id = class_id or payload.get("class_id")
		school_year_id = school_year_id or payload.get("school_year_id")
		if not class_id or not school_year_id:
			return error_response(message="Thiếu class_id hoặc school_year_id", code="MISSING_PARAMS")

		cls = _get_class(class_id)
		if not cls:
			return error_response(message="Không tìm thấy lớp", code="CLASS_NOT_FOUND")
		if not _can_manage_posters(cls):
			return error_response(
				message="Chỉ GVCN/phó hoặc SIS Manager được thêm người đăng bài",
				code="ACCESS_DENIED",
			)

		subjects_map = _teacher_subjects_map(class_id, school_year_id)
		homeroom_ids = {cls.get("homeroom_teacher"), cls.get("vice_homeroom_teacher")}
		existing = {
			r.get("teacher_id")
			for r in _poster_rows(class_id, school_year_id)
			if r.get("teacher_id")
		}

		teachers = []
		for tid, subjects in subjects_map.items():
			if not tid or tid in homeroom_ids or tid in existing:
				continue
			snap = _teacher_snapshot_for_chat(tid, subjects=subjects)
			if not snap:
				continue
			teachers.append(
				{
					"teacherId": tid,
					"teacherName": snap.get("name") or tid,
					"email": snap.get("email") or "",
					"avatarUrl": snap.get("avatarUrl") or "",
					"subjects": subjects,
				}
			)

		teachers.sort(key=lambda t: (t.get("teacherName") or "").lower())
		return success_response(data={"teachers": teachers})
	except Exception as e:
		frappe.logger().error(f"[NewsfeedPoster] get_addable_teachers: {e}")
		return error_response(
			message=_("Không thể tải danh sách giáo viên có thể thêm"),
			code="NEWSFEED_ADDABLE_ERROR",
		)


@frappe.whitelist(allow_guest=False, methods=["POST"])
def add_class_newsfeed_poster(class_id=None, school_year_id=None, teacher_id=None):
	"""Thêm GV vào danh sách được đăng bài."""
	try:
		payload = _parse_payload()
		class_id = class_id or payload.get("class_id")
		school_year_id = school_year_id or payload.get("school_year_id")
		teacher_id = teacher_id or payload.get("teacher_id")
		if not class_id or not school_year_id or not teacher_id:
			return error_response(message="Thiếu tham số", code="MISSING_PARAMS")

		cls = _get_class(class_id)
		if not cls:
			return error_response(message="Không tìm thấy lớp", code="CLASS_NOT_FOUND")
		if not _can_manage_posters(cls):
			return error_response(
				message="Chỉ GVCN/phó hoặc SIS Manager được thêm người đăng bài",
				code="ACCESS_DENIED",
			)

		doc = frappe.get_doc(
			{
				"doctype": "SIS Class Newsfeed Poster",
				"class_id": class_id,
				"school_year_id": school_year_id,
				"teacher_id": teacher_id,
				"campus_id": cls.get("campus_id"),
				"added_by": frappe.session.user,
			}
		)
		doc.insert(ignore_permissions=True)
		frappe.db.commit()

		return success_response(
			data={"name": doc.name, "teacherId": teacher_id},
			message="Đã thêm giáo viên vào danh sách đăng bài",
		)
	except frappe.ValidationError as e:
		return error_response(message=str(e), code="VALIDATION_ERROR")
	except Exception as e:
		frappe.logger().error(f"[NewsfeedPoster] add_class_newsfeed_poster: {e}")
		return error_response(
			message=_("Không thể thêm giáo viên"),
			code="NEWSFEED_POSTER_ADD_ERROR",
		)


@frappe.whitelist(allow_guest=False, methods=["POST"])
def remove_class_newsfeed_poster(name=None):
	"""Gỡ GV khỏi danh sách được đăng bài."""
	try:
		payload = _parse_payload()
		name = name or payload.get("name")
		if not name:
			return error_response(message="Thiếu name", code="MISSING_PARAMS")

		if not frappe.db.exists("SIS Class Newsfeed Poster", name):
			return error_response(message="Không tìm thấy bản ghi", code="NOT_FOUND")

		row = frappe.db.get_value(
			"SIS Class Newsfeed Poster",
			name,
			["name", "class_id", "school_year_id", "teacher_id"],
			as_dict=True,
		)
		cls = _get_class(row.get("class_id"))
		if not cls:
			return error_response(message="Không tìm thấy lớp", code="CLASS_NOT_FOUND")
		if not _can_manage_posters(cls):
			return error_response(
				message="Chỉ GVCN/phó hoặc SIS Manager được gỡ người đăng bài",
				code="ACCESS_DENIED",
			)

		frappe.delete_doc("SIS Class Newsfeed Poster", name, ignore_permissions=True)
		frappe.db.commit()
		return success_response(data={"name": name}, message="Đã gỡ giáo viên khỏi danh sách")
	except Exception as e:
		frappe.logger().error(f"[NewsfeedPoster] remove_class_newsfeed_poster: {e}")
		return error_response(
			message=_("Không thể gỡ giáo viên"),
			code="NEWSFEED_POSTER_REMOVE_ERROR",
		)


@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def get_class_newsfeed_permissions(class_id=None, school_year_id=None):
	"""
	Danh sách người được đăng bài lớp cho social-service enforce.

	Cho phép: System Manager (API key service) hoặc staff đã đăng nhập.
	Trả homeroom + posters với teacherId / email.
	"""
	try:
		payload = _parse_payload()
		class_id = class_id or payload.get("class_id")
		school_year_id = school_year_id or payload.get("school_year_id")
		if not class_id or not school_year_id:
			return error_response(message="Thiếu class_id hoặc school_year_id", code="MISSING_PARAMS")

		user = frappe.session.user
		if not user or user == "Guest":
			return error_response(message="Vui lòng đăng nhập", code="NOT_AUTHENTICATED")

		cls = _get_class(class_id)
		if not cls:
			return error_response(message="Không tìm thấy lớp", code="CLASS_NOT_FOUND")

		homeroom = _homeroom_entries(cls)
		rows = _poster_rows(class_id, school_year_id)
		posters = []
		for row in rows:
			tid = row.get("teacher_id")
			snap = _teacher_snapshot_for_chat(tid)
			if not snap:
				continue
			posters.append(
				{
					"teacherId": snap.get("teacherId") or tid,
					"email": (snap.get("email") or "").strip().lower(),
					"userId": snap.get("userId") or "",
					"name": snap.get("name") or tid,
				}
			)

		return success_response(
			data={
				"classId": class_id,
				"schoolYearId": school_year_id,
				"homeroom": homeroom,
				"posters": posters,
			}
		)
	except Exception as e:
		frappe.logger().error(f"[NewsfeedPoster] get_class_newsfeed_permissions: {e}")
		return error_response(
			message=_("Không thể tải quyền đăng bài lớp"),
			code="NEWSFEED_PERMISSIONS_ERROR",
		)
