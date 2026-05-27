app_name = "erp"
app_title = "Erp"
app_publisher = "Linh Nguyen"
app_description = "An app for WSHN’s internal applications."
app_email = "linh.nguyenhai@wellspring.edu.vn"
app_license = "mit"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "erp",
# 		"logo": "/assets/erp/logo.png",
# 		"title": "Erp",
# 		"route": "/erp",
# 		"has_permission": "erp.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/erp/css/erp.css"
# app_include_js = "/assets/erp/js/erp.js"

# include js, css files in header of web template
# web_include_css = "/assets/erp/css/erp.css"
# web_include_js = "/assets/erp/js/erp.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "erp/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "erp/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "erp.utils.jinja_methods",
# 	"filters": "erp.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "erp.install.before_install"
# Start Redis listeners — start_redis_listener đã gỡ khỏi ticket.py; tránh lỗi import khi install/start.
after_install = []

app_startup = []

# Uninstallation
# ------------

# before_uninstall = "erp.uninstall.before_uninstall"
# after_uninstall = "erp.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "erp.utils.before_app_install"
# after_app_install = "erp.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "erp.utils.before_app_uninstall"
# after_app_uninstall = "erp.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "erp.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

permission_query_conditions = {
	"SIS School Year": "erp.sis.utils.permission_query.sis_school_year_query",
	"SIS Education Stage": "erp.sis.utils.permission_query.sis_education_stage_query", 
	"SIS Education Grade": "erp.sis.utils.permission_query.sis_education_grade_query",
	"SIS Academic Program": "erp.sis.utils.permission_query.sis_academic_program_query",
	"SIS Timetable Subject": "erp.sis.utils.permission_query.sis_timetable_subject_query",
	"SIS Curriculum": "erp.sis.utils.permission_query.sis_curriculum_query",
	"SIS Actual Subject": "erp.sis.utils.permission_query.sis_actual_subject_query",
	"SIS Sub Curriculum": "erp.sis.utils.permission_query.sis_sub_curriculum_query",
	"SIS Sub Curriculum Evaluation": "erp.sis.utils.permission_query.sis_sub_curriculum_evaluation_query",
	"SIS Curriculum Evaluation Criteria": "erp.sis.utils.permission_query.sis_curriculum_evaluation_criteria_query",
	"SIS Subject": "erp.sis.utils.permission_query.sis_subject_query",
	"SIS Timetable Column": "erp.sis.utils.permission_query.sis_timetable_column_query",
	"SIS Calendar": "erp.sis.utils.permission_query.sis_calendar_query",
	"SIS Class": "erp.sis.utils.permission_query.sis_class_query",
	"SIS Teacher": "erp.sis.utils.permission_query.sis_teacher_query",
	"SIS Subject Assignment": "erp.sis.utils.permission_query.sis_subject_assignment_query",
	"SIS Timetable": "erp.sis.utils.permission_query.sis_timetable_query",
	"SIS Timetable Instance": "erp.sis.utils.permission_query.sis_timetable_instance_query",
	"SIS Timetable Instance Row": "erp.sis.utils.permission_query.sis_timetable_instance_row_query",
	"SIS Teacher Timetable": "erp.sis.utils.permission_query.sis_teacher_timetable_query",
	"SIS Timetable Override": "erp.sis.utils.permission_query.sis_timetable_override_query",
	"SIS Event": "erp.sis.utils.permission_query.sis_event_query",
	"SIS Event Student": "erp.sis.utils.permission_query.sis_event_student_query",
	"SIS Event Teacher": "erp.sis.utils.permission_query.sis_event_teacher_query",
	"SIS Student Timetable": "erp.sis.utils.permission_query.sis_student_timetable_query",
	"SIS Class Student": "erp.sis.utils.permission_query.sis_class_student_query",
	"SIS Photo": "erp.sis.utils.permission_query.sis_photo_query",
	"SIS Class Log Score": "erp.sis.utils.permission_query.sis_class_log_score_query",
	"SIS Class Log Subject": "erp.sis.utils.permission_query.sis_class_log_subject_query",
	"SIS Class Log Student": "erp.sis.utils.permission_query.sis_class_log_student_query",
	"SIS Homeroom Score Record": "erp.sis.utils.permission_query.sis_homeroom_score_record_query",
	# Bus, Finance, Report Card, Marcom, ... (Phase 1 bổ sung)
	"SIS Announcement": "erp.sis.utils.permission_query.sis_announcement_query",
	"SIS Award Category": "erp.sis.utils.permission_query.sis_award_category_query",
	"SIS Award Record": "erp.sis.utils.permission_query.sis_award_record_query",
	"SIS Bulk Import Job": "erp.sis.utils.permission_query.sis_bulk_import_job_query",
	"SIS Bus Daily Trip": "erp.sis.utils.permission_query.sis_bus_daily_trip_query",
	"SIS Bus Daily Trip Archive": "erp.sis.utils.permission_query.sis_bus_daily_trip_archive_query",
	"SIS Bus Driver": "erp.sis.utils.permission_query.sis_bus_driver_query",
	"SIS Bus Monitor": "erp.sis.utils.permission_query.sis_bus_monitor_query",
	"SIS Bus Pickup Point": "erp.sis.utils.permission_query.sis_bus_pickup_point_query",
	"SIS Bus Route": "erp.sis.utils.permission_query.sis_bus_route_query",
	"SIS Bus Student": "erp.sis.utils.permission_query.sis_bus_student_query",
	"SIS Bus Transportation": "erp.sis.utils.permission_query.sis_bus_transportation_query",
	"SIS Class Attendance": "erp.sis.utils.permission_query.sis_class_attendance_query",
	"SIS Contact Log View": "erp.sis.utils.permission_query.sis_contact_log_view_query",
	"SIS Event Date Time": "erp.sis.utils.permission_query.sis_event_date_time_query",
	"SIS Finance Student": "erp.sis.utils.permission_query.sis_finance_student_query",
	"SIS Finance Year": "erp.sis.utils.permission_query.sis_finance_year_query",
	"SIS Health Checkup Session": "erp.sis.utils.permission_query.sis_health_checkup_session_query",
	"SIS News Article": "erp.sis.utils.permission_query.sis_news_article_query",
	"SIS News Tag": "erp.sis.utils.permission_query.sis_news_tag_query",
	"SIS Re-enrollment": "erp.sis.utils.permission_query.sis_re_enrollment_query",
	"SIS Re-enrollment Config": "erp.sis.utils.permission_query.sis_re_enrollment_config_query",
	"SIS Report Card Approval Config": "erp.sis.utils.permission_query.sis_report_card_approval_config_query",
	"SIS Report Card Comment Title": "erp.sis.utils.permission_query.sis_report_card_comment_title_query",
	"SIS Report Card Evaluation Criteria": "erp.sis.utils.permission_query.sis_report_card_evaluation_criteria_query",
	"SIS Report Card Evaluation Scale": "erp.sis.utils.permission_query.sis_report_card_evaluation_scale_query",
	"SIS Report Card Form": "erp.sis.utils.permission_query.sis_report_card_form_query",
	"SIS Report Card Homeroom Comment": "erp.sis.utils.permission_query.sis_report_card_homeroom_comment_query",
	"SIS Report Card Template": "erp.sis.utils.permission_query.sis_report_card_template_query",
	"SIS Schedule": "erp.sis.utils.permission_query.sis_schedule_query",
	"SIS Scholarship Period": "erp.sis.utils.permission_query.sis_scholarship_period_query",
	"SIS Student Health Checkup": "erp.sis.utils.permission_query.sis_student_health_checkup_query",
	"SIS Student Leave Request": "erp.sis.utils.permission_query.sis_student_leave_request_query",
	"SIS Student Report Card": "erp.sis.utils.permission_query.sis_student_report_card_query",
	"SIS Student Subject": "erp.sis.utils.permission_query.sis_student_subject_query",
	"SIS Subject Department": "erp.sis.utils.permission_query.sis_subject_department_query",
	"SIS Timetable Generation Session": "erp.sis.utils.permission_query.sis_timetable_generation_session_query",
	"SIS Timetable Rule Set": "erp.sis.utils.permission_query.sis_timetable_rule_set_query",
	# CRM Doctypes
	"CRM Lead": "erp.crm.utils.permission_query.crm_lead_query",
	"CRM Exam": "erp.crm.utils.permission_query.crm_exam_query",
	"CRM Issue": "erp.crm.utils.permission_query.crm_issue_query",
	# LMS
	"LMS Program": "erp.lms.utils.permissions.lms_program_query",
	"LMS Course": "erp.lms.utils.permissions.lms_course_query",
	"LMS Course Section": "erp.lms.utils.permissions.lms_course_section_query",
	"LMS Enrollment": "erp.lms.utils.permissions.lms_enrollment_query",
	"LMS Video Asset": "erp.lms.utils.permissions.lms_video_asset_query",
	"LMS Page": "erp.lms.utils.permissions.lms_course_query",
	"LMS File": "erp.lms.utils.permissions.lms_course_query",
	"LMS Assignment": "erp.lms.utils.permissions.lms_course_query",
	"LMS Grade Column": "erp.lms.utils.permissions.lms_course_section_query",
	"LMS Grade Group": "erp.lms.utils.permissions.lms_course_section_query",
	"LMS Announcement": "erp.lms.utils.permissions.lms_announcement_query",
	"LMS Quiz": "erp.lms.utils.permissions.lms_course_query",
	"LMS Question Bank": "erp.lms.utils.permissions.lms_program_query",
	"LMS Discussion": "erp.lms.utils.permissions.lms_course_query",
	"LMS Group": "erp.lms.utils.permissions.lms_course_section_query",
	"LMS Calendar Event": "erp.lms.utils.permissions.lms_course_query",
	"LMS Outcome": "erp.lms.utils.permissions.lms_course_query",
	"LMS Mastery Rule": "erp.lms.utils.permissions.lms_course_query",
	"LMS Grade Sync Rule": "erp.lms.utils.permissions.lms_course_section_query",
	"LMS Blueprint Course": "erp.lms.utils.permissions.lms_course_query",
	# IT Support ticket
	"ERP IT Support Ticket": "erp.it_support.permissions.it_support_ticket_query",
	"SIS Health Examination": "erp.sis.utils.permission_query.sis_health_examination_query",
	"SIS Daily Health Visit": "erp.sis.utils.permission_query.sis_daily_health_visit_query",
	"SIS Health Report": "erp.sis.utils.permission_query.sis_health_report_query",
	"SIS Scholarship Application": "erp.sis.utils.permission_query.sis_scholarship_application_query",
	"SIS Scholarship Recommendation": "erp.sis.utils.permission_query.sis_scholarship_recommendation_query",
	"SIS Timetable Pinned Slot": "erp.sis.utils.permission_query.sis_timetable_pinned_slot_query",
	"SIS Event Attendance": "erp.sis.utils.permission_query.sis_event_attendance_query",
	"Feedback": "erp.utils.campus_permission_query.feedback_query",
	"SIS Bus Daily Trip Student": "erp.sis.utils.permission_query.sis_bus_daily_trip_student_query",
	"SIS Bus Route Student": "erp.sis.utils.permission_query.sis_bus_route_student_query",
	"SIS Menu Registration": "erp.sis.utils.permission_query.sis_menu_registration_query",
	"SIS Menu Registration Period": "erp.sis.utils.permission_query.sis_menu_registration_period_query",
	"SIS Teacher Education Stage": "erp.sis.utils.permission_query.sis_teacher_education_stage_query",
	"SIS Finance Order": "erp.sis.utils.permission_query.sis_finance_order_query",
	"SIS Finance Order Student": "erp.sis.utils.permission_query.sis_finance_order_student_query",
	"SIS Finance Order Item": "erp.sis.utils.permission_query.sis_finance_order_item_query",
	"SIS Finance Send Batch": "erp.sis.utils.permission_query.sis_finance_send_batch_query",
	"SIS Finance Collection Log": "erp.sis.utils.permission_query.sis_finance_collection_log_query",
	"SIS Finance Debit Note History": "erp.sis.utils.permission_query.sis_finance_debit_note_history_query",
	"SIS Finance Student Document": "erp.sis.utils.permission_query.sis_finance_student_document_query",
	"SIS Library Book Copy": "erp.sis.utils.permission_query.sis_library_book_copy_query",
	"SIS Library Transaction": "erp.sis.utils.permission_query.sis_library_transaction_query",
	"SIS Library Title": "erp.sis.utils.permission_query.sis_library_title_query",
	"SIS Library Event": "erp.sis.utils.permission_query.sis_library_event_query",
	"CRM Guardian": "erp.crm.utils.permission_query.crm_guardian_query",
	"CRM Family": "erp.crm.utils.permission_query.crm_family_query",
	"CRM Admission Course": "erp.crm.utils.permission_query.crm_admission_course_query",
	"CRM Admission Course Student": "erp.crm.utils.permission_query.crm_admission_course_student_query",
	"CRM Admission Entrance Exam": "erp.crm.utils.permission_query.crm_admission_entrance_exam_query",
	"CRM Admission Entrance Exam Student": "erp.crm.utils.permission_query.crm_admission_entrance_exam_student_query",
	"CRM Admission Event": "erp.crm.utils.permission_query.crm_admission_event_query",
	"CRM Admission Event Student": "erp.crm.utils.permission_query.crm_admission_event_student_query",
	"CRM Exam Score": "erp.crm.utils.permission_query.crm_exam_score_query",
	"CRM Lead Note": "erp.crm.utils.permission_query.crm_lead_note_query",
	"CRM Lead Step History": "erp.crm.utils.permission_query.crm_lead_step_history_query",
	"Portal API Error": "erp.utils.campus_permission_query.portal_api_error_query",
	"Portal Guardian Activity": "erp.utils.campus_permission_query.portal_guardian_activity_query",
	"LMS Submission": "erp.lms.utils.permissions.lms_submission_query",
	"LMS Grade Entry": "erp.lms.utils.permissions.lms_grade_entry_query",
	"LMS Quiz Attempt": "erp.lms.utils.permissions.lms_quiz_attempt_query",
	"LMS Course Progress": "erp.lms.utils.permissions.lms_course_progress_query",
	"LMS Content Progress": "erp.lms.utils.permissions.lms_content_progress_query",
	"LMS Engagement Score": "erp.lms.utils.permissions.lms_engagement_score_query",
	"LMS Group Membership": "erp.lms.utils.permissions.lms_group_membership_query",
	"LMS Grade Sync Log": "erp.lms.utils.permissions.lms_grade_sync_log_query",
	"LMS Activity Log": "erp.lms.utils.permissions.lms_activity_log_query",
	"LMS Conversation": "erp.lms.utils.permissions.lms_conversation_query",
	"LMS Module": "erp.lms.utils.permissions.lms_module_query",
	"LMS External Tool": "erp.lms.utils.permissions.lms_external_tool_query",
	"LMS Blueprint Sync Log": "erp.lms.utils.permissions.lms_blueprint_sync_log_query",
	"ERP Administrative Room Yearly Assignment": "erp.utils.campus_permission_query.erp_administrative_room_yearly_assignment_query",
	"ERP Administrative Ticket": "erp.utils.campus_permission_query.erp_administrative_ticket_query",
	"ERP Administrative Facility Handover": "erp.utils.campus_permission_query.erp_administrative_facility_handover_query",
	"ERP Administrative Inventory Check": "erp.utils.campus_permission_query.erp_administrative_inventory_check_query",
	"ERP Administrative Room Activity Log": "erp.utils.campus_permission_query.erp_administrative_room_activity_log_query",
	"ERP Administrative Room Facility Equipment": "erp.utils.campus_permission_query.erp_administrative_room_facility_equipment_query",
	"ERP Inventory Device": "erp.utils.campus_permission_query.erp_inventory_device_query",
	"ERP Inventory Inspection": "erp.utils.campus_permission_query.erp_inventory_inspection_query",
	"ERP Inventory Handover Log": "erp.utils.campus_permission_query.erp_inventory_handover_log_query",
	"ERP Inventory Activity Log": "erp.utils.campus_permission_query.erp_inventory_activity_log_query",
	"PM Task": "erp.utils.campus_permission_query.pm_task_query",
	"PM Meeting": "erp.utils.campus_permission_query.pm_meeting_query",
	"PM Project Member": "erp.utils.campus_permission_query.pm_project_member_query",
	"PM Resource": "erp.utils.campus_permission_query.pm_resource_query",
	"PM Requirement": "erp.utils.campus_permission_query.pm_requirement_query",
	"PM Change Log": "erp.utils.campus_permission_query.pm_change_log_query",
	"PM Project Invitation": "erp.utils.campus_permission_query.pm_project_invitation_query",
	"SIS Discipline Record": "erp.sis.utils.permission_query.sis_discipline_record_query",
	"SIS Discipline Classification": "erp.sis.utils.permission_query.sis_discipline_classification_query",
	"SIS Discipline Form": "erp.sis.utils.permission_query.sis_discipline_form_query",
	"SIS Discipline Time": "erp.sis.utils.permission_query.sis_discipline_time_query",
	"SIS Discipline Violation": "erp.sis.utils.permission_query.sis_discipline_violation_query",
	"SIS First Aid": "erp.sis.utils.permission_query.sis_first_aid_query",
	"SIS Medicine": "erp.sis.utils.permission_query.sis_medicine_query",
	"SIS Disease Classification": "erp.sis.utils.permission_query.sis_disease_classification_query",
	# Pre-Phase-2 gap (đã có campus_id)
	"ERP Administrative Room": "erp.utils.campus_permission_query.erp_administrative_room_query",
	"ERP Administrative Building": "erp.utils.campus_permission_query.erp_administrative_building_query",
	"ERP Administrative Academic Year Closure": "erp.utils.campus_permission_query.erp_administrative_academic_year_closure_query",
	"CRM PIC Config": "erp.utils.campus_permission_query.crm_pic_config_query",
	"CRM Student": "erp.utils.campus_permission_query.crm_student_query",
	"PM Project": "erp.utils.campus_permission_query.pm_project_query",
}

