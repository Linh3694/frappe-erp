# Copyright (c) 2024, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from .campus_permissions import get_campus_filter


def add_campus_condition(doctype, conditions, filters):
    """Add campus-based filtering conditions to queries"""
    user = frappe.session.user
    
    if user == "Administrator":
        return conditions
    
    # Get campus filter for this doctype
    campus_filter = get_campus_filter(doctype, user)
    
    if campus_filter:
        # Add campus condition to the query
        if "campus_id" in campus_filter:
            if isinstance(campus_filter["campus_id"], list) and campus_filter["campus_id"][0] == "in":
                # Handle "in" condition
                campus_list = campus_filter["campus_id"][1]
                if campus_list:
                    conditions.append(f"`tab{doctype}`.`campus_id` IN ({','.join(['%s'] * len(campus_list))})")
                    filters.extend(campus_list)
                else:
                    # No campus access - return impossible condition
                    conditions.append("1=0")
            else:
                # Handle direct equality
                conditions.append(f"`tab{doctype}`.`campus_id` = %s")
                filters.append(campus_filter["campus_id"])
    
    return conditions


# Generic Permission Query Function for SIS DocTypes
def get_campus_permission_query(doctype, user):
    """Generic permission query function for SIS doctypes with campus_id"""
    if user == "Administrator":
        return ""

    # Check if doctype has campus_id field
    try:
        meta = frappe.get_meta(doctype)
        has_campus_field = any(field.fieldname == "campus_id" for field in meta.fields)

        if not has_campus_field:
            return ""  # No campus filter for doctypes without campus_id
    except Exception as e:
        frappe.logger().error(f"Error checking doctype meta for {doctype}: {str(e)}")
        return ""

    campus_filter = get_campus_filter(doctype, user)
    if campus_filter and "campus_id" in campus_filter:
        if isinstance(campus_filter["campus_id"], list) and campus_filter["campus_id"][0] == "in":
            campus_list = campus_filter["campus_id"][1]
            if campus_list:
                campus_values = ','.join([f"'{c}'" for c in campus_list])
                return f"`tab{doctype}`.`campus_id` IN ({campus_values})"
            else:
                return "1=0"  # No access
        else:
            return f"`tab{doctype}`.`campus_id` = '{campus_filter['campus_id']}'"

    return ""


# Specific permission query functions for each SIS DocType
def sis_school_year_query(user):
    """Permission query for SIS School Year"""
    return get_campus_permission_query("SIS School Year", user)


def sis_education_stage_query(user):
    """Permission query for SIS Education Stage"""
    return get_campus_permission_query("SIS Education Stage", user)


def sis_education_grade_query(user):
    """Permission query for SIS Education Grade"""
    return get_campus_permission_query("SIS Education Grade", user)


def sis_academic_program_query(user):
    """Permission query for SIS Academic Program"""
    return get_campus_permission_query("SIS Academic Program", user)


def sis_timetable_subject_query(user):
    """Permission query for SIS Timetable Subject"""
    return get_campus_permission_query("SIS Timetable Subject", user)


def sis_curriculum_query(user):
    """Permission query for SIS Curriculum"""
    return get_campus_permission_query("SIS Curriculum", user)


def sis_actual_subject_query(user):
    """Permission query for SIS Actual Subject"""
    return get_campus_permission_query("SIS Actual Subject", user)


def sis_subject_query(user):
    """Permission query for SIS Subject"""
    return get_campus_permission_query("SIS Subject", user)


def sis_timetable_column_query(user):
    """Permission query for SIS Timetable Column"""
    return get_campus_permission_query("SIS Timetable Column", user)


def sis_calendar_query(user):
    """Permission query for SIS Calendar"""
    return get_campus_permission_query("SIS Calendar", user)


def sis_class_query(user):
    """Permission query for SIS Class"""
    return get_campus_permission_query("SIS Class", user)


def sis_teacher_query(user):
    """Permission query for SIS Teacher"""
    return get_campus_permission_query("SIS Teacher", user)


def sis_subject_assignment_query(user):
    """Permission query for SIS Subject Assignment"""
    return get_campus_permission_query("SIS Subject Assignment", user)


def sis_timetable_query(user):
    """Permission query for SIS Timetable"""
    return get_campus_permission_query("SIS Timetable", user)


def sis_timetable_instance_query(user):
    """Permission query for SIS Timetable Instance"""
    return get_campus_permission_query("SIS Timetable Instance", user)


def sis_event_query(user):
    """Permission query for SIS Event"""
    return get_campus_permission_query("SIS Event", user)


def sis_event_student_query(user):
    """Permission query for SIS Event Student"""
    return get_campus_permission_query("SIS Event Student", user)


def sis_event_teacher_query(user):
    """Permission query for SIS Event Teacher"""
    return get_campus_permission_query("SIS Event Teacher", user)


def sis_student_timetable_query(user):
    """Permission query for SIS Student Timetable"""
    return get_campus_permission_query("SIS Student Timetable", user)


def sis_class_student_query(user):
    """Permission query for SIS Class Student"""
    return get_campus_permission_query("SIS Class Student", user)


def sis_photo_query(user):
    """Permission query for SIS Photo"""
    return get_campus_permission_query("SIS Photo", user)
