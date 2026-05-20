"""Discussion forum — thread, reply, pin, lock, graded."""

import frappe
from frappe.utils import now_datetime

from erp.lms.utils.enrollment import get_student_id_for_user, validate_section_enrollment
from erp.lms.utils.permissions import is_lms_staff, require_lms_staff


def create_discussion(data: dict) -> dict:
	"""GV tạo forum; graded → tự tạo grade column."""
	require_lms_staff()
	doc = frappe.get_doc({"doctype": "LMS Discussion", **data})
	if not doc.campus_id and doc.course:
		doc.campus_id = frappe.db.get_value("LMS Course", doc.course, "campus_id")
	doc.insert()
	_ensure_grade_column_for_discussion(doc)
	return doc.as_dict()


def list_discussions(course_id: str = None, section_id: str = None, user: str | None = None) -> list:
	user = user or frappe.session.user
	filters = {}
	if section_id:
		validate_section_enrollment(section_id, user, min_role="observer")
		filters["section"] = section_id
	elif course_id:
		from erp.lms.utils.permissions import user_enrolled_in_course
		if not is_lms_staff(user) and not user_enrolled_in_course(user, course_id):
			frappe.throw("Không có quyền", frappe.PermissionError)
		filters["course"] = course_id
	else:
		frappe.throw("course_id hoặc section_id bắt buộc")

	return frappe.get_all(
		"LMS Discussion",
		filters=filters,
		fields=[
			"name", "title", "course", "section", "graded", "points_possible",
			"due_at", "locked", "description", "modified",
		],
		order_by="modified desc",
		limit=100,
	)


def get_discussion(discussion_id: str, user: str | None = None) -> dict:
	user = user or frappe.session.user
	doc = frappe.get_doc("LMS Discussion", discussion_id)
	_check_discussion_access(doc, user, min_role="observer")
	return doc.as_dict()


def update_discussion(discussion_id: str, data: dict) -> dict:
	"""Pin/lock/graded — staff only."""
	require_lms_staff()
	doc = frappe.get_doc("LMS Discussion", discussion_id)
	allowed = {"title", "description", "locked", "graded", "points_possible", "due_at"}
	for key, val in (data or {}).items():
		if key in allowed:
			setattr(doc, key, val)
	doc.save(ignore_permissions=True)
	if doc.graded:
		_ensure_grade_column_for_discussion(doc)
	return doc.as_dict()


def post_entry(discussion_id: str, body: str, parent_entry: str | None = None, user: str | None = None) -> dict:
	"""HS/GV đăng bài; observer không được post."""
	user = user or frappe.session.user
	discussion = frappe.get_doc("LMS Discussion", discussion_id)
	_check_discussion_access(discussion, user, min_role="student")

	if discussion.locked and not is_lms_staff(user):
		frappe.throw("Discussion đã khóa")

	if discussion.due_at and now_datetime() > discussion.due_at and not is_lms_staff(user):
		frappe.throw("Đã quá hạn đăng bài")

	doc = frappe.get_doc(
		{
			"doctype": "LMS Discussion Entry",
			"discussion": discussion_id,
			"author": user,
			"parent_entry": parent_entry,
			"body": body,
			"posted_at": now_datetime(),
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.as_dict()


def list_entries(discussion_id: str, user: str | None = None) -> list:
	"""Danh sách entry (threaded flat + parent_entry)."""
	user = user or frappe.session.user
	discussion = frappe.get_doc("LMS Discussion", discussion_id)
	_check_discussion_access(discussion, user, min_role="observer")

	entries = frappe.get_all(
		"LMS Discussion Entry",
		filters={"discussion": discussion_id},
		fields=[
			"name", "discussion", "author", "parent_entry", "body",
			"posted_at", "pinned", "hidden",
		],
		order_by="pinned desc, posted_at asc",
	)
	if not is_lms_staff(user):
		entries = [e for e in entries if not e.hidden]
	for e in entries:
		e["author_name"] = frappe.db.get_value("User", e.author, "full_name") or e.author
	return entries


def pin_entry(entry_id: str, pinned: bool = True) -> dict:
	require_lms_staff()
	frappe.db.set_value("LMS Discussion Entry", entry_id, "pinned", 1 if pinned else 0)
	return frappe.get_doc("LMS Discussion Entry", entry_id).as_dict()


def hide_entry(entry_id: str, hidden: bool = True) -> dict:
	"""Moderation — ẩn entry."""
	require_lms_staff()
	frappe.db.set_value("LMS Discussion Entry", entry_id, "hidden", 1 if hidden else 0)
	return frappe.get_doc("LMS Discussion Entry", entry_id).as_dict()


def grade_discussion_participation(
	discussion_id: str,
	student_id: str,
	score: float,
	user: str | None = None,
) -> dict:
	"""Chấm điểm thảo luận (graded discussion)."""
	require_lms_staff()
	discussion = frappe.get_doc("LMS Discussion", discussion_id)
	if not discussion.graded or not discussion.section:
		frappe.throw("Discussion không graded hoặc thiếu section")

	column = frappe.db.get_value("LMS Grade Column", {"discussion": discussion_id})
	if not column:
		_ensure_grade_column_for_discussion(discussion)
		column = frappe.db.get_value("LMS Grade Column", {"discussion": discussion_id})

	from erp.lms.services.gradebook_service import upsert_grade_entry

	return upsert_grade_entry(column, student_id, score)


def _check_discussion_access(discussion, user: str, min_role: str = "student"):
	if discussion.section:
		validate_section_enrollment(discussion.section, user, min_role=min_role)
	elif discussion.course:
		from erp.lms.utils.permissions import user_enrolled_in_course
		if not is_lms_staff(user) and not user_enrolled_in_course(user, discussion.course):
			frappe.throw("Không có quyền", frappe.PermissionError)


def _ensure_grade_column_for_discussion(discussion):
	if not discussion.graded or not discussion.section:
		return
	if frappe.db.exists("LMS Grade Column", {"discussion": discussion.name}):
		return
	frappe.get_doc(
		{
			"doctype": "LMS Grade Column",
			"section": discussion.section,
			"title": discussion.title,
			"points_possible": discussion.points_possible or 100,
			"column_type": "discussion",
			"discussion": discussion.name,
			"campus_id": discussion.campus_id,
		}
	).insert(ignore_permissions=True)