has_permission = {
	"SIS School Year": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Education Stage": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Education Grade": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Academic Program": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Timetable Subject": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Curriculum": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Actual Subject": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Sub Curriculum": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Sub Curriculum Evaluation": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Curriculum Evaluation Criteria": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Subject": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Timetable Column": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Calendar": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Class": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Teacher": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Subject Assignment": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Timetable": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Timetable Instance": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Timetable Instance Row": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Teacher Timetable": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Timetable Override": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Event": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Event Student": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Event Teacher": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Student Timetable": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Class Student": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Photo": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Class Log Score": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Class Log Subject": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Class Log Student": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Homeroom Score Record": "erp.sis.utils.campus_permissions.has_campus_permission",
	# Bus, Finance, Report Card, Marcom, ... (Phase 1 bổ sung)
	"SIS Announcement": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Award Category": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Award Record": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Bulk Import Job": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Bus Daily Trip": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Bus Daily Trip Archive": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Bus Driver": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Bus Monitor": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Bus Pickup Point": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Bus Route": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Bus Student": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Bus Transportation": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Class Attendance": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Contact Log View": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Event Date Time": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Finance Student": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Finance Year": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Health Checkup Session": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS News Article": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS News Tag": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Re-enrollment": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Re-enrollment Config": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Report Card Approval Config": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Report Card Comment Title": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Report Card Evaluation Criteria": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Report Card Evaluation Scale": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Report Card Form": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Report Card Homeroom Comment": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Report Card Template": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Schedule": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Scholarship Period": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Student Health Checkup": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Student Leave Request": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Student Report Card": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Student Subject": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Subject Department": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Timetable Generation Session": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Timetable Rule Set": "erp.sis.utils.campus_permissions.has_campus_permission",
	# CRM Doctypes
	"CRM Lead": "erp.crm.utils.permission_query.has_crm_permission",
	"CRM Exam": "erp.crm.utils.permission_query.has_crm_permission",
	"CRM Issue": "erp.crm.utils.permission_query.has_crm_permission",
	# LMS
	"LMS Program": "erp.lms.utils.permissions.has_lms_campus_permission",
	"LMS Course": "erp.lms.utils.permissions.has_lms_campus_permission",
	"LMS Course Section": "erp.lms.utils.permissions.has_lms_campus_permission",
	"LMS Enrollment": "erp.lms.utils.permissions.has_lms_campus_permission",
	"LMS Video Asset": "erp.lms.utils.permissions.has_lms_campus_permission",
	"LMS Page": "erp.lms.utils.permissions.has_lms_campus_permission",
	"LMS File": "erp.lms.utils.permissions.has_lms_campus_permission",
	"LMS Assignment": "erp.lms.utils.permissions.has_lms_campus_permission",
	"LMS Grade Column": "erp.lms.utils.permissions.has_lms_campus_permission",
	"LMS Grade Group": "erp.lms.utils.permissions.has_lms_campus_permission",
	"LMS Announcement": "erp.lms.utils.permissions.has_lms_campus_permission",
	"LMS Quiz": "erp.lms.utils.permissions.has_lms_campus_permission",
	"LMS Question Bank": "erp.lms.utils.permissions.has_lms_campus_permission",
	"LMS Discussion": "erp.lms.utils.permissions.has_lms_campus_permission",
	"LMS Group": "erp.lms.utils.permissions.has_lms_campus_permission",
	"LMS Calendar Event": "erp.lms.utils.permissions.has_lms_campus_permission",
	"LMS Outcome": "erp.lms.utils.permissions.has_lms_campus_permission",
	"LMS Mastery Rule": "erp.lms.utils.permissions.has_lms_campus_permission",
	"LMS Grade Sync Rule": "erp.lms.utils.permissions.has_lms_campus_permission",
	"LMS Grade Sync Log": "erp.lms.utils.permissions.has_lms_campus_permission",
	"LMS Blueprint Course": "erp.lms.utils.permissions.has_lms_campus_permission",
	"LMS Blueprint Sync Log": "erp.lms.utils.permissions.has_lms_campus_permission",
	# IT Support ticket
	"ERP IT Support Ticket": "erp.it_support.permissions.has_it_support_ticket_permission",
	"SIS Health Examination": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Daily Health Visit": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Health Report": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Scholarship Application": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Scholarship Recommendation": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Timetable Pinned Slot": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Event Attendance": "erp.sis.utils.campus_permissions.has_campus_permission",
	"Feedback": "erp.utils.campus_permission_query.has_campus_doctype_permission",
	"SIS Bus Daily Trip Student": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Bus Route Student": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Menu Registration": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Menu Registration Period": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Teacher Education Stage": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Finance Order": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Finance Order Student": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Finance Order Item": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Finance Send Batch": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Finance Collection Log": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Finance Debit Note History": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Finance Student Document": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Library Book Copy": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Library Transaction": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Library Title": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Library Event": "erp.sis.utils.campus_permissions.has_campus_permission",
	"CRM Guardian": "erp.crm.utils.permission_query.has_crm_permission",
	"CRM Family": "erp.crm.utils.permission_query.has_crm_permission",
	"CRM Admission Course": "erp.crm.utils.permission_query.has_crm_permission",
	"CRM Admission Course Student": "erp.crm.utils.permission_query.has_crm_permission",
	"CRM Admission Entrance Exam": "erp.crm.utils.permission_query.has_crm_permission",
	"CRM Admission Entrance Exam Student": "erp.crm.utils.permission_query.has_crm_permission",
	"CRM Admission Event": "erp.crm.utils.permission_query.has_crm_permission",
	"CRM Admission Event Student": "erp.crm.utils.permission_query.has_crm_permission",
	"CRM Exam Score": "erp.crm.utils.permission_query.has_crm_permission",
	"CRM Lead Note": "erp.crm.utils.permission_query.has_crm_permission",
	"CRM Lead Step History": "erp.crm.utils.permission_query.has_crm_permission",
	"Portal API Error": "erp.utils.campus_permission_query.has_campus_doctype_permission",
	"Portal Guardian Activity": "erp.utils.campus_permission_query.has_campus_doctype_permission",
	"LMS Submission": "erp.lms.utils.permissions.has_lms_campus_permission",
	"LMS Grade Entry": "erp.lms.utils.permissions.has_lms_campus_permission",
	"LMS Quiz Attempt": "erp.lms.utils.permissions.has_lms_campus_permission",
	"LMS Course Progress": "erp.lms.utils.permissions.has_lms_campus_permission",
	"LMS Content Progress": "erp.lms.utils.permissions.has_lms_campus_permission",
	"LMS Engagement Score": "erp.lms.utils.permissions.has_lms_campus_permission",
	"LMS Group Membership": "erp.lms.utils.permissions.has_lms_campus_permission",
	"LMS Activity Log": "erp.lms.utils.permissions.has_lms_campus_permission",
	"LMS Conversation": "erp.lms.utils.permissions.has_lms_campus_permission",
	"LMS Module": "erp.lms.utils.permissions.has_lms_campus_permission",
	"LMS External Tool": "erp.lms.utils.permissions.has_lms_campus_permission",
	"ERP Administrative Room Yearly Assignment": "erp.utils.campus_permission_query.has_campus_doctype_permission",
	"ERP Administrative Ticket": "erp.utils.campus_permission_query.has_campus_doctype_permission",
	"ERP Administrative Facility Handover": "erp.utils.campus_permission_query.has_campus_doctype_permission",
	"ERP Administrative Inventory Check": "erp.utils.campus_permission_query.has_campus_doctype_permission",
	"ERP Administrative Room Activity Log": "erp.utils.campus_permission_query.has_campus_doctype_permission",
	"ERP Administrative Room Facility Equipment": "erp.utils.campus_permission_query.has_campus_doctype_permission",
	"ERP Inventory Device": "erp.utils.campus_permission_query.has_campus_doctype_permission",
	"ERP Inventory Inspection": "erp.utils.campus_permission_query.has_campus_doctype_permission",
	"ERP Inventory Handover Log": "erp.utils.campus_permission_query.has_campus_doctype_permission",
	"ERP Inventory Activity Log": "erp.utils.campus_permission_query.has_campus_doctype_permission",
	"PM Task": "erp.utils.campus_permission_query.has_campus_doctype_permission",
	"PM Meeting": "erp.utils.campus_permission_query.has_campus_doctype_permission",
	"PM Project Member": "erp.utils.campus_permission_query.has_campus_doctype_permission",
	"PM Resource": "erp.utils.campus_permission_query.has_campus_doctype_permission",
	"PM Requirement": "erp.utils.campus_permission_query.has_campus_doctype_permission",
	"PM Change Log": "erp.utils.campus_permission_query.has_campus_doctype_permission",
	"PM Project Invitation": "erp.utils.campus_permission_query.has_campus_doctype_permission",
	"SIS Discipline Record": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Discipline Classification": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Discipline Form": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Discipline Time": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Discipline Violation": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS First Aid": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Medicine": "erp.sis.utils.campus_permissions.has_campus_permission",
	"SIS Disease Classification": "erp.sis.utils.campus_permissions.has_campus_permission",
	# Pre-Phase-2 gap (đã có campus_id)
	"ERP Administrative Room": "erp.utils.campus_permission_query.has_campus_doctype_permission",
	"ERP Administrative Building": "erp.utils.campus_permission_query.has_campus_doctype_permission",
	"ERP Administrative Academic Year Closure": "erp.utils.campus_permission_query.has_campus_doctype_permission",
	"CRM PIC Config": "erp.utils.campus_permission_query.has_campus_doctype_permission",
	"CRM Student": "erp.utils.campus_permission_query.has_campus_doctype_permission",
	"PM Project": "erp.utils.campus_permission_query.has_campus_doctype_permission",
}

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# doc_events = {
#     "Event": "erp.event.get_events"
# }

