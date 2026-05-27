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

    # Feature flag canary rollout — campus_pq_enabled_doctypes: ["SIS Bus Route", ...] hoặc "*"
    enabled = frappe.conf.get("campus_pq_enabled_doctypes", "*")
    if enabled != "*" and doctype not in enabled:
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


def sis_sub_curriculum_query(user):
    """Permission query for SIS Sub Curriculum"""
    return get_campus_permission_query("SIS Sub Curriculum", user)


def sis_sub_curriculum_evaluation_query(user):
    """Permission query for SIS Sub Curriculum Evaluation"""
    return get_campus_permission_query("SIS Sub Curriculum Evaluation", user)


def sis_curriculum_evaluation_criteria_query(user):
    """Permission query for SIS Curriculum Evaluation Criteria"""
    return get_campus_permission_query("SIS Curriculum Evaluation Criteria", user)


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


def sis_timetable_instance_row_query(user):
    """Permission query for SIS Timetable Instance Row"""
    return get_campus_permission_query("SIS Timetable Instance Row", user)


def sis_teacher_timetable_query(user):
    """Permission query for SIS Teacher Timetable"""
    return get_campus_permission_query("SIS Teacher Timetable", user)


def sis_timetable_override_query(user):
    """Permission query for SIS Timetable Override"""
    return get_campus_permission_query("SIS Timetable Override", user)


def sis_class_log_score_query(user):
    """Permission query for SIS Class Log Score"""
    return get_campus_permission_query("SIS Class Log Score", user)


def sis_class_log_subject_query(user):
    """Permission query for SIS Class Log Subject"""
    return get_campus_permission_query("SIS Class Log Subject", user)


def sis_class_log_student_query(user):
    """Permission query for SIS Class Log Student"""
    return get_campus_permission_query("SIS Class Log Student", user)


def sis_homeroom_score_record_query(user):
    """Permission query for SIS Homeroom Score Record"""
    return get_campus_permission_query("SIS Homeroom Score Record", user)


# --- DocTypes bổ sung (campus_id, chưa có permission_query trước Phase 1) ---

def sis_announcement_query(user):
    return get_campus_permission_query("SIS Announcement", user)


def sis_award_category_query(user):
    return get_campus_permission_query("SIS Award Category", user)


def sis_award_record_query(user):
    return get_campus_permission_query("SIS Award Record", user)


def sis_bulk_import_job_query(user):
    return get_campus_permission_query("SIS Bulk Import Job", user)


def sis_bus_daily_trip_query(user):
    return get_campus_permission_query("SIS Bus Daily Trip", user)


def sis_bus_daily_trip_archive_query(user):
    return get_campus_permission_query("SIS Bus Daily Trip Archive", user)


def sis_bus_driver_query(user):
    return get_campus_permission_query("SIS Bus Driver", user)


def sis_bus_monitor_query(user):
    return get_campus_permission_query("SIS Bus Monitor", user)


def sis_bus_pickup_point_query(user):
    return get_campus_permission_query("SIS Bus Pickup Point", user)


def sis_bus_route_query(user):
    return get_campus_permission_query("SIS Bus Route", user)


def sis_bus_student_query(user):
    return get_campus_permission_query("SIS Bus Student", user)


def sis_bus_transportation_query(user):
    return get_campus_permission_query("SIS Bus Transportation", user)


def sis_class_attendance_query(user):
    return get_campus_permission_query("SIS Class Attendance", user)


def sis_contact_log_view_query(user):
    return get_campus_permission_query("SIS Contact Log View", user)


def sis_event_date_time_query(user):
    return get_campus_permission_query("SIS Event Date Time", user)


def sis_finance_student_query(user):
    return get_campus_permission_query("SIS Finance Student", user)


def sis_finance_year_query(user):
    return get_campus_permission_query("SIS Finance Year", user)


def sis_health_checkup_session_query(user):
    return get_campus_permission_query("SIS Health Checkup Session", user)


def sis_news_article_query(user):
    return get_campus_permission_query("SIS News Article", user)


def sis_news_tag_query(user):
    return get_campus_permission_query("SIS News Tag", user)


def sis_re_enrollment_query(user):
    return get_campus_permission_query("SIS Re-enrollment", user)


def sis_re_enrollment_config_query(user):
    return get_campus_permission_query("SIS Re-enrollment Config", user)


def sis_report_card_approval_config_query(user):
    return get_campus_permission_query("SIS Report Card Approval Config", user)


def sis_report_card_comment_title_query(user):
    return get_campus_permission_query("SIS Report Card Comment Title", user)


def sis_report_card_evaluation_criteria_query(user):
    return get_campus_permission_query("SIS Report Card Evaluation Criteria", user)


def sis_report_card_evaluation_scale_query(user):
    return get_campus_permission_query("SIS Report Card Evaluation Scale", user)


def sis_report_card_form_query(user):
    return get_campus_permission_query("SIS Report Card Form", user)


def sis_report_card_homeroom_comment_query(user):
    return get_campus_permission_query("SIS Report Card Homeroom Comment", user)


def sis_report_card_template_query(user):
    return get_campus_permission_query("SIS Report Card Template", user)


def sis_schedule_query(user):
    return get_campus_permission_query("SIS Schedule", user)


def sis_scholarship_period_query(user):
    return get_campus_permission_query("SIS Scholarship Period", user)


def sis_student_health_checkup_query(user):
    return get_campus_permission_query("SIS Student Health Checkup", user)


