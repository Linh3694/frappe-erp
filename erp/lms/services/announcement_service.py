"""Course announcements."""

import frappe
from frappe.utils import now_datetime

from erp.lms.utils.enrollment import validate_section_enrollment
from erp.lms.utils.permissions import is_lms_staff, require_lms_staff


def post_announcement(data: dict) -> dict:
	require_lms_staff()
	data.setdefault("posted_at", now_datetime())
	data.setdefault("posted_by", frappe.session.user)
	doc = frappe.get_doc({"doctype": "LMS Announcement", **data})
	doc.insert()
	return doc.as_dict()


def list_announcements(course_id: str = None, section_id: str = None, user: str | None = None) -> list:
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
		"LMS Announcement",
		filters=filters,
		fields=["name", "title", "message", "posted_at", "posted_by", "course", "section"],
		order_by="posted_at desc",
		limit=50,
	)