# User Management Hooks - Trigger webhooks khi User thay đổi
doc_events = {
	"User": {
		"after_insert": [
			"erp.common.user_hooks.trigger_user_webhooks",
			"erp.sis.utils.campus_permissions.create_user_campus_preference",
		],
		"on_update": [
			"erp.common.user_hooks.trigger_user_webhooks"
		],
		"on_trash": [
			"erp.common.user_hooks.trigger_user_webhooks"
		]
	},
	"ERP Administrative Room": {
		"after_insert": [
			"erp.common.room_events.on_room_after_insert",
			"erp.common.user_hooks.trigger_room_webhooks"
		],
		"on_update": [
			"erp.common.room_events.on_room_on_update",
			"erp.common.user_hooks.trigger_room_webhooks"
		],
		"on_trash": [
			"erp.common.room_events.on_room_on_trash",
			"erp.common.user_hooks.trigger_room_webhooks"
		]
	},
	# Push notification when ERP Notification is created
	"ERP Notification": {
		"after_insert": "erp.api.parent_portal.realtime_notification.on_notification_created"
	},
	# Cache Invalidation Hooks for Subject Assignment & Timetable
	"SIS Subject Assignment": {
		"after_insert": "erp.api.erp_sis.utils.assignment_cache.on_subject_assignment_change",
		"on_update": "erp.api.erp_sis.utils.assignment_cache.on_subject_assignment_change",
		"after_delete": "erp.api.erp_sis.utils.assignment_cache.on_subject_assignment_change"
	},
	"SIS Subject": {
		"after_insert": "erp.api.erp_sis.utils.assignment_cache.on_subject_change",
		"on_update": "erp.api.erp_sis.utils.assignment_cache.on_subject_change",
		"after_delete": "erp.api.erp_sis.utils.assignment_cache.on_subject_change"
	},
	"SIS Timetable Instance Row": {
		"after_insert": "erp.api.erp_sis.utils.assignment_cache.on_timetable_instance_row_change",
		"on_update": "erp.api.erp_sis.utils.assignment_cache.on_timetable_instance_row_change",
		"after_delete": "erp.api.erp_sis.utils.assignment_cache.on_timetable_instance_row_change"
	},
	# Logging hooks for audit trail
	"File": {
		"after_insert": [
			"erp.observability.audit.log_file_upload"
		],
		"on_update": [
			"erp.observability.audit.log_file_update"
		],
		"on_trash": [
			"erp.observability.audit.log_file_delete"
		]
	},
	"Student": {
		"after_insert": [
			"erp.observability.audit.log_create"
		],
		"on_update": [
			"erp.observability.audit.log_update"
		],
		"on_trash": [
			"erp.observability.audit.log_delete"
		],
		"on_cancel": [
			"erp.observability.audit.log_cancel"
		]
	},
	"Guardian": {
		"after_insert": [
			"erp.observability.audit.log_create"
		],
		"on_update": [
			"erp.observability.audit.log_update"
		],
		"on_trash": [
			"erp.observability.audit.log_delete"
		]
	},
	"SIS Class Student": {
		"after_insert": [
			"erp.observability.audit.log_create"
		],
		"on_update": [
			"erp.observability.audit.log_update"
		],
		"on_trash": [
			"erp.observability.audit.log_delete"
		]
	},
	"SIS Class Attendance": {
		"after_insert": [
			"erp.observability.audit.log_create"
		],
		"on_update": [
			"erp.observability.audit.log_update"
		],
		"on_trash": [
			"erp.observability.audit.log_delete"
		]
	},
	"SIS Event": {
		"after_insert": [
			"erp.observability.audit.log_create"
		],
		"on_update": [
			"erp.observability.audit.log_update"
		],
		"on_trash": [
			"erp.observability.audit.log_delete"
		]
	},
	"SIS Class": {
		"after_insert": [
			"erp.observability.audit.log_create"
		],
		"on_update": [
			"erp.api.erp_administrative.room.sync_class_room_assignment",
			"erp.api.erp_administrative.room.sync_class_homeroom_teachers_to_room_pic",
			"erp.observability.audit.log_update"
		],
		"on_trash": [
			"erp.observability.audit.log_delete"
		]
	},
	"SIS Teacher": {
		"after_insert": [
			"erp.observability.audit.log_create"
		],
		"on_update": [
			"erp.observability.audit.log_update"
		],
		"on_trash": [
			"erp.observability.audit.log_delete"
		]
	},
	"SIS Subject": {
		"after_insert": [
			"erp.observability.audit.log_create"
		],
		"on_update": [
			"erp.observability.audit.log_update"
		],
		"on_trash": [
			"erp.observability.audit.log_delete"
		]
	},
	"SIS Curriculum": {
		"after_insert": [
			"erp.observability.audit.log_create"
		],
		"on_update": [
			"erp.observability.audit.log_update"
		],
		"on_trash": [
			"erp.observability.audit.log_delete"
		]
	},
	"SIS Actual Subject": {
		"after_insert": [
			"erp.observability.audit.log_create"
		],
		"on_update": [
			"erp.observability.audit.log_update"
		],
		"on_trash": [
			"erp.observability.audit.log_delete"
		]
	},
	"SIS Timetable": {
		"after_insert": [
			"erp.observability.audit.log_create"
		],
		"on_update": [
			"erp.observability.audit.log_update"
		],
		"on_trash": [
			"erp.observability.audit.log_delete"
		]
	},
	"SIS Timetable Subject": {
		"after_insert": [
			"erp.observability.audit.log_create"
		],
		"on_update": [
			"erp.observability.audit.log_update"
		],
		"on_trash": [
			"erp.observability.audit.log_delete"
		]
	},
	"SIS Photo": {
		"after_insert": [
			"erp.observability.audit.log_create"
		],
		"on_update": [
			"erp.observability.audit.log_update"
		],
		"on_trash": [
			"erp.observability.audit.log_delete"
		]
	},
	"SIS School Year": {
		"after_insert": [
			"erp.observability.audit.log_create"
		],
		"on_update": [
			"erp.observability.audit.log_update"
		],
		"on_trash": [
			"erp.observability.audit.log_delete"
		]
	},
	"SIS Education Stage": {
		"after_insert": [
			"erp.observability.audit.log_create"
		],
		"on_update": [
			"erp.observability.audit.log_update"
		],
		"on_trash": [
			"erp.observability.audit.log_delete"
		]
	},
	"SIS Education Grade": {
		"after_insert": [
			"erp.observability.audit.log_create"
		],
		"on_update": [
			"erp.observability.audit.log_update"
		],
		"on_trash": [
			"erp.observability.audit.log_delete"
		]
	},
	"SIS Academic Program": {
		"after_insert": [
			"erp.observability.audit.log_create"
		],
		"on_update": [
			"erp.observability.audit.log_update"
		],
		"on_trash": [
			"erp.observability.audit.log_delete"
		]
	},
	"SIS Sub Curriculum": {
		"after_insert": [
			"erp.observability.audit.log_create"
		],
		"on_update": [
			"erp.observability.audit.log_update"
		],
		"on_trash": [
			"erp.observability.audit.log_delete"
		]
	},
	"SIS Calendar": {
		"after_insert": [
			"erp.observability.audit.log_create"
		],
		"on_update": [
			"erp.observability.audit.log_update"
		],
		"on_trash": [
			"erp.observability.audit.log_delete"
		]
	},
	"SIS Subject Assignment": {
		"after_insert": [
			"erp.observability.audit.log_create"
		],
		"on_update": [
			"erp.observability.audit.log_update"
		],
		"on_trash": [
			"erp.observability.audit.log_delete"
		]
	},
	"Feedback": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
		"after_insert": [
			"erp.observability.audit.log_create"
		],
		"on_update": [
			"erp.observability.audit.log_update"
		],
		"on_trash": [
			"erp.observability.audit.log_delete"
		]
	},
	"SIS Student Leave Request": {
		"after_insert": [
			"erp.observability.audit.log_create"
		],
		"on_update": [
			"erp.observability.audit.log_update"
		],
		"on_trash": [
			"erp.observability.audit.log_delete"
		]
	},
	"SIS Announcement": {
		"after_insert": [
			"erp.observability.audit.log_create"
		],
		"on_update": [
			"erp.observability.audit.log_update"
		],
		"on_trash": [
			"erp.observability.audit.log_delete"
		]
	},
	"SIS News Article": {
		"after_insert": [
			"erp.observability.audit.log_create"
		],
		"on_update": [
			"erp.observability.audit.log_update"
		],
		"on_trash": [
			"erp.observability.audit.log_delete"
		]
	},
	"Daily Menu": {
		"after_insert": [
			"erp.observability.audit.log_create"
		],
		"on_update": [
			"erp.observability.audit.log_update"
		],
		"on_trash": [
			"erp.observability.audit.log_delete"
		]
	},
	"SIS Bus Route": {
		"after_insert": [
			"erp.observability.audit.log_create"
		],
		"on_update": [
			"erp.observability.audit.log_update"
		],
		"on_trash": [
			"erp.observability.audit.log_delete"
		]
	},
	"SIS Bus Student": {
		"after_insert": [
			"erp.observability.audit.log_create"
		],
		"on_update": [
			"erp.observability.audit.log_update"
		],
		"on_trash": [
			"erp.observability.audit.log_delete"
		]
	},
	"SIS Bus Daily Trip": {
		"after_insert": [
			"erp.observability.audit.log_create"
		],
		"on_update": [
			"erp.observability.audit.log_update"
		],
		"on_trash": [
			"erp.observability.audit.log_delete"
		]
	},
	"SIS Badge": {
		"after_insert": [
			"erp.observability.audit.log_create"
		],
		"on_update": [
			"erp.observability.audit.log_update"
		],
		"on_trash": [
			"erp.observability.audit.log_delete"
		]
	},
	"SIS Student Timetable": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"SIS Teacher Timetable": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"SIS Timetable Override": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"SIS Event Date Time": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"LMS Announcement": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"CRM Issue": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"ERP IT Support Ticket": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"SIS Health Examination": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"SIS Daily Health Visit": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"SIS Health Report": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"SIS Scholarship Application": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"SIS Scholarship Recommendation": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"SIS Timetable Pinned Slot": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"SIS Event Attendance": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"SIS Bus Daily Trip Student": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"SIS Bus Route Student": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"SIS Menu Registration": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"SIS Menu Registration Period": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"SIS Teacher Education Stage": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"SIS Finance Order": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"SIS Finance Order Student": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"SIS Finance Order Item": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"SIS Finance Send Batch": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"SIS Finance Collection Log": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"SIS Finance Debit Note History": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"SIS Finance Student Document": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"SIS Library Book Copy": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"SIS Library Transaction": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"SIS Library Title": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"SIS Library Event": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"CRM Guardian": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"CRM Family": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"CRM Admission Course": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"CRM Admission Course Student": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"CRM Admission Entrance Exam": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"CRM Admission Entrance Exam Student": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"CRM Admission Event": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"CRM Admission Event Student": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"CRM Exam Score": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"CRM Lead Note": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"CRM Lead Step History": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"Portal API Error": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"Portal Guardian Activity": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"LMS Submission": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"LMS Grade Entry": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"LMS Quiz Attempt": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"LMS Course Progress": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"LMS Content Progress": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"LMS Engagement Score": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"LMS Group Membership": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"LMS Grade Sync Log": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"LMS Activity Log": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"LMS Conversation": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"LMS Module": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"LMS External Tool": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"LMS Blueprint Sync Log": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"ERP Administrative Room Yearly Assignment": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"ERP Administrative Ticket": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"ERP Administrative Facility Handover": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"ERP Administrative Inventory Check": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"ERP Administrative Room Activity Log": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"ERP Administrative Room Facility Equipment": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"ERP Inventory Device": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"ERP Inventory Inspection": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"ERP Inventory Handover Log": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"ERP Inventory Activity Log": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"PM Task": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"PM Meeting": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"PM Project Member": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"PM Resource": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"PM Requirement": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"PM Change Log": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"PM Project Invitation": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"SIS Discipline Record": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"SIS Discipline Classification": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"SIS Discipline Form": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"SIS Discipline Time": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"SIS Discipline Violation": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"SIS First Aid": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"SIS Medicine": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
	"SIS Disease Classification": {
		"before_insert": "erp.utils.campus_document.inject_campus_id",
	},
}

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"erp.tasks.all"
# 	],
# 	"daily": [
# 		"erp.tasks.daily"
# 	],
# 	"hourly": [
# 		"erp.tasks.hourly"
# 	],
# 	"weekly": [
# 		"erp.tasks.weekly"
# 	],
# 	"monthly": [
# 		"erp.tasks.monthly"
# 	]
# }

