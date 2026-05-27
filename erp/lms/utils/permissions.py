"""Phân quyền LMS — campus scope + enrollment."""

import frappe

from erp.utils.campus_utils import get_current_campus_from_context

LMS_STAFF_ROLES = frozenset(
	{
		"System Manager",
		"SIS Manager",
		"SIS Teacher",
		"Academic Admin",
		# Role LMS chuẩn (Desk)
		"LMS Teacher",
		"LMS TA",
		"LMS Designer",
		"LMS Admin",
	}
)


def _get_user_campus_ids(user: str) -> list:
	from erp.utils.campus_utils import get_all_campus_ids_from_user_roles

	email = frappe.db.get_value("User", user, "email") or user
	return get_all_campus_ids_from_user_roles(email) or []


def lms_campus_query(user: str, doctype: str) -> str:
	"""Filter DocType có campus_id."""
	if "System Manager" in frappe.get_roles(user):
		return ""
	campus_ids = _get_user_campus_ids(user)
	if not campus_ids:
		return "1=0"
	campus_list = ", ".join([f"'{c}'" for c in campus_ids])
	return f"`tab{doctype}`.campus_id IN ({campus_list})"


def lms_program_query(user):
	return lms_campus_query(user, "LMS Program")


def lms_course_query(user):
	return lms_campus_query(user, "LMS Course")


def lms_course_section_query(user):
	return lms_campus_query(user, "LMS Course Section")


def lms_enrollment_query(user):
	return lms_campus_query(user, "LMS Enrollment")


def lms_video_asset_query(user):
	return lms_campus_query(user, "LMS Video Asset")


def has_lms_campus_permission(doc, ptype, user):
	if "System Manager" in frappe.get_roles(user):
		return True
	if not getattr(doc, "campus_id", None):
		return True
	campus_ids = _get_user_campus_ids(user)
	return doc.campus_id in campus_ids


def is_lms_staff(user: str | None = None) -> bool:
	user = user or frappe.session.user
	if user == "Guest":
		return False
	roles = set(frappe.get_roles(user))
	return bool(roles & LMS_STAFF_ROLES)


def require_lms_staff():
	if not is_lms_staff():
		frappe.throw("Không có quyền thao tác LMS", frappe.PermissionError)


def user_enrolled_in_course(user: str, course_id: str, roles: list | None = None) -> bool:
	"""Kiểm tra user/student có enrollment active trong course (bất kỳ section)."""
	if not course_id:
		return False
	sections = frappe.get_all("LMS Course Section", filters={"course": course_id}, pluck="name")
	if not sections:
		return False

	filters = {"section": ["in", sections], "status": "active"}
	if roles:
		filters["role"] = ["in", roles]

	# Teacher/staff qua User
	enrollments = frappe.get_all(
		"LMS Enrollment",
		filters={**filters, "user": user},
		limit=1,
	)
	if enrollments:
		return True

	# Student — map CRM Student qua email (đơn giản Phase 1)
	student_id = _get_crm_student_for_user(user)
	if student_id:
		return bool(
			frappe.db.exists(
				"LMS Enrollment",
				{**filters, "student_id": student_id, "role": "student"},
			)
		)
	return False


def user_can_access_video_asset(user: str, asset_id: str) -> bool:
	if is_lms_staff(user):
		return True
	doc = frappe.db.get_value(
		"LMS Video Asset",
		asset_id,
		["course", "campus_id", "status", "uploaded_by"],
		as_dict=True,
	)
	if not doc:
		return False
	if doc.uploaded_by == user:
		return True
	if doc.status != "ready":
		return is_lms_staff(user)
	if doc.course:
		return user_enrolled_in_course(user, doc.course)
	return is_lms_staff(user)


def _get_crm_student_for_user(user: str) -> str | None:
	"""Map User → CRM Student (email hoặc user link nếu có sau này)."""
	email = frappe.db.get_value("User", user, "email")
	if email and frappe.db.has_column("CRM Student", "email"):
		student = frappe.db.get_value("CRM Student", {"email": email}, "name")
		if student:
			return student
	# Fallback: User name trùng student code (hiếm)
	return frappe.db.get_value("CRM Student", {"student_code": user}, "name")

def lms_announcement_query(user):
	"""Permission query for LMS Announcement."""
	return lms_campus_query(user, "LMS Announcement")

def lms_submission_query(user):
	"""Permission query for LMS Submission."""
	return lms_campus_query(user, "LMS Submission")

def lms_grade_entry_query(user):
	"""Permission query for LMS Grade Entry."""
	return lms_campus_query(user, "LMS Grade Entry")

def lms_quiz_attempt_query(user):
	"""Permission query for LMS Quiz Attempt."""
	return lms_campus_query(user, "LMS Quiz Attempt")

def lms_course_progress_query(user):
	"""Permission query for LMS Course Progress."""
	return lms_campus_query(user, "LMS Course Progress")

def lms_content_progress_query(user):
	"""Permission query for LMS Content Progress."""
	return lms_campus_query(user, "LMS Content Progress")

def lms_engagement_score_query(user):
	"""Permission query for LMS Engagement Score."""
	return lms_campus_query(user, "LMS Engagement Score")

def lms_group_membership_query(user):
	"""Permission query for LMS Group Membership."""
	return lms_campus_query(user, "LMS Group Membership")

def lms_grade_sync_log_query(user):
	"""Permission query for LMS Grade Sync Log."""
	return lms_campus_query(user, "LMS Grade Sync Log")

def lms_activity_log_query(user):
	"""Permission query for LMS Activity Log."""
	return lms_campus_query(user, "LMS Activity Log")

def lms_conversation_query(user):
	"""Permission query for LMS Conversation."""
	return lms_campus_query(user, "LMS Conversation")

def lms_module_query(user):
	"""Permission query for LMS Module."""
	return lms_campus_query(user, "LMS Module")

def lms_external_tool_query(user):
	"""Permission query for LMS External Tool."""
	return lms_campus_query(user, "LMS External Tool")

def lms_blueprint_sync_log_query(user):
	"""Permission query for LMS Blueprint Sync Log."""
	return lms_campus_query(user, "LMS Blueprint Sync Log")

