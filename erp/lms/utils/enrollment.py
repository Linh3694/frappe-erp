"""Enrollment helpers — validate quyền theo section/course."""

import frappe

from erp.lms.constants import ENROLLMENT_ROLE_STUDENT, ENROLLMENT_STATUS_ACTIVE
from erp.lms.utils.permissions import _get_crm_student_for_user, is_lms_staff

# Thứ bậc role (cao hơn = nhiều quyền hơn)
ROLE_RANK = {
	"observer": 0,
	"student": 1,
	"ta": 2,
	"teacher": 3,
	"designer": 4,
}


def get_enrollment_for_user(section_id: str, user: str | None = None) -> dict | None:
	"""Lấy enrollment active của user trong section."""
	user = user or frappe.session.user
	if not section_id or user == "Guest":
		return None

	row = frappe.db.get_value(
		"LMS Enrollment",
		{"section": section_id, "user": user, "status": ENROLLMENT_STATUS_ACTIVE},
		["name", "role", "student_id", "section"],
		as_dict=True,
	)
	if row:
		return row

	student_id = _get_crm_student_for_user(user)
	if student_id:
		return frappe.db.get_value(
			"LMS Enrollment",
			{
				"section": section_id,
				"student_id": student_id,
				"role": ENROLLMENT_ROLE_STUDENT,
				"status": ENROLLMENT_STATUS_ACTIVE,
			},
			["name", "role", "student_id", "section"],
			as_dict=True,
		)
	return None


def validate_section_enrollment(section_id: str, user: str | None = None, min_role: str = "student"):
	"""Raise PermissionError nếu user không đủ quyền trong section."""
	user = user or frappe.session.user
	if is_lms_staff(user):
		return get_enrollment_for_user(section_id, user)

	enr = get_enrollment_for_user(section_id, user)
	if not enr:
		frappe.throw("Không có enrollment trong section này", frappe.PermissionError)

	min_rank = ROLE_RANK.get(min_role, 1)
	user_rank = ROLE_RANK.get(enr.role, 0)
	if user_rank < min_rank:
		frappe.throw("Không đủ quyền trong section", frappe.PermissionError)
	return enr


def get_student_id_for_user(user: str | None = None) -> str | None:
	user = user or frappe.session.user
	enr = frappe.db.get_value(
		"LMS Enrollment",
		{"user": user, "role": ENROLLMENT_ROLE_STUDENT, "status": ENROLLMENT_STATUS_ACTIVE},
		"student_id",
	)
	if enr:
		return enr
	return _get_crm_student_for_user(user)


def get_course_id_from_section(section_id: str) -> str | None:
	return frappe.db.get_value("LMS Course Section", section_id, "course")
