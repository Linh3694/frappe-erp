"""
Cấu hình Phase 2 — danh sách DocType và quy tắc backfill campus_id theo đợt rollout.
"""

from __future__ import annotations

# Field campus_id chuẩn (reqd=0 giai đoạn rollout, before_insert gán default)
CAMPUS_ID_FIELD = {
	"fieldname": "campus_id",
	"fieldtype": "Link",
	"label": "Campus",
	"options": "SIS Campus",
	"reqd": 0,
	"in_standard_filter": 1,
}

# (doctype, backfill_kind, kwargs)
# backfill_kind: join | coalesce | copy | assignment_chain | student_code | guardian_family | it_creator | finance_chain | guardian_activity | skip
PHASE2_BACKFILL: dict[str, list[tuple[str, str, dict]]] = {
	"dot0": [
		("SIS Student Timetable", "join", {"link_field": "class_id", "parent_doctype": "SIS Class"}),
		("SIS Teacher Timetable", "join", {"link_field": "class_id", "parent_doctype": "SIS Class"}),
		("SIS Timetable Override", "join", {"link_field": "event_id", "parent_doctype": "SIS Event"}),
		("SIS Event Date Time", "join", {"link_field": "event_id", "parent_doctype": "SIS Event"}),
		("LMS Announcement", "coalesce", {
			"joins": [
				("section", "LMS Course Section", "campus_id"),
				("course", "LMS Course", "campus_id"),
			],
		}),
		("CRM Issue", "coalesce", {
			"joins": [
				("lead", "CRM Lead", "campus_id"),
				("student", "CRM Student", "campus_id"),
			],
		}),
		("ERP IT Support Ticket", "it_creator", {}),
	],
	"dot1": [
		("SIS Health Examination", "join", {"link_field": "student_id", "parent_doctype": "CRM Student"}),
		("SIS Daily Health Visit", "join", {"link_field": "student_id", "parent_doctype": "CRM Student"}),
		("SIS Health Report", "join", {"link_field": "student_id", "parent_doctype": "CRM Student"}),
		("SIS Scholarship Application", "join", {"link_field": "student_id", "parent_doctype": "CRM Student"}),
		("SIS Scholarship Recommendation", "join", {"link_field": "application_id", "parent_doctype": "SIS Scholarship Application"}),
		("SIS Timetable Pinned Slot", "join", {"link_field": "class_id", "parent_doctype": "SIS Class"}),
		("SIS Event Attendance", "join", {"link_field": "event_id", "parent_doctype": "SIS Event"}),
		("Feedback", "join", {"link_field": "guardian", "parent_doctype": "CRM Guardian"}),
		("SIS Bus Daily Trip Student", "join", {"link_field": "student_id", "parent_doctype": "CRM Student"}),
		("SIS Bus Route Student", "join", {"link_field": "student_id", "parent_doctype": "CRM Student"}),
		("SIS Menu Registration", "join", {"link_field": "class_id", "parent_doctype": "SIS Class"}),
		("SIS Menu Registration Period", "join", {"link_field": "school_year_id", "parent_doctype": "SIS School Year"}),
		("SIS Teacher Education Stage", "join", {"link_field": "teacher_id", "parent_doctype": "SIS Teacher"}),
	],
	"dot2": [
		("SIS Finance Order", "join", {"link_field": "finance_year_id", "parent_doctype": "SIS Finance Year"}),
		("SIS Finance Order Student", "join", {"link_field": "order_id", "parent_doctype": "SIS Finance Order"}),
		("SIS Finance Order Item", "join", {"link_field": "order_id", "parent_doctype": "SIS Finance Order"}),
		("SIS Finance Send Batch", "join", {"link_field": "order_id", "parent_doctype": "SIS Finance Order"}),
		("SIS Finance Collection Log", "join", {"link_field": "order_student_id", "parent_doctype": "SIS Finance Order Student"}),
		("SIS Finance Debit Note History", "join", {"link_field": "order_student_id", "parent_doctype": "SIS Finance Order Student"}),
		("SIS Finance Student Document", "join", {"link_field": "order_student_id", "parent_doctype": "SIS Finance Order Student"}),
		("SIS Library Book Copy", "join", {"link_field": "title_id", "parent_doctype": "SIS Library Title"}),
		("SIS Library Transaction", "student_code", {}),
		("SIS Library Title", "skip", {}),
		("SIS Library Event", "skip", {}),
	],
	"dot3": [
		("CRM Guardian", "guardian_family", {}),
		("CRM Family", "crm_family", {}),
		("CRM Admission Course", "join", {"link_field": "school_year_id", "parent_doctype": "SIS School Year"}),
		("CRM Admission Course Student", "join", {"link_field": "crm_lead_id", "parent_doctype": "CRM Lead"}),
		("CRM Admission Entrance Exam", "join", {"link_field": "school_year_id", "parent_doctype": "SIS School Year"}),
		("CRM Admission Entrance Exam Student", "join", {"link_field": "crm_lead_id", "parent_doctype": "CRM Lead"}),
		("CRM Admission Event", "join", {"link_field": "school_year_id", "parent_doctype": "SIS School Year"}),
		("CRM Admission Event Student", "join", {"link_field": "crm_lead_id", "parent_doctype": "CRM Lead"}),
		("CRM Exam Score", "join", {"link_field": "lead", "parent_doctype": "CRM Lead"}),
		("CRM Lead Note", "join", {"link_field": "lead", "parent_doctype": "CRM Lead"}),
		("CRM Lead Step History", "join", {"link_field": "lead", "parent_doctype": "CRM Lead"}),
		("Portal API Error", "skip", {}),
		("Portal Guardian Activity", "join", {"link_field": "guardian", "parent_doctype": "CRM Guardian"}),
	],
	"dot4": [
		("LMS Submission", "assignment_chain", {"assignment_field": "assignment", "assignment_doctype": "LMS Assignment"}),
		("LMS Grade Entry", "join", {"link_field": "column", "parent_doctype": "LMS Grade Column"}),
		("LMS Quiz Attempt", "lms_quiz_attempt", {}),
		("LMS Course Progress", "join", {"link_field": "section", "parent_doctype": "LMS Course Section"}),
		("LMS Content Progress", "join", {"link_field": "student_id", "parent_doctype": "CRM Student"}),
		("LMS Engagement Score", "join", {"link_field": "section", "parent_doctype": "LMS Course Section"}),
		("LMS Group Membership", "join", {"link_field": "group", "parent_doctype": "LMS Group"}),
		("LMS Grade Sync Log", "join", {"link_field": "rule", "parent_doctype": "LMS Grade Sync Rule"}),
		("LMS Activity Log", "coalesce", {
			"joins": [
				("section", "LMS Course Section", "campus_id"),
				("course", "LMS Course", "campus_id"),
			],
		}),
		("LMS Conversation", "coalesce", {
			"joins": [
				("section", "LMS Course Section", "campus_id"),
				("course", "LMS Course", "campus_id"),
			],
		}),
		("LMS Module", "join", {"link_field": "course", "parent_doctype": "LMS Course"}),
		("LMS External Tool", "join", {"link_field": "course", "parent_doctype": "LMS Course"}),
		("LMS Blueprint Sync Log", "join", {"link_field": "blueprint_course", "parent_doctype": "LMS Blueprint Course"}),
	],
	"dot5": [
		("ERP Administrative Room Yearly Assignment", "join", {"link_field": "room", "parent_doctype": "ERP Administrative Room"}),
		("ERP Administrative Ticket", "join", {"link_field": "room_id", "parent_doctype": "ERP Administrative Room"}),
		("ERP Administrative Facility Handover", "join", {"link_field": "room", "parent_doctype": "ERP Administrative Room"}),
		("ERP Administrative Inventory Check", "join", {"link_field": "room", "parent_doctype": "ERP Administrative Room"}),
		("ERP Administrative Room Activity Log", "join", {"link_field": "room", "parent_doctype": "ERP Administrative Room"}),
		("ERP Administrative Room Facility Equipment", "join", {"link_field": "room", "parent_doctype": "ERP Administrative Room"}),
		("ERP Inventory Device", "join", {"link_field": "room", "parent_doctype": "ERP Administrative Room"}),
		("ERP Inventory Inspection", "join", {"link_field": "device", "parent_doctype": "ERP Inventory Device"}),
		("ERP Inventory Handover Log", "join", {"link_field": "device", "parent_doctype": "ERP Inventory Device"}),
		("ERP Inventory Activity Log", "join", {"link_field": "entity", "parent_doctype": "ERP Inventory Device"}),
		("PM Task", "join", {"link_field": "project_id", "parent_doctype": "PM Project"}),
		("PM Meeting", "join", {"link_field": "project_id", "parent_doctype": "PM Project"}),
		("PM Project Member", "join", {"link_field": "project_id", "parent_doctype": "PM Project"}),
		("PM Resource", "join", {"link_field": "project_id", "parent_doctype": "PM Project"}),
		("PM Requirement", "join", {"link_field": "project_id", "parent_doctype": "PM Project"}),
		("PM Change Log", "join", {"link_field": "project_id", "parent_doctype": "PM Project"}),
		("PM Project Invitation", "join", {"link_field": "project_id", "parent_doctype": "PM Project"}),
	],
	"dot6": [
		("SIS Discipline Record", "copy", {"source_field": "campus"}),
		("SIS Discipline Classification", "copy", {"source_field": "campus"}),
		("SIS Discipline Form", "copy", {"source_field": "campus"}),
		("SIS Discipline Time", "copy", {"source_field": "campus"}),
		("SIS Discipline Violation", "copy", {"source_field": "campus"}),
		("SIS First Aid", "copy", {"source_field": "campus"}),
		("SIS Medicine", "copy", {"source_field": "campus"}),
		("SIS Disease Classification", "copy", {"source_field": "campus"}),
	],
}

