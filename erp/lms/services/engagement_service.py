"""Engagement Score & async attendance — Phase 6 (§7.12)."""

from __future__ import annotations

import json
from datetime import datetime

import frappe
from frappe.utils import add_days, get_datetime, now_datetime, today

from erp.lms.utils.enrollment import get_student_id_for_user, validate_section_enrollment
from erp.lms.utils.permissions import is_lms_staff, require_lms_staff


def _current_period() -> str:
	"""Tuần hiện tại dạng YYYY-Www."""
	iso = datetime.utcnow().isocalendar()
	return f"{iso[0]}-W{iso[1]:02d}"


def _at_risk_threshold(section_id: str) -> float:
	course_id = frappe.db.get_value("LMS Course Section", section_id, "course")
	if not course_id:
		return 30.0
	val = frappe.db.get_value("LMS Course", course_id, "engagement_threshold_at_risk")
	try:
		return float(val) if val is not None else 30.0
	except (TypeError, ValueError):
		return 30.0


def _student_user_id(section_id: str, student_id: str) -> str | None:
	return frappe.db.get_value(
		"LMS Enrollment",
		{"section": section_id, "student_id": student_id, "role": "student", "status": "active"},
		"user",
	)


def _compute_signals(section_id: str, student_id: str) -> dict:
	"""Tính các tín hiệu 0–100 trước khi gộp trọng số."""
	course_id = frappe.db.get_value("LMS Course Section", section_id, "course")
	user_id = _student_user_id(section_id, student_id)
	week_ago = add_days(today(), -7)

	# Login days (15%)
	login_days = 0
	if user_id:
		logs = frappe.db.sql(
			"""
			SELECT COUNT(DISTINCT DATE(`timestamp`)) AS c
			FROM `tabLMS Activity Log`
			WHERE `user` = %s AND `section` = %s AND `timestamp` >= %s
			""",
			(user_id, section_id, week_ago),
			as_dict=True,
		)
		login_days = min(int(logs[0].c or 0), 7)
	login_score = round(login_days / 7 * 100, 2)

	# Video / content completion (25%)
	video_score = 0.0
	if course_id:
		module_names = frappe.get_all("LMS Module", filters={"course": course_id}, pluck="name")
		item_ids = []
		if module_names:
			item_ids = frappe.get_all(
				"LMS Module Item",
				filters={"module": ["in", module_names], "published": 1},
				pluck="name",
			)
		if item_ids:
			done = frappe.db.count(
				"LMS Content Progress",
				{"student_id": student_id, "module_item": ["in", item_ids], "completed": 1},
			)
			video_score = round(done / len(item_ids) * 100, 2)

	# On-time submission (30%)
	submission_score = 0.0
	assignments = frappe.get_all(
		"LMS Assignment",
		filters={"section": section_id},
		fields=["name", "due_at"],
	)
	if assignments:
		on_time = 0
		for a in assignments:
			sub = frappe.db.get_value(
				"LMS Submission",
				{"assignment": a.name, "student_id": student_id},
				["submitted_at", "workflow_state"],
				as_dict=True,
			)
			if not sub or sub.workflow_state not in ("submitted", "graded"):
				continue
			if not a.due_at:
				on_time += 1
			elif sub.submitted_at and get_datetime(sub.submitted_at) <= get_datetime(a.due_at):
				on_time += 1
		submitted_count = frappe.db.count(
			"LMS Submission",
			{
				"student_id": student_id,
				"assignment": ["in", [x.name for x in assignments]],
				"workflow_state": ["in", ["submitted", "graded"]],
			},
		)
		if submitted_count:
			submission_score = round(on_time / len(assignments) * 100, 2)

	# Discussion posts (15%)
	discussion_score = 0.0
	discussion_ids = frappe.get_all(
		"LMS Discussion",
		filters={"section": section_id},
		pluck="name",
	)
	if discussion_ids and user_id:
		posts = frappe.db.count(
			"LMS Discussion Entry",
			{"discussion": ["in", discussion_ids], "author": user_id, "hidden": 0},
		)
		discussion_score = min(100.0, posts * 20.0)

	# Quiz completed (15%)
	quiz_score = 0.0
	quiz_ids = frappe.get_all("LMS Quiz", filters={"section": section_id}, pluck="name")
	if quiz_ids:
		done_quizzes = frappe.db.sql(
			"""
			SELECT COUNT(DISTINCT quiz) AS c
			FROM `tabLMS Quiz Attempt`
			WHERE student_id = %s AND quiz IN %s
			  AND workflow_state IN ('submitted', 'graded')
			""",
			(student_id, tuple(quiz_ids)),
			as_dict=True,
		)
		completed = int(done_quizzes[0].c or 0)
		quiz_score = round(completed / len(quiz_ids) * 100, 2)

	weighted = round(
		login_score * 0.15
		+ video_score * 0.25
		+ submission_score * 0.30
		+ discussion_score * 0.15
		+ quiz_score * 0.15,
		2,
	)
	return {
		"login_days": login_days,
		"login_score": login_score,
		"video_score": video_score,
		"submission_score": submission_score,
		"discussion_score": discussion_score,
		"quiz_score": quiz_score,
		"weighted_score": weighted,
	}