# Testing
# -------

# before_tests = "erp.install.before_tests"

# Overriding Methods
# ------------------------------
#
# Whitelisted methods
# -------------------
whitelisted_methods = [
	"erp.api.bulk_import.upload_bulk_import_file_v2",
	"erp.api.bulk_import.start_bulk_import",
	"erp.api.bulk_import.get_bulk_import_status",
	"erp.api.bulk_import.download_template",
	"erp.api.bulk_import.reload_whitelist",
	"erp.api.erp_sis.sub_curriculum.get_sub_curriculums",
	"erp.api.erp_sis.sub_curriculum.get_sub_curriculum_by_id",
	"erp.api.erp_sis.sub_curriculum.create_sub_curriculum",
	"erp.api.erp_sis.sub_curriculum.update_sub_curriculum",
	"erp.api.erp_sis.sub_curriculum.delete_sub_curriculum",
	"erp.api.erp_sis.sub_curriculum.get_sub_curriculums_for_selection",
	"erp.api.erp_sis.sub_curriculum.get_sub_curriculums_with_criteria",
	"erp.api.erp_sis.sub_curriculum_evaluation.get_sub_curriculum_evaluations",
	"erp.api.erp_sis.sub_curriculum_evaluation.get_sub_curriculum_evaluation_by_id",
	"erp.api.erp_sis.sub_curriculum_evaluation.create_sub_curriculum_evaluation",
	"erp.api.erp_sis.sub_curriculum_evaluation.update_sub_curriculum_evaluation",
	"erp.api.erp_sis.sub_curriculum_evaluation.delete_sub_curriculum_evaluation",
	"erp.api.erp_sis.curriculum_evaluation_criteria.get_curriculum_evaluation_criteria",
	"erp.api.erp_sis.curriculum_evaluation_criteria.get_curriculum_evaluation_criteria_by_id",
	"erp.api.erp_sis.curriculum_evaluation_criteria.create_curriculum_evaluation_criteria",
	"erp.api.erp_sis.curriculum_evaluation_criteria.update_curriculum_evaluation_criteria",
	"erp.api.erp_sis.curriculum_evaluation_criteria.delete_curriculum_evaluation_criteria",
	# File download endpoints
	"erp.api.parent_portal.file_download.download_leave_attachment",
	"erp.api.erp_sis.file_download.download_leave_attachment",
	# Analytics dashboard endpoints
	"erp.api.analytics.dashboard_api.get_dashboard_summary",
	"erp.api.analytics.dashboard_api.get_user_trends",
	"erp.api.analytics.dashboard_api.get_module_usage",
	"erp.api.analytics.dashboard_api.get_feedback_ratings",
	"erp.api.analytics.dashboard_api.get_all_feedback_ratings",
	"erp.api.analytics.dashboard_api.trigger_analytics_aggregation",
	"erp.api.observability.prometheus.metrics",
]

