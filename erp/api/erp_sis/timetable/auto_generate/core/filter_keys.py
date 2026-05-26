"""Whitelist filter keys cho SubjectResolver — dùng UI picker."""

from __future__ import annotations

from typing import Dict, List

FILTER_KEYS: Dict[str, List[dict]] = {
	"class": [
		{"key": "class_ids", "type": "id_list", "label": "Lớp", "entity": "class"},
		{"key": "grade_ids", "type": "id_list", "label": "Khối", "entity": "grade"},
		{"key": "education_stage_id", "type": "id", "label": "Cấp học", "entity": "education_stage"},
	],
	"teacher": [
		{"key": "teacher_ids", "type": "id_list", "label": "Giáo viên", "entity": "teacher"},
		{"key": "department_id", "type": "id", "label": "Tổ CM", "entity": "department", "optional": True},
	],
	"room": [
		{"key": "room_ids", "type": "id_list", "label": "Phòng", "entity": "room"},
		{"key": "room_type", "type": "text", "label": "Loại phòng"},
	],
	"subject": [
		{"key": "subject_ids", "type": "id_list", "label": "Môn TKB", "entity": "timetable_subject"},
		{"key": "is_heavy", "type": "bool", "label": "Môn nặng"},
		{"key": "force_pair", "type": "bool", "label": "Bắt buộc cặp tiết"},
	],
	"assignment": [
		{"key": "class_ids", "type": "id_list", "label": "Lớp", "entity": "class"},
		{"key": "subject_ids", "type": "id_list", "label": "Môn TKB", "entity": "timetable_subject"},
		{"key": "has_room_type_required", "type": "bool", "label": "Có yêu cầu loại phòng"},
		{"key": "is_heavy", "type": "bool", "label": "Môn nặng"},
	],
	"session_scope": [],
}


def list_subject_filter_keys(subject_type: str) -> List[dict]:
	return list(FILTER_KEYS.get(subject_type, []))
