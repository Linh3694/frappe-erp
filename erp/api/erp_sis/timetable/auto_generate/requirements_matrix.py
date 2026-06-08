"""Helper dùng chung cho ma trận số tiết lớp×môn (rule set + session)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def load_subjects(campus_id: str, education_stage_id: str) -> List[dict]:
	"""Môn TKB theo campus + cấp học (kể cả bản ghi chưa gán education_stage_id)."""
	import frappe

	return frappe.db.sql(
		"""
		SELECT name, title_vn, title_en
		FROM `tabSIS Timetable Subject`
		WHERE campus_id = %(campus_id)s
		  AND (
		    education_stage_id = %(stage_id)s
		    OR IFNULL(education_stage_id, '') = ''
		  )
		ORDER BY title_vn
		""",
		{"stage_id": education_stage_id, "campus_id": campus_id},
		as_dict=True,
	)


def load_grade_groups(
	campus_id: str,
	school_year_id: str,
	education_stage_id: str,
	class_ids: Optional[List[str]] = None,
) -> List[dict]:
	"""Trả danh sách khối, mỗi khối kèm các lớp regular thuộc phạm vi."""
	import frappe

	grades = frappe.db.sql(
		"""
		SELECT name, title_vn, grade_code, sort_order
		FROM `tabSIS Education Grade`
		WHERE education_stage_id = %(stage_id)s
		  AND campus_id = %(campus_id)s
		ORDER BY sort_order
		""",
		{"stage_id": education_stage_id, "campus_id": campus_id},
		as_dict=True,
	)

	# JOIN khối để chỉ lấy lớp thuộc đúng cấp học (tránh lệch education_grade)
	sql = """
		SELECT c.name, c.title, c.short_title, c.education_grade AS education_grade_id
		FROM `tabSIS Class` c
		INNER JOIN `tabSIS Education Grade` eg ON c.education_grade = eg.name
		WHERE c.campus_id = %(campus_id)s
		  AND c.school_year_id = %(school_year_id)s
		  AND eg.education_stage_id = %(stage_id)s
		  AND eg.campus_id = %(campus_id)s
		  AND (LOWER(IFNULL(c.class_type, 'regular')) = 'regular')
	"""
	params: Dict[str, Any] = {
		"campus_id": campus_id,
		"school_year_id": school_year_id,
		"stage_id": education_stage_id,
	}
	if class_ids:
		sql += " AND c.name IN %(class_ids)s"
		params["class_ids"] = class_ids
	sql += " ORDER BY eg.sort_order, c.title"

	classes = frappe.db.sql(sql, params, as_dict=True)
	by_grade: Dict[str, List[dict]] = {g["name"]: [] for g in grades}
	for cls in classes:
		gid = cls.get("education_grade_id")
		if gid in by_grade:
			by_grade[gid].append({
				"name": cls["name"],
				"title_vn": cls.get("title") or cls["name"],
				"short_title": cls.get("short_title"),
				"education_grade_id": gid,
			})

	out = []
	for g in grades:
		out.append({
			"grade": {
				"name": g["name"],
				"title_vn": g["title_vn"],
				"grade_code": g.get("grade_code"),
				"sort_order": g.get("sort_order"),
			},
			"classes": by_grade.get(g["name"], []),
		})
	return out


def compute_max_slots(
	schedule_id: Optional[str],
	campus_id: str,
	education_stage_id: str,
) -> dict:
	"""Tính slot/tuần từ tiết study của schedule (khớp logic solver)."""
	import frappe

	study_periods_count = 0
	if schedule_id:
		# Chỉ đếm tiết học (study) thuộc khung giờ đã chọn
		study_periods_count = frappe.db.count(
			"SIS Timetable Column",
			filters={"schedule_id": schedule_id, "period_type": "study"},
		)
	if not study_periods_count:
		# Legacy: tiết study không gắn schedule — tránh cộng dồn nhiều kỳ học
		study_periods_count = frappe.db.sql(
			"""
			SELECT COUNT(*)
			FROM `tabSIS Timetable Column`
			WHERE campus_id = %(campus_id)s
			  AND education_stage_id = %(education_stage_id)s
			  AND period_type = 'study'
			  AND IFNULL(schedule_id, '') = ''
			""",
			{"campus_id": campus_id, "education_stage_id": education_stage_id},
		)[0][0]

	working_days = 5
	default_per_day = 10
	per_day = int(study_periods_count or 0) or default_per_day
	max_slots_per_week = per_day * working_days
	return {
		"study_periods_per_day": per_day,
		"working_days": working_days,
		"max_slots_per_week": max_slots_per_week,
	}


def req_cell_key(class_id: str, subject_id: str) -> str:
	return f"{class_id}|{subject_id}"


def normalize_requirement_row(row: dict) -> dict:
	"""Chuẩn hóa 1 ô ma trận từ DB/API."""
	return {
		"class_id": row.get("class_id"),
		"timetable_subject_id": row.get("timetable_subject_id"),
		"periods_per_week": int(row.get("periods_per_week") or 0),
		"max_periods_per_day": int(row.get("max_periods_per_day") or 2),
		"prefer_consecutive": bool(row.get("prefer_consecutive")),
		"force_pair": bool(row.get("force_pair")),
		"room_type_required": row.get("room_type_required") or "",
	}


def index_requirements(rows: List[dict]) -> dict:
	out = {}
	for r in rows:
		cid = r.get("class_id")
		sid = r.get("timetable_subject_id")
		if not cid or not sid:
			continue
		key = req_cell_key(cid, sid)
		out[key] = normalize_requirement_row(r)
		if r.get("name"):
			out[key]["name"] = r["name"]
	return out
