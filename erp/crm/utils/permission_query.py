"""
CRM Permission Query - Filter CRM doctypes theo campus_id
"""

import frappe

from erp.sis.utils.permission_query import get_campus_permission_query


def crm_lead_query(user):
    """Filter CRM Lead theo campus_id cua user"""
    if "System Manager" in frappe.get_roles(user):
        return ""
    
    campus_ids = _get_user_campus_ids(user)
    if not campus_ids:
        return "1=0"
    
    campus_list = ", ".join([f"'{c}'" for c in campus_ids])
    return f"`tabCRM Lead`.campus_id IN ({campus_list})"


def crm_exam_query(user):
    """Filter CRM Exam theo campus_id cua user"""
    if "System Manager" in frappe.get_roles(user):
        return ""
    
    campus_ids = _get_user_campus_ids(user)
    if not campus_ids:
        return "1=0"
    
    campus_list = ", ".join([f"'{c}'" for c in campus_ids])
    return f"`tabCRM Exam`.campus_id IN ({campus_list})"


def crm_issue_query(user):
	"""Filter CRM Issue theo campus_id + roles CRM."""
	if "System Manager" in frappe.get_roles(user):
		return ""

	allowed_roles = [
		"SIS Manager",
		"Registrar",
		"SIS Sales",
		"SIS Sales Care",
		"SIS Sales Care Admin",
		"SIS Sales Admin",
		"SIS BOD",
	]
	user_roles = frappe.get_roles(user)
	if not any(role in user_roles for role in allowed_roles):
		return "1=0"

	return get_campus_permission_query("CRM Issue", user)


def has_crm_permission(doc, ptype, user):
	"""Kiểm tra quyền truy cập CRM doctype (role + campus_id nếu có)."""
	if "System Manager" in frappe.get_roles(user):
		return True

	allowed_roles = [
		"SIS Manager",
		"Registrar",
		"SIS Sales",
		"SIS Sales Care",
		"SIS Sales Care Admin",
		"SIS Sales Admin",
		"SIS BOD",
	]
	user_roles = frappe.get_roles(user)
	if not any(role in user_roles for role in allowed_roles):
		return False

	# Lọc theo campus khi document đã có campus_id
	if getattr(doc, "campus_id", None):
		campus_ids = _get_user_campus_ids(user)
		if campus_ids and doc.campus_id not in campus_ids:
			return False

	return True


def _get_user_campus_ids(user):
    """Lấy danh sách campus_id của user — nguồn truth thống nhất qua Role Campus *"""
    from erp.sis.utils.campus_permissions import get_user_campuses

    return get_user_campuses(user) or []

def crm_guardian_query(user):
	"""Permission query for CRM Guardian."""
	return get_campus_permission_query("CRM Guardian", user)

def crm_family_query(user):
	"""Permission query for CRM Family."""
	return get_campus_permission_query("CRM Family", user)

def crm_admission_course_query(user):
	"""Permission query for CRM Admission Course."""
	return get_campus_permission_query("CRM Admission Course", user)

def crm_admission_course_student_query(user):
	"""Permission query for CRM Admission Course Student."""
	return get_campus_permission_query("CRM Admission Course Student", user)

def crm_admission_entrance_exam_query(user):
	"""Permission query for CRM Admission Entrance Exam."""
	return get_campus_permission_query("CRM Admission Entrance Exam", user)

def crm_admission_entrance_exam_student_query(user):
	"""Permission query for CRM Admission Entrance Exam Student."""
	return get_campus_permission_query("CRM Admission Entrance Exam Student", user)

def crm_admission_event_query(user):
	"""Permission query for CRM Admission Event."""
	return get_campus_permission_query("CRM Admission Event", user)

def crm_admission_event_student_query(user):
	"""Permission query for CRM Admission Event Student."""
	return get_campus_permission_query("CRM Admission Event Student", user)

def crm_exam_score_query(user):
	"""Permission query for CRM Exam Score."""
	return get_campus_permission_query("CRM Exam Score", user)

def crm_lead_note_query(user):
	"""Permission query for CRM Lead Note."""
	return get_campus_permission_query("CRM Lead Note", user)

def crm_lead_step_history_query(user):
	"""Permission query for CRM Lead Step History."""
	return get_campus_permission_query("CRM Lead Step History", user)