def compute_and_store_score(section_id: str, student_id: str, period: str | None = None) -> dict:
	"""Tính và lưu LMS Engagement Score."""
	period = period or _current_period()
	signals = _compute_signals(section_id, student_id)
	score = signals["weighted_score"]
	threshold = _at_risk_threshold(section_id)
	at_risk = 1 if score < threshold else 0

	existing = frappe.db.get_value(
		"LMS Engagement Score",
		{"section": section_id, "student_id": student_id, "period": period},
	)
	payload = {
		"score": score,
		"signals_json": json.dumps(signals),
		"computed_at": now_datetime(),
		"at_risk": at_risk,
	}
	if existing:
		frappe.db.set_value("LMS Engagement Score", existing, payload)
		name = existing
	else:
		doc = frappe.get_doc(
			{
				"doctype": "LMS Engagement Score",
				"student_id": student_id,
				"section": section_id,
				"period": period,
				**payload,
			}
		)
		doc.insert(ignore_permissions=True)
		name = doc.name

	row = frappe.get_doc("LMS Engagement Score", name).as_dict()
	row["student_name"] = frappe.db.get_value("CRM Student", student_id, "student_name")
	return row


def get_score(section_id: str, student_id: str | None = None, user: str | None = None) -> dict | list:
	"""HS xem điểm của mình; GV/Admin xem cả section."""
	user = user or frappe.session.user
	if is_lms_staff(user):
		require_lms_staff()
	else:
		validate_section_enrollment(section_id, user, min_role="student")
		student_id = student_id or get_student_id_for_user(user)
		if not student_id:
			frappe.throw("Không tìm thấy học sinh", frappe.PermissionError)

	period = _current_period()
	if student_id:
		existing = frappe.db.get_value(
			"LMS Engagement Score",
			{"section": section_id, "student_id": student_id, "period": period},
			["name", "score", "signals_json", "at_risk", "computed_at"],
			as_dict=True,
		)
		if not existing:
			return compute_and_store_score(section_id, student_id, period)
		existing["student_name"] = frappe.db.get_value("CRM Student", student_id, "student_name")
		if isinstance(existing.get("signals_json"), str):
			try:
				existing["signals"] = json.loads(existing["signals_json"])
			except json.JSONDecodeError:
				existing["signals"] = {}
		return existing

	# Staff — danh sách cả lớp
	students = frappe.get_all(
		"LMS Enrollment",
		filters={"section": section_id, "role": "student", "status": "active"},
		pluck="student_id",
	)
	rows = []
	for sid in students:
		if not sid:
			continue
		rows.append(compute_and_store_score(section_id, sid, period))
	return {"section_id": section_id, "period": period, "students": rows}


def async_attendance(section_id: str, week: str | None = None, user: str | None = None) -> dict:
	"""% học sinh active trong tuần (login, content, submit)."""
	user = user or frappe.session.user
	if is_lms_staff(user):
		require_lms_staff()
	else:
		validate_section_enrollment(section_id, user, min_role="teacher")

	students = frappe.get_all(
		"LMS Enrollment",
		filters={"section": section_id, "role": "student", "status": "active"},
		pluck="student_id",
	)
	student_ids = [s for s in students if s]
	if not student_ids:
		return {"section_id": section_id, "week": week or _current_period(), "active_percent": 0, "active_count": 0, "total": 0}

	week_start = add_days(today(), -7)
	active = set()
	for sid in student_ids:
		prog = frappe.db.get_value(
			"LMS Course Progress",
			{"section": section_id, "student_id": sid},
			"last_activity_at",
		)
		if prog and get_datetime(prog) >= get_datetime(week_start):
			active.add(sid)
			continue
		if frappe.db.exists(
			"LMS Submission",
			{
				"student_id": sid,
				"submitted_at": [">=", week_start],
			},
		):
			active.add(sid)

	total = len(student_ids)
	pct = round(len(active) / total * 100, 2) if total else 0
	return {
		"section_id": section_id,
		"week": week or _current_period(),
		"active_percent": pct,
		"active_count": len(active),
		"total": total,
	}


def compute_all_sections():
	"""Cron — tính engagement cho mọi section có HS active."""
	sections = frappe.get_all(
		"LMS Enrollment",
		filters={"role": "student", "status": "active"},
		pluck="section",
	)
	seen = set()
	for section_id in sections:
		if not section_id or section_id in seen:
			continue
		seen.add(section_id)
		students = frappe.get_all(
			"LMS Enrollment",
			filters={"section": section_id, "role": "student", "status": "active"},
			pluck="student_id",
		)
		for sid in students:
			if sid:
				try:
					compute_and_store_score(section_id, sid)
				except Exception:
					frappe.log_error(title=f"Engagement score {section_id}/{sid}")
