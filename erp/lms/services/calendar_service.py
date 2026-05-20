"""Lịch LMS + merge SIS Student Timetable."""

from datetime import timedelta

import frappe
from frappe.utils import get_datetime, getdate

from erp.lms.utils.enrollment import get_student_id_for_user, validate_section_enrollment
from erp.lms.utils.permissions import is_lms_staff, require_lms_staff


def create_calendar_event(data: dict) -> dict:
	require_lms_staff()
	doc = frappe.get_doc({"doctype": "LMS Calendar Event", **data})
	if not doc.campus_id and doc.course:
		doc.campus_id = frappe.db.get_value("LMS Course", doc.course, "campus_id")
	doc.insert()
	return doc.as_dict()


def list_calendar_events(
	course_id: str = None,
	section_id: str = None,
	start: str = None,
	end: str = None,
	user: str | None = None,
) -> list:
	user = user or frappe.session.user
	filters = {}
	if section_id:
		validate_section_enrollment(section_id, user, min_role="observer")
		filters["section"] = section_id
	elif course_id:
		from erp.lms.utils.permissions import user_enrolled_in_course
		if not is_lms_staff(user) and not user_enrolled_in_course(user, course_id):
			frappe.throw("Không có quyền", frappe.PermissionError)
		filters["course"] = course_id
	else:
		frappe.throw("course_id hoặc section_id bắt buộc")

	if start:
		filters["start"] = [">=", start]
	if end:
		filters.setdefault("start", ["<=", end])
		if isinstance(filters.get("start"), list) and filters["start"][0] == ">=":
			# Cả hai bound: dùng SQL filter đơn giản — lấy rộng theo start
			pass

	rows = frappe.get_all(
		"LMS Calendar Event",
		filters=filters,
		fields=[
			"name", "title", "course", "section", "event_type",
			"start", "end", "all_day", "reference_doctype", "reference_name", "description",
		],
		order_by="start asc",
		limit=200,
	)
	if start and end:
		start_dt = get_datetime(start)
		end_dt = get_datetime(end)
		rows = [
			r for r in rows
			if get_datetime(r.start) <= end_dt and (not r.end or get_datetime(r.end) >= start_dt)
		]
	for r in rows:
		r["source"] = "lms"
	return rows


def get_merged_calendar(
	week_start: str = None,
	week_end: str = None,
	section_id: str = None,
	student_id: str = None,
	user: str | None = None,
) -> dict:
	"""
	Merge LMS Calendar Event + SIS Student Timetable cho tuần.
	Query: week_start, week_end (YYYY-MM-DD), section_id hoặc student_id.
	"""
	user = user or frappe.session.user
	student_id = student_id or get_student_id_for_user(user)

	if not week_start:
		today = getdate()
		week_start = str(today - timedelta(days=today.weekday()))
	if not week_end:
		week_end = str(getdate(week_start) + timedelta(days=6))

	lms_events = []
	sis_events = []

	# LMS events từ các section user enrolled
	section_ids = []
	if section_id:
		validate_section_enrollment(section_id, user, min_role="observer")
		section_ids = [section_id]
	elif is_lms_staff(user) and section_id is None:
		# Staff không truyền section — cần section hoặc student
		if not student_id:
			frappe.throw("section_id hoặc student_id bắt buộc cho staff")
	else:
		enrollments = frappe.get_all(
			"LMS Enrollment",
			filters={"user": user, "status": "active"},
			pluck="section",
		)
		if not enrollments and student_id:
			enrollments = frappe.get_all(
				"LMS Enrollment",
				filters={"student_id": student_id, "status": "active", "role": "student"},
				pluck="section",
			)
		section_ids = list(set(enrollments))

	for sec in section_ids:
		lms_events.extend(
			list_calendar_events(
				section_id=sec,
				start=f"{week_start} 00:00:00",
				end=f"{week_end} 23:59:59",
				user=user,
			)
		)

	# Auto due dates từ assignment/quiz
	lms_events.extend(_auto_due_events_for_sections(section_ids, week_start, week_end))

	if student_id:
		sis_events = _fetch_sis_timetable(student_id, week_start, week_end)

	return {
		"week_start": week_start,
		"week_end": week_end,
		"lms_events": lms_events,
		"sis_events": sis_events,
		"events": lms_events + sis_events,
	}


def _auto_due_events_for_sections(section_ids: list, week_start: str, week_end: str) -> list:
	"""Sinh event due từ assignment/quiz có due_at trong tuần."""
	if not section_ids:
		return []
	events = []
	ws = getdate(week_start)
	we = getdate(week_end)

	for doctype, event_type in (("LMS Assignment", "assignment"), ("LMS Quiz", "quiz")):
		rows = frappe.get_all(
			doctype,
			filters={"section": ["in", section_ids], "due_at": ["is", "set"]},
			fields=["name", "title", "course", "section", "due_at"],
		)
		for r in rows:
			d = getdate(r.due_at)
			if ws <= d <= we:
				events.append(
					{
						"name": f"auto-{doctype}-{r.name}",
						"title": r.title,
						"course": r.course,
						"section": r.section,
						"event_type": event_type,
						"start": r.due_at,
						"end": r.due_at,
						"all_day": 0,
						"reference_doctype": doctype,
						"reference_name": r.name,
						"source": "lms",
						"auto_generated": 1,
					}
				)
	return events


def _fetch_sis_timetable(student_id: str, week_start: str, week_end: str) -> list:
	"""Đọc SIS Student Timetable — read-only, source=sis."""
	if not frappe.db.exists("DocType", "SIS Student Timetable"):
		return []

	rows = frappe.get_all(
		"SIS Student Timetable",
		filters={
			"student_id": student_id,
			"date": ["between", [week_start, week_end]],
		},
		fields=[
			"name", "student_id", "class_id", "date", "day_of_week",
			"timetable_column_id", "subject_id", "teacher_1_id", "room_id",
		],
		order_by="date asc, timetable_column_id asc",
	)
	events = []
	for r in rows:
		col = {}
		if r.timetable_column_id:
			col = frappe.db.get_value(
				"SIS Timetable Column",
				r.timetable_column_id,
				["period_name", "start_time", "end_time"],
				as_dict=True,
			) or {}
		subject_title = frappe.db.get_value("SIS Subject", r.subject_id, "title") if r.subject_id else ""
		start_time = col.get("start_time") or "07:00:00"
		end_time = col.get("end_time") or "07:45:00"
		date_str = str(r.date)
		events.append(
			{
				"name": r.name,
				"title": subject_title or col.get("period_name") or "Tiết học",
				"event_type": "sis_class",
				"start": f"{date_str} {start_time}",
				"end": f"{date_str} {end_time}",
				"all_day": 0,
				"class_id": r.class_id,
				"subject_id": r.subject_id,
				"room_id": r.room_id,
				"source": "sis",
				"read_only": 1,
			}
		)
	return events
