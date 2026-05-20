"""Cấu hình LMS — đọc từ site_config hoặc biến môi trường."""

import os

import frappe

# Nhóm DocType theo phase (tham chiếu lms-phase-specs.md)
LMS_DOCTYPE_GROUPS = {
	"core": [
		"LMS Program",
		"LMS Course",
		"LMS Course Section",
		"LMS Enrollment",
		"LMS Module",
		"LMS Module Item",
		"LMS Page",
		"LMS File",
		"LMS Content Progress",
		"LMS Course Progress",
	],
	"assessment": [
		"LMS Assignment",
		"LMS Submission",
		"LMS Grade Column",
		"LMS Grade Entry",
		"LMS Grade Group",
		"LMS Quiz",
		"LMS Question Bank",
		"LMS Question",
		"LMS Quiz Question",
		"LMS Quiz Attempt",
		"LMS Announcement",
	],
	"media": ["LMS Video Asset"],
	"phase4": [
		"LMS Discussion",
		"LMS Discussion Entry",
		"LMS Group",
		"LMS Group Membership",
		"LMS Calendar Event",
		"LMS Outcome",
		"LMS Mastery Rule",
	],
	"phase5": [
		"LMS Grade Sync Rule",
		"LMS Grade Sync Log",
		"LMS Blueprint Course",
		"LMS Blueprint Sync Log",
	],
	"phase6": ["LMS Activity Log", "LMS Conversation", "LMS Message", "LMS External Tool"],
	"phase7_live": ["LMS Live Session", "LMS Live Attendance", "LMS Live Provider Config", "LMS Caption Track"],
	"phase7_ai": ["LMS AI Job", "LMS Transcript", "LMS AI Tutor Conversation", "LMS AI Tutor Message"],
	"phase8": ["LMS SCORM Package", "LMS SCORM Tracking", "LMS xAPI Statement", "LMS H5P Content"],
	"phase9": ["LMS Device Registration", "LMS Offline Sync Log"],
	"phase10": [
		"LMS Certificate Template",
		"LMS Certificate Issuance",
		"LMS Badge Class",
		"LMS Badge Assertion",
		"LMS Catalog Entry",
		"LMS Enrollment Request",
		"LMS Portfolio",
		"LMS Portfolio Item",
	],
	"phase11": [
		"LMS Mastery Scale",
		"LMS Reading Log",
		"LMS Pacing Guide",
		"LMS Substitute Access Grant",
		"LMS Conference Booking",
		"LMS Achievement Definition",
		"LMS Student Achievement",
	],
	"phase12": [
		"LMS AI Feedback Suggestion",
		"LMS Plagiarism Report",
		"LMS Item Analysis",
		"LMS Peer Review Assignment",
		"LMS Peer Review Submission",
		"LMS Late Policy",
	],
}


def get_media_service_url() -> str:
	return (
		frappe.conf.get("lms_media_service_url")
		or os.environ.get("LMS_MEDIA_SERVICE_URL")
		or "http://172.16.20.21:5020"
	).rstrip("/")


def get_media_internal_secret() -> str:
	return frappe.conf.get("lms_media_internal_secret") or os.environ.get(
		"LMS_MEDIA_INTERNAL_SECRET", ""
	)


def get_media_public_url() -> str:
	return (
		frappe.conf.get("lms_media_public_url")
		or os.environ.get("LMS_MEDIA_PUBLIC_URL")
		or ""
	).rstrip("/")


def get_ai_service_url() -> str:
	return (
		frappe.conf.get("lms_ai_service_url")
		or os.environ.get("LMS_AI_SERVICE_URL")
		or "http://172.16.20.22:5030"
	).rstrip("/")


def get_ai_internal_secret() -> str:
	return frappe.conf.get("lms_ai_internal_secret") or os.environ.get("LMS_AI_INTERNAL_SECRET", "")


def get_live_service_url() -> str:
	return (
		frappe.conf.get("lms_live_service_url")
		or os.environ.get("LMS_LIVE_SERVICE_URL")
		or "http://172.16.20.22:5040"
	).rstrip("/")


def get_live_internal_secret() -> str:
	return frappe.conf.get("lms_live_internal_secret") or os.environ.get("LMS_LIVE_INTERNAL_SECRET", "")