def sis_student_leave_request_query(user):
    return get_campus_permission_query("SIS Student Leave Request", user)


def sis_student_report_card_query(user):
    return get_campus_permission_query("SIS Student Report Card", user)


def sis_student_subject_query(user):
    return get_campus_permission_query("SIS Student Subject", user)


def sis_subject_department_query(user):
    return get_campus_permission_query("SIS Subject Department", user)


def sis_timetable_generation_session_query(user):
    return get_campus_permission_query("SIS Timetable Generation Session", user)


def sis_timetable_rule_set_query(user):
    return get_campus_permission_query("SIS Timetable Rule Set", user)

def sis_health_examination_query(user):
	"""Permission query for SIS Health Examination."""
	return get_campus_permission_query("SIS Health Examination", user)

def sis_daily_health_visit_query(user):
	"""Permission query for SIS Daily Health Visit."""
	return get_campus_permission_query("SIS Daily Health Visit", user)

def sis_health_report_query(user):
	"""Permission query for SIS Health Report."""
	return get_campus_permission_query("SIS Health Report", user)

def sis_scholarship_application_query(user):
	"""Permission query for SIS Scholarship Application."""
	return get_campus_permission_query("SIS Scholarship Application", user)

def sis_scholarship_recommendation_query(user):
	"""Permission query for SIS Scholarship Recommendation."""
	return get_campus_permission_query("SIS Scholarship Recommendation", user)

def sis_timetable_pinned_slot_query(user):
	"""Permission query for SIS Timetable Pinned Slot."""
	return get_campus_permission_query("SIS Timetable Pinned Slot", user)

def sis_event_attendance_query(user):
	"""Permission query for SIS Event Attendance."""
	return get_campus_permission_query("SIS Event Attendance", user)

def sis_bus_daily_trip_student_query(user):
	"""Permission query for SIS Bus Daily Trip Student."""
	return get_campus_permission_query("SIS Bus Daily Trip Student", user)

def sis_bus_route_student_query(user):
	"""Permission query for SIS Bus Route Student."""
	return get_campus_permission_query("SIS Bus Route Student", user)

def sis_menu_registration_query(user):
	"""Permission query for SIS Menu Registration."""
	return get_campus_permission_query("SIS Menu Registration", user)

def sis_menu_registration_period_query(user):
	"""Permission query for SIS Menu Registration Period."""
	return get_campus_permission_query("SIS Menu Registration Period", user)

def sis_teacher_education_stage_query(user):
	"""Permission query for SIS Teacher Education Stage."""
	return get_campus_permission_query("SIS Teacher Education Stage", user)

def sis_finance_order_query(user):
	"""Permission query for SIS Finance Order."""
	return get_campus_permission_query("SIS Finance Order", user)

def sis_finance_order_student_query(user):
	"""Permission query for SIS Finance Order Student."""
	return get_campus_permission_query("SIS Finance Order Student", user)

def sis_finance_order_item_query(user):
	"""Permission query for SIS Finance Order Item."""
	return get_campus_permission_query("SIS Finance Order Item", user)

def sis_finance_send_batch_query(user):
	"""Permission query for SIS Finance Send Batch."""
	return get_campus_permission_query("SIS Finance Send Batch", user)

def sis_finance_collection_log_query(user):
	"""Permission query for SIS Finance Collection Log."""
	return get_campus_permission_query("SIS Finance Collection Log", user)

def sis_finance_debit_note_history_query(user):
	"""Permission query for SIS Finance Debit Note History."""
	return get_campus_permission_query("SIS Finance Debit Note History", user)

def sis_finance_student_document_query(user):
	"""Permission query for SIS Finance Student Document."""
	return get_campus_permission_query("SIS Finance Student Document", user)

def sis_library_book_copy_query(user):
	"""Permission query for SIS Library Book Copy."""
	return get_campus_permission_query("SIS Library Book Copy", user)

def sis_library_transaction_query(user):
	"""Permission query for SIS Library Transaction."""
	return get_campus_permission_query("SIS Library Transaction", user)

def sis_library_title_query(user):
	"""Permission query for SIS Library Title."""
	return get_campus_permission_query("SIS Library Title", user)

def sis_library_event_query(user):
	"""Permission query for SIS Library Event."""
	return get_campus_permission_query("SIS Library Event", user)

def sis_discipline_record_query(user):
	"""Permission query for SIS Discipline Record."""
	return get_campus_permission_query("SIS Discipline Record", user)

def sis_discipline_classification_query(user):
	"""Permission query for SIS Discipline Classification."""
	return get_campus_permission_query("SIS Discipline Classification", user)

def sis_discipline_form_query(user):
	"""Permission query for SIS Discipline Form."""
	return get_campus_permission_query("SIS Discipline Form", user)

def sis_discipline_time_query(user):
	"""Permission query for SIS Discipline Time."""
	return get_campus_permission_query("SIS Discipline Time", user)

def sis_discipline_violation_query(user):
	"""Permission query for SIS Discipline Violation."""
	return get_campus_permission_query("SIS Discipline Violation", user)

def sis_first_aid_query(user):
	"""Permission query for SIS First Aid."""
	return get_campus_permission_query("SIS First Aid", user)

def sis_medicine_query(user):
	"""Permission query for SIS Medicine."""
	return get_campus_permission_query("SIS Medicine", user)

def sis_disease_classification_query(user):
	"""Permission query for SIS Disease Classification."""
	return get_campus_permission_query("SIS Disease Classification", user)

