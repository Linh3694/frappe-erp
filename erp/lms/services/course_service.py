"""CRUD Course shell — Phase 1."""

import frappe

from erp.lms.utils.permissions import is_lms_staff, require_lms_staff, user_enrolled_in_course
from erp.utils.campus_utils import get_current_campus_from_context
from erp.utils.api_response import paginated_response


def list_courses(page=1, per_page=20, course_state=None, program=None):
	user = frappe.session.user
	filters = {}
	if course_state:
		filters["course_state"] = course_state
	if program:
		filters["program"] = program

	if is_lms_staff(user):
		campus_id = get_current_campus_from_context()
		if campus_id:
			filters["campus_id"] = campus_id
	else:
		# Student: chỉ course đã enroll
		section_ids = frappe.get_all(
			"LMS Enrollment",
			filters={"user": user, "status": "active"},
			pluck="section",
		)
		if not section_ids:
			return [], 0
		course_ids = frappe.get_all(
			"LMS Course Section",
			filters={"name": ["in", section_ids]},
			pluck="course",
		)
		if not course_ids:
			return [], 0
		filters["name"] = ["in", list(set(course_ids))]
		filters["course_state"] = "published"

	start = (int(page) - 1) * int(per_page)
	rows = frappe.get_all(
		"LMS Course",
		filters=filters,
		fields=[
			"name",
			"title",
			"code",
			"course_state",
			"campus_id",
			"program",
			"modified",
		],
		order_by="modified desc",
		start=start,
		limit_page_length=per_page,
	)
	total = frappe.db.count("LMS Course", filters=filters)
	return rows, total


def get_course_detail(course_id: str) -> dict:
	user = frappe.session.user
	if not is_lms_staff(user) and not user_enrolled_in_course(user, course_id):
		frappe.throw("Không có quyền xem khóa học", frappe.PermissionError)

	course = frappe.get_doc("LMS Course", course_id).as_dict()
	sections = frappe.get_all(
		"LMS Course Section",
		filters={"course": course_id},
		fields=["name", "section_name", "sis_class_id", "start_date", "end_date"],
		order_by="section_name asc",
	)
	modules = frappe.get_all(
		"LMS Module",
		filters={"course": course_id},
		fields=["name", "title", "position", "unlock_at"],
		order_by="position asc",
	)
	module_items = {}
	if modules:
		items = frappe.get_all(
			"LMS Module Item",
			filters={"module": ["in", [m["name"] for m in modules]]},
			fields=[
				"name",
				"module",
				"title",
				"position",
				"item_type",
				"published",
				"video_asset",
			],
			order_by="position asc",
		)
		for it in items:
			module_items.setdefault(it["module"], []).append(it)

	for mod in modules:
		mod["items"] = module_items.get(mod["name"], [])

	course["sections"] = sections
	course["modules"] = modules
	return course


def create_course(data: dict) -> dict:
	require_lms_staff()
	doc = frappe.get_doc({"doctype": "LMS Course", **data})
	if not doc.campus_id:
		doc.campus_id = get_current_campus_from_context()
	doc.insert()
	return doc.as_dict()


def update_course(course_id: str, data: dict) -> dict:
	require_lms_staff()
	doc = frappe.get_doc("LMS Course", course_id)
	doc.update(data)
	doc.save()
	return doc.as_dict()