# Module routing cho permission_query wrapper
DOCTYPE_PQ_MODULE: dict[str, str] = {
	"CRM Issue": "crm",
	"CRM Guardian": "crm",
	"CRM Family": "crm",
	"CRM Admission Course": "crm",
	"CRM Admission Course Student": "crm",
	"CRM Admission Entrance Exam": "crm",
	"CRM Admission Entrance Exam Student": "crm",
	"CRM Admission Event": "crm",
	"CRM Admission Event Student": "crm",
	"CRM Exam Score": "crm",
	"CRM Lead Note": "crm",
	"CRM Lead Step History": "crm",
	"LMS Announcement": "lms",
	"LMS Submission": "lms",
	"LMS Grade Entry": "lms",
	"LMS Quiz Attempt": "lms",
	"LMS Course Progress": "lms",
	"LMS Content Progress": "lms",
	"LMS Engagement Score": "lms",
	"LMS Group Membership": "lms",
	"LMS Grade Sync Log": "lms",
	"LMS Activity Log": "lms",
	"LMS Conversation": "lms",
	"LMS Module": "lms",
	"LMS External Tool": "lms",
	"LMS Blueprint Sync Log": "lms",
	"ERP IT Support Ticket": "it",
	"ERP Administrative Room Yearly Assignment": "generic",
	"ERP Administrative Ticket": "generic",
	"ERP Administrative Facility Handover": "generic",
	"ERP Administrative Inventory Check": "generic",
	"ERP Administrative Room Activity Log": "generic",
	"ERP Administrative Room Facility Equipment": "generic",
	"ERP Inventory Device": "generic",
	"ERP Inventory Inspection": "generic",
	"ERP Inventory Handover Log": "generic",
	"ERP Inventory Activity Log": "generic",
	"PM Task": "generic",
	"PM Meeting": "generic",
	"PM Project Member": "generic",
	"PM Resource": "generic",
	"PM Requirement": "generic",
	"PM Change Log": "generic",
	"PM Project Invitation": "generic",
	"Portal API Error": "generic",
	"Portal Guardian Activity": "generic",
	"Feedback": "generic",
}


def all_phase2_doctypes(phases: list[str] | None = None) -> list[str]:
	"""Trả về danh sách DocType Phase 2 (có thể lọc theo đợt)."""
	phases = phases or list(PHASE2_BACKFILL.keys())
	seen: set[str] = set()
	result: list[str] = []
	for phase in phases:
		for dt, _, _ in PHASE2_BACKFILL.get(phase, []):
			if dt not in seen:
				seen.add(dt)
				result.append(dt)
	return result


def pq_module_for(doctype: str) -> str:
	return DOCTYPE_PQ_MODULE.get(doctype, "sis")
