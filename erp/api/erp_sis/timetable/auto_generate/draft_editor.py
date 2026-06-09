"""Chỉnh sửa draft TKB sau khi solver sinh kết quả."""

from __future__ import annotations

import json
import uuid
from typing import Dict, List, Optional

import frappe

from .core.helpers import req_map, resolve_room_id
from .data_collector import TimetableDataCollector
from .excel_preview import draft_has_variant_index


def _parse_teacher_ids(raw) -> List[str]:
	if not raw:
		return []
	try:
		parsed = json.loads(raw) if isinstance(raw, str) else raw
		return [str(t) for t in parsed if t]
	except (json.JSONDecodeError, TypeError):
		return []


def _variant_clause() -> str:
	return "AND variant_index = %(variant_index)s" if draft_has_variant_index() else ""


def update_draft_slot(
	session_id: str,
	variant_index: int,
	class_id: str,
	day_of_week: str,
	timetable_column_id: str,
	timetable_subject_id: Optional[str] = None,
) -> Dict:
	"""Cập nhật / xóa 1 ô draft; tự resolve GV và phòng."""
	if not all([class_id, day_of_week, timetable_column_id]):
		frappe.throw("Thiếu class_id, day_of_week hoặc timetable_column_id")

	session = frappe.get_doc("SIS Timetable Generation Session", session_id)
	if session.status != "Completed":
		frappe.throw("Chỉ chỉnh sửa draft khi session ở trạng thái Completed")

	collector = TimetableDataCollector(session_id)
	inp = collector.collect()
	class_info = next((c for c in inp.classes if c.name == class_id), None)
	if not class_info:
		frappe.throw(f"Lớp {class_id} không thuộc phiên")

	rmap = req_map(inp)
	v_clause = _variant_clause()
	params = {
		"session_id": session_id,
		"variant_index": int(variant_index),
		"class_id": class_id,
		"day_of_week": day_of_week,
		"timetable_column_id": timetable_column_id,
	}

	existing = frappe.db.sql(f"""
		SELECT name, timetable_subject_id FROM `tabSIS_TKB_Gen_Result`
		WHERE session_id = %(session_id)s AND class_id = %(class_id)s
		  AND day_of_week = %(day_of_week)s AND timetable_column_id = %(timetable_column_id)s
		  {v_clause}
		LIMIT 1
	""", params, as_dict=True)

	warnings: List[str] = []

	# Xóa slot nếu không chọn môn
	if not timetable_subject_id:
		if existing:
			frappe.db.sql("DELETE FROM `tabSIS_TKB_Gen_Result` WHERE name = %s", existing[0].name)
			frappe.db.commit()
		return {"action": "deleted", "warnings": warnings}

	allowed = set(inp.class_subjects.get(class_id, []))
	if timetable_subject_id not in allowed:
		frappe.throw("Môn không thuộc lớp hoặc chưa có trong ma trận định biên")

	period_priority = frappe.db.get_value("SIS Timetable Column", timetable_column_id, "period_priority") or 0
	key_a = f"{class_id}|{timetable_subject_id}"
	teacher_ids = list(inp.class_subject_teachers.get(key_a, []))
	room_id = resolve_room_id(inp, class_info, timetable_subject_id, rmap)

	# Cảnh báo xung đột GV (không chặn)
	for t_id in teacher_ids:
		conflicts = frappe.db.sql(f"""
			SELECT r.class_id, c.title
			FROM `tabSIS_TKB_Gen_Result` r
			LEFT JOIN `tabSIS Class` c ON c.name = r.class_id
			WHERE r.session_id = %(session_id)s {v_clause}
			  AND r.day_of_week = %(day_of_week)s
			  AND r.timetable_column_id = %(timetable_column_id)s
			  AND r.class_id != %(class_id)s
			  AND r.teacher_ids LIKE %(tid)s
		""", {**params, "tid": f"%{t_id}%"}, as_dict=True)
		for cf in conflicts:
			warnings.append(f"GV {t_id} đã dạy lớp {cf.get('title') or cf['class_id']} cùng slot")

	teacher_json = json.dumps(teacher_ids)

	if existing:
		frappe.db.sql("""
			UPDATE `tabSIS_TKB_Gen_Result`
			SET timetable_subject_id = %(ts_id)s,
			    teacher_ids = %(teacher_ids)s,
			    room_id = %(room_id)s,
			    period_priority = %(period_priority)s
			WHERE name = %(name)s
		""", {
			"name": existing[0].name,
			"ts_id": timetable_subject_id,
			"teacher_ids": teacher_json,
			"room_id": room_id or "",
			"period_priority": period_priority,
		})
		action = "updated"
	else:
		row_name = f"DRAFT-{uuid.uuid4().hex[:12]}"
		cols = ["name", "session_id", "class_id", "day_of_week", "timetable_column_id",
		        "timetable_subject_id", "teacher_ids", "room_id", "period_priority"]
		vals = [row_name, session_id, class_id, day_of_week, timetable_column_id,
		        timetable_subject_id, teacher_json, room_id or "", period_priority]
		if draft_has_variant_index():
			cols.append("variant_index")
			vals.append(int(variant_index))
		placeholders = ", ".join(["%s"] * len(cols))
		frappe.db.sql(
			f"INSERT INTO `tabSIS_TKB_Gen_Result` ({', '.join(f'`{c}`' for c in cols)}) VALUES ({placeholders})",
			tuple(vals),
		)
		action = "inserted"

	frappe.db.commit()

	subject_title = frappe.db.get_value("SIS Timetable Subject", timetable_subject_id, "title_vn") or timetable_subject_id
	teacher_names = []
	if teacher_ids:
		rows = frappe.db.sql("""
			SELECT t.name, COALESCE(NULLIF(u.full_name, ''), u.first_name, t.name) AS full_name
			FROM `tabSIS Teacher` t
			LEFT JOIN `tabUser` u ON u.name = t.user_id
			WHERE t.name IN %(ids)s
		""", {"ids": teacher_ids}, as_dict=True)
		teacher_names = [r["full_name"] for r in rows]

	room_title = ""
	if room_id:
		room_title = frappe.db.get_value(
			"ERP Administrative Room", room_id, "physical_code"
		) or frappe.db.get_value("ERP Administrative Room", room_id, "title_vn") or ""

	return {
		"action": action,
		"warnings": warnings,
		"cell": {
			"subject_title": subject_title,
			"teacher_names": teacher_names,
			"room_title": room_title or "",
		},
	}
