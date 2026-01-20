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
after_install = [
    "erp.api.notification.ticket.start_redis_listener"
]

# Start Redis listeners on app startup
app_startup = [
    "erp.api.notification.ticket.start_redis_listener"
]

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
	"SIS Class Log Student": "erp.sis.utils.permission_query.sis_class_log_student_query"
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
	"SIS Class Log Student": "erp.sis.utils.campus_permissions.has_campus_permission"
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
			"erp.common.user_hooks.trigger_user_webhooks"
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
	"SIS Class": {
		"on_update": [
			"erp.api.erp_administrative.room.sync_class_room_assignment"
		]
	},
	# Logging hooks for audit trail
	"File": {
		"after_insert": [
			"erp.hooks_handlers.file_logger.log_file_upload"
		],
		"on_update": [
			"erp.hooks_handlers.file_logger.log_file_update"
		],
		"on_trash": [
			"erp.hooks_handlers.file_logger.log_file_delete"
		]
	},
	"Student": {
		"after_insert": [
			"erp.hooks_handlers.crud_logger.log_create"
		],
		"on_update": [
			"erp.hooks_handlers.crud_logger.log_update"
		],
		"on_trash": [
			"erp.hooks_handlers.crud_logger.log_delete"
		],
		"on_cancel": [
			"erp.hooks_handlers.crud_logger.log_cancel"
		]
	},
	"Guardian": {
		"after_insert": [
			"erp.hooks_handlers.crud_logger.log_create"
		],
		"on_update": [
			"erp.hooks_handlers.crud_logger.log_update"
		],
		"on_trash": [
			"erp.hooks_handlers.crud_logger.log_delete"
		]
	},
	"SIS Class Student": {
		"after_insert": [
			"erp.hooks_handlers.crud_logger.log_create"
		],
		"on_update": [
			"erp.hooks_handlers.crud_logger.log_update"
		],
		"on_trash": [
			"erp.hooks_handlers.crud_logger.log_delete"
		]
	},
	"SIS Class Attendance": {
		"after_insert": [
			"erp.hooks_handlers.crud_logger.log_create"
		],
		"on_update": [
			"erp.hooks_handlers.crud_logger.log_update"
		],
		"on_trash": [
			"erp.hooks_handlers.crud_logger.log_delete"
		]
	},
	"SIS Event": {
		"after_insert": [
			"erp.hooks_handlers.crud_logger.log_create"
		],
		"on_update": [
			"erp.hooks_handlers.crud_logger.log_update"
		],
		"on_trash": [
			"erp.hooks_handlers.crud_logger.log_delete"
		]
	},
	"SIS Class": {
		"after_insert": [
			"erp.hooks_handlers.crud_logger.log_create"
		],
		"on_update": [
			"erp.hooks_handlers.crud_logger.log_update"
		],
		"on_trash": [
			"erp.hooks_handlers.crud_logger.log_delete"
		]
	},
	"SIS Teacher": {
		"after_insert": [
			"erp.hooks_handlers.crud_logger.log_create"
		],
		"on_update": [
			"erp.hooks_handlers.crud_logger.log_update"
		],
		"on_trash": [
			"erp.hooks_handlers.crud_logger.log_delete"
		]
	},
	"SIS Subject": {
		"after_insert": [
			"erp.hooks_handlers.crud_logger.log_create"
		],
		"on_update": [
			"erp.hooks_handlers.crud_logger.log_update"
		],
		"on_trash": [
			"erp.hooks_handlers.crud_logger.log_delete"
		]
	},
	"SIS Curriculum": {
		"after_insert": [
			"erp.hooks_handlers.crud_logger.log_create"
		],
		"on_update": [
			"erp.hooks_handlers.crud_logger.log_update"
		],
		"on_trash": [
			"erp.hooks_handlers.crud_logger.log_delete"
		]
	},
	"SIS Actual Subject": {
		"after_insert": [
			"erp.hooks_handlers.crud_logger.log_create"
		],
		"on_update": [
			"erp.hooks_handlers.crud_logger.log_update"
		],
		"on_trash": [
			"erp.hooks_handlers.crud_logger.log_delete"
		]
	},
	"SIS Timetable": {
		"after_insert": [
			"erp.hooks_handlers.crud_logger.log_create"
		],
		"on_update": [
			"erp.hooks_handlers.crud_logger.log_update"
		],
		"on_trash": [
			"erp.hooks_handlers.crud_logger.log_delete"
		]
	},
	"SIS Timetable Subject": {
		"after_insert": [
			"erp.hooks_handlers.crud_logger.log_create"
		],
		"on_update": [
			"erp.hooks_handlers.crud_logger.log_update"
		],
		"on_trash": [
			"erp.hooks_handlers.crud_logger.log_delete"
		]
	},
	"SIS Photo": {
		"after_insert": [
			"erp.hooks_handlers.crud_logger.log_create"
		],
		"on_update": [
			"erp.hooks_handlers.crud_logger.log_update"
		],
		"on_trash": [
			"erp.hooks_handlers.crud_logger.log_delete"
		]
	},
	"SIS School Year": {
		"after_insert": [
			"erp.hooks_handlers.crud_logger.log_create"
		],
		"on_update": [
			"erp.hooks_handlers.crud_logger.log_update"
		],
		"on_trash": [
			"erp.hooks_handlers.crud_logger.log_delete"
		]
	},
	"SIS Education Stage": {
		"after_insert": [
			"erp.hooks_handlers.crud_logger.log_create"
		],
		"on_update": [
			"erp.hooks_handlers.crud_logger.log_update"
		],
		"on_trash": [
			"erp.hooks_handlers.crud_logger.log_delete"
		]
	},
	"SIS Education Grade": {
		"after_insert": [
			"erp.hooks_handlers.crud_logger.log_create"
		],
		"on_update": [
			"erp.hooks_handlers.crud_logger.log_update"
		],
		"on_trash": [
			"erp.hooks_handlers.crud_logger.log_delete"
		]
	},
	"SIS Academic Program": {
		"after_insert": [
			"erp.hooks_handlers.crud_logger.log_create"
		],
		"on_update": [
			"erp.hooks_handlers.crud_logger.log_update"
		],
		"on_trash": [
			"erp.hooks_handlers.crud_logger.log_delete"
		]
	},
	"SIS Sub Curriculum": {
		"after_insert": [
			"erp.hooks_handlers.crud_logger.log_create"
		],
		"on_update": [
			"erp.hooks_handlers.crud_logger.log_update"
		],
		"on_trash": [
			"erp.hooks_handlers.crud_logger.log_delete"
		]
	},
	"SIS Calendar": {
		"after_insert": [
			"erp.hooks_handlers.crud_logger.log_create"
		],
		"on_update": [
			"erp.hooks_handlers.crud_logger.log_update"
		],
		"on_trash": [
			"erp.hooks_handlers.crud_logger.log_delete"
		]
	},
	"SIS Subject Assignment": {
		"after_insert": [
			"erp.hooks_handlers.crud_logger.log_create"
		],
		"on_update": [
			"erp.hooks_handlers.crud_logger.log_update"
		],
		"on_trash": [
			"erp.hooks_handlers.crud_logger.log_delete"
		]
	},
	"Feedback": {
		"after_insert": [
			"erp.hooks_handlers.crud_logger.log_create"
		],
		"on_update": [
			"erp.hooks_handlers.crud_logger.log_update"
		],
		"on_trash": [
			"erp.hooks_handlers.crud_logger.log_delete"
		]
	},
	"SIS Student Leave Request": {
		"after_insert": [
			"erp.hooks_handlers.crud_logger.log_create"
		],
		"on_update": [
			"erp.hooks_handlers.crud_logger.log_update"
		],
		"on_trash": [
			"erp.hooks_handlers.crud_logger.log_delete"
		]
	},
	"SIS Announcement": {
		"after_insert": [
			"erp.hooks_handlers.crud_logger.log_create"
		],
		"on_update": [
			"erp.hooks_handlers.crud_logger.log_update"
		],
		"on_trash": [
			"erp.hooks_handlers.crud_logger.log_delete"
		]
	},
	"SIS News Article": {
		"after_insert": [
			"erp.hooks_handlers.crud_logger.log_create"
		],
		"on_update": [
			"erp.hooks_handlers.crud_logger.log_update"
		],
		"on_trash": [
			"erp.hooks_handlers.crud_logger.log_delete"
		]
	},
	"Daily Menu": {
		"after_insert": [
			"erp.hooks_handlers.crud_logger.log_create"
		],
		"on_update": [
			"erp.hooks_handlers.crud_logger.log_update"
		],
		"on_trash": [
			"erp.hooks_handlers.crud_logger.log_delete"
		]
	},
	"SIS Bus Route": {
		"after_insert": [
			"erp.hooks_handlers.crud_logger.log_create"
		],
		"on_update": [
			"erp.hooks_handlers.crud_logger.log_update"
		],
		"on_trash": [
			"erp.hooks_handlers.crud_logger.log_delete"
		]
	},
	"SIS Bus Student": {
		"after_insert": [
			"erp.hooks_handlers.crud_logger.log_create"
		],
		"on_update": [
			"erp.hooks_handlers.crud_logger.log_update"
		],
		"on_trash": [
			"erp.hooks_handlers.crud_logger.log_delete"
		]
	},
	"SIS Bus Daily Trip": {
		"after_insert": [
			"erp.hooks_handlers.crud_logger.log_create"
		],
		"on_update": [
			"erp.hooks_handlers.crud_logger.log_update"
		],
		"on_trash": [
			"erp.hooks_handlers.crud_logger.log_delete"
		]
	},
	"SIS Badge": {
		"after_insert": [
			"erp.hooks_handlers.crud_logger.log_create"
		],
		"on_update": [
			"erp.hooks_handlers.crud_logger.log_update"
		],
		"on_trash": [
			"erp.hooks_handlers.crud_logger.log_delete"
		]
	}
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
	"erp.api.analytics.dashboard_api.trigger_analytics_aggregation"
]

# Allow guest access for testing
guest_method_whitelist = [
	"erp.api.bulk_import.reload_whitelist"
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
	"erp.hooks_handlers.api_logger.log_api_request_start"
]

after_request = [
	"erp.hooks_handlers.api_logger.log_api_request_end",
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
    {"dt": "DocType", "name": "ERP Administrative Room Class"}
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
        ]
    },
    # Project Management - Auto-expire pending invitations
    "daily": [
        "erp.project_management.cron.expire_pending_invitations"
    ]
}