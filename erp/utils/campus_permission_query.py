"""
Permission query generic cho DocType ngoài module SIS (Admin, Inventory, PM, Portal, Feedback).
"""

from __future__ import annotations

import frappe

from erp.sis.utils.campus_permissions import get_campus_filter
from erp.sis.utils.permission_query import get_campus_permission_query


def campus_doctype_query(doctype: str, user: str) -> str:
	"""Wrapper generic — tái sử dụng get_campus_permission_query."""
	return get_campus_permission_query(doctype, user)


def has_campus_doctype_permission(doc, ptype, user):
	"""Kiểm tra quyền theo campus_id — campus đang active."""
	from erp.sis.utils.campus_permissions import has_campus_permission

	return has_campus_permission(doc, ptype, user)


# --- Wrapper cụ thể (generator có thể bổ sung thêm) ---

def feedback_query(user):
	return campus_doctype_query("Feedback", user)


def portal_api_error_query(user):
	return campus_doctype_query("Portal API Error", user)


def portal_guardian_activity_query(user):
	return campus_doctype_query("Portal Guardian Activity", user)


def erp_administrative_room_yearly_assignment_query(user):
	return campus_doctype_query("ERP Administrative Room Yearly Assignment", user)


def erp_administrative_ticket_query(user):
	return campus_doctype_query("ERP Administrative Ticket", user)


def erp_administrative_facility_handover_query(user):
	return campus_doctype_query("ERP Administrative Facility Handover", user)


def erp_administrative_inventory_check_query(user):
	return campus_doctype_query("ERP Administrative Inventory Check", user)


def erp_administrative_room_activity_log_query(user):
	return campus_doctype_query("ERP Administrative Room Activity Log", user)


def erp_administrative_room_facility_equipment_query(user):
	return campus_doctype_query("ERP Administrative Room Facility Equipment", user)


def erp_inventory_device_query(user):
	return campus_doctype_query("ERP Inventory Device", user)


def erp_inventory_inspection_query(user):
	return campus_doctype_query("ERP Inventory Inspection", user)


def erp_inventory_handover_log_query(user):
	return campus_doctype_query("ERP Inventory Handover Log", user)


def erp_inventory_activity_log_query(user):
	return campus_doctype_query("ERP Inventory Activity Log", user)


def pm_task_query(user):
	return campus_doctype_query("PM Task", user)


def pm_meeting_query(user):
	return campus_doctype_query("PM Meeting", user)


def pm_project_member_query(user):
	return campus_doctype_query("PM Project Member", user)


def pm_resource_query(user):
	return campus_doctype_query("PM Resource", user)


def pm_requirement_query(user):
	return campus_doctype_query("PM Requirement", user)


def pm_change_log_query(user):
	return campus_doctype_query("PM Change Log", user)


def pm_project_invitation_query(user):
	return campus_doctype_query("PM Project Invitation", user)


def pm_project_query(user):
	return campus_doctype_query("PM Project", user)


def erp_administrative_room_query(user):
	return campus_doctype_query("ERP Administrative Room", user)


def erp_administrative_building_query(user):
	return campus_doctype_query("ERP Administrative Building", user)


def erp_administrative_academic_year_closure_query(user):
	return campus_doctype_query("ERP Administrative Academic Year Closure", user)


def crm_student_query(user):
	return campus_doctype_query("CRM Student", user)


def crm_pic_config_query(user):
	return campus_doctype_query("CRM PIC Config", user)