# Allow guest access for testing
guest_method_whitelist = [
	"erp.api.bulk_import.reload_whitelist",
	"erp.api.observability.prometheus.metrics",
	# IT Support — email-service (Phase 1 HTTP, cần X-IT-Support-Key nếu cấu hình)
	"erp.api.erp_it_support.email_ticket.create_from_email",
	"erp.api.erp_it_support.email_ticket.get_ticket_info_for_email",
]

# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "erp.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "erp.task.get_dashboard_data"
# }

# Inventory API endpoints are automatically exposed via @frappe.whitelist() decorator

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
before_request = [
	"erp.utils.auth_middleware.jwt_auth_middleware",
	"erp.observability.middleware.log_api_request_start"
]

after_request = [
	"erp.observability.middleware.log_api_request_end",
	"erp.utils.module_tracker.track_request_module_usage"
]

# Job Events
# ----------
# before_job = ["erp.utils.before_job"]
# after_job = ["erp.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"erp.authentication.auth_hooks"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# File upload system setup
# ------------------------
# after_install = [
#     "erp.install.after_install"
# ]

# User Management Hooks
# ---------------------
# doc_events = {
#     "User": {
#         "after_insert": [
#             "erp.utils.user_hooks.after_insert"
#         ],
#         "on_update": [
#             "erp.utils.user_hooks.on_update"
#         ],
#         "before_delete": [
#             "erp.utils.user_hooks.before_delete"
#         ]
#     }
# }

