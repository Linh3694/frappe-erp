"""Analytics dashboard — aggregate từ dữ liệu LMS hiện có (§7.12)."""

from __future__ import annotations

from datetime import timedelta

import frappe
from frappe.utils import add_days, get_datetime, now_datetime, today

from erp.lms.services import engagement_service
from erp.lms.utils.enrollment import validate_section_enrollment
from erp.lms.utils.permissions import is_lms_staff, require_lms_staff, _get_user_campus_ids


def get_course_analytics(section_id: str, user: str | None = None) -> dict:
	"""Metrics khóa học — Teacher/Admin."""
	user = user or frappe.session.user
	if is_lms_staff(user):
		require_lms_staff()
	else:
		validate_section_enrollment(section_id, user, min_role="teacher")

	course_id = frappe.db.get_value("LMS Course Section", section_id, "course")
	course_title = frappe.db.get_value("LMS Course", course_id, "title") if course_id else None

	students = frappe.get_all(
		"LMS Enrollment",
		filters={"section": section_id, "role": "student", "status": "active"},
		fields=["student_id"],
	)
	student_ids = [s.student_id for s in students if s.student_id]
	student_count = len(student_ids)

	# Tiến độ trung bình
	progress_rows = []
	if student_ids:
		progress_rows = frappe.get_all(
			"LMS Course Progress",
			filters={"section": section_id, "student_id": ["in", student_ids]},
			fields=["percent_complete", "last_activity_at", "student_id"],
		)
	avg_progress = (
		round(sum(r.percent_complete or 0 for r in progress_rows) / len(progress_rows), 2)
		if progress_rows
		else 0
	)

	# Tỷ lệ nộp bài
	assignments = frappe.get_all("LMS Assignment", filters={"section": section_id}, pluck="name")
	submission_rate = 0.0
	if assignments and student_ids:
		expected = len(assignments) * len(student_ids)
		submitted = frappe.db.count(
			"LMS Submission",
			{
				"assignment": ["in", assignments],
				"student_id": ["in", student_ids],
				"workflow_state": ["in", ["submitted", "graded"]],
			},
		)
		submission_rate = round(submitted / expected * 100, 2) if expected else 0

	# Hoạt động 7 ngày
	week_ago = add_days(today(), -7)
	activity_count = frappe.db.count(
		"LMS Activity Log",
		{"section": section_id, "timestamp": [">=", week_ago]},
	)

	# Engagement & async attendance
	engagement_rows = engagement_service.get_score(section_id, user=user)
	if isinstance(engagement_rows, dict) and "students" in engagement_rows:
		student_scores = engagement_rows["students"]
	else:
		student_scores = [engagement_rows] if engagement_rows else []

	avg_engagement = 0.0
	at_risk = []
	if student_scores:
		scores = [r.get("score") or 0 for r in student_scores]
		avg_engagement = round(sum(scores) / len(scores), 2)
		for row in student_scores:
			if row.get("at_risk"):
				at_risk.append(
					{
						"student_id": row.get("student_id"),
						"student_name": row.get("student_name"),
						"score": row.get("score"),
					}
				)

	async_att = engagement_service.async_attendance(section_id, user=user)

	# Inactive > 7 ngày (bổ sung rule at-risk)
	inactive_cutoff = now_datetime() - timedelta(days=7)
	for row in progress_rows:
		last = row.last_activity_at
		if not last or get_datetime(last) < inactive_cutoff:
			sid = row.student_id
			if sid and not any(a["student_id"] == sid for a in at_risk):
				at_risk.append(
					{
						"student_id": sid,
						"student_name": frappe.db.get_value("CRM Student", sid, "student_name"),
						"reason": "inactive_7d",
					}
				)

	return {
		"section_id": section_id,
		"course_id": course_id,
		"course_title": course_title,
		"student_count": student_count,
		"avg_progress_percent": avg_progress,
		"submission_rate_percent": submission_rate,
		"activity_last_7_days": activity_count,
		"avg_engagement_score": avg_engagement,
		"at_risk_students": at_risk,
		"async_attendance": async_att,
	}


def get_campus_analytics(user: str | None = None) -> dict:
	"""Tổng hợp campus — Admin dashboard."""
	user = user or frappe.session.user
	require_lms_staff()
	campus_ids = _get_user_campus_ids(user)
	if "System Manager" in frappe.get_roles(user):
		campus_ids = campus_ids or frappe.get_all("SIS Campus", pluck="name")

	if not campus_ids:
		return {"sections": [], "totals": {"sections": 0, "students": 0, "avg_engagement": 0}}

	sections = frappe.get_all(
		"LMS Course Section",
		filters={"campus_id": ["in", campus_ids]},
		fields=["name", "title", "course"],
		limit=50,
		order_by="modified desc",
	)
	summaries = []
	total_students = 0
	engagement_sum = 0
	engagement_n = 0

	for sec in sections:
		try:
			metrics = get_course_analytics(sec.name, user=user)
			summaries.append(
				{
					"section_id": sec.name,
					"section_title": sec.title,
					"course_id": sec.course,
					"student_count": metrics.get("student_count", 0),
					"avg_progress_percent": metrics.get("avg_progress_percent", 0),
					"avg_engagement_score": metrics.get("avg_engagement_score", 0),
					"at_risk_count": len(metrics.get("at_risk_students") or []),
				}
			)
			total_students += metrics.get("student_count", 0)
			if metrics.get("avg_engagement_score"):
				engagement_sum += metrics["avg_engagement_score"]
				engagement_n += 1
		except Exception:
			continue

	return {
		"sections": summaries,
		"totals": {
			"sections": len(summaries),
			"students": total_students,
			"avg_engagement": round(engagement_sum / engagement_n, 2) if engagement_n else 0,
		},
	}