# Login/Logout Hooks
# ------------------
# ⚠️ DISABLED: Logging handled directly in auth.py endpoints to avoid timing issues
# on_login = [
# 	"erp.hooks_handlers.auth_logger.on_user_login"
# ]

# on_logout = [
# 	"erp.hooks_handlers.auth_logger.on_user_logout"
# ]

# Fixtures - Explicitly register child tables to prevent orphaning
fixtures = [
    {"dt": "DocType", "name": "ERP Administrative Room Class"},
]

after_migrate = [
    "erp.setup.after_migrate.execute",
]

scheduler_events = {
    # Attendance Batch Processor - Chạy mỗi lần scheduler tick (khoảng 5-10 giây)
    # Xử lý batch attendance events từ Redis buffer để giảm load database
    "all": [
        "erp.api.attendance.batch_processor.scheduled_process_attendance_buffer"
    ],
    "cron": {
        # Renew subscription mỗi 30 phút
        "*/30 * * * *": [
            "erp.api.erp_common_user.microsoft_auth.ensure_users_subscription"
        ],
        # Nhắc giáo viên điểm danh + Báo cáo điểm danh homeroom lúc 8:30 AM
        "30 8 * * *": [
            "erp.api.erp_sis.attendance.remind_homeroom_attendance",
            "erp.api.erp_sis.attendance.daily_homeroom_attendance_report"
        ],
        # Báo cáo kỷ luật THCS/THPT — 17:00 hàng ngày (email; non-production khi đang thử nghiệm)
        "0 17 * * *": [
            "erp.api.erp_sis.discipline_report.daily_discipline_email_report"
        ],
        # Aggregate Parent Portal Analytics lúc 23:00 hàng ngày
        "0 23 * * *": [
            "erp.api.analytics.portal_analytics.aggregate_portal_analytics"
        ],
        # Bus Daily Trips - Tạo trips cho ngày tiếp theo lúc 00:30 AM
        "30 0 * * *": [
            "erp.sis.tasks.bus_daily_trips.extend_daily_trips_job"
        ],
        # Bus Daily Trips - Archive trips cũ lúc 01:00 AM Chủ nhật
        "0 1 * * 0": [
            "erp.sis.tasks.bus_daily_trips.archive_old_trips_job"
        ],
        # Thư viện - Đồng bộ trạng thái quá hạn lúc 01:00 AM hàng ngày
        "0 1 * * *": [
            "erp.sis.tasks.library_overdue.sync_library_overdue_job"
        ],
        # Health Visit Escalation - Kiểm tra visit quá 15 phút chưa chuyển trạng thái (mỗi 5 phút, 7h-17h)
        "*/5 7-17 * * 1-6": [
            "erp.api.erp_sis.daily_health_notification.check_stale_health_visits"
        ],
        # CRM Issue SLA — canh bao sap qua / qua han (15 phut: tranh bo lo Warning voi SLA ngan)
        "*/15 * * * *": [
            "erp.api.crm.sla_scheduler.check_crm_issue_sla",
            "erp.lms.sync.enrollment_sync.sync_all_sections",
        ],
        # LMS Phase 6 — engagement score (2:00 AM), digest stub (7:00 AM)
        "0 2 * * *": [
            "erp.lms.cron.phase6_tasks.compute_engagement_score",
        ],
        "0 7 * * *": [
            "erp.lms.cron.phase6_tasks.generate_daily_digest",
        ],
    },
    # Project Management - Auto-expire pending invitations
    # Push Subscription cleanup - Xóa subscriptions không dùng trong 30 ngày
    "daily": [
        "erp.project_management.cron.expire_pending_invitations",
        "erp.api.parent_portal.push_notification.cleanup_stale_push_subscriptions"
    ],
    # CRM Weekly - Khong co scheduler tu dong mac dinh, goi thu cong qua API
    # auto_enroll va end_of_year_transition duoc goi thu cong boi admin
}