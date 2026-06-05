"""Schema params/instance cho UI form động — không import frappe."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# object_kind: None | Slots | Day | SubjectSlot | Int | Pair | DocType
VERB_SCHEMAS: Dict[str, dict] = {
	"no_overlap": {
		"params_schema": {"fields": []},
		"instance_schema": None,
	},
	"exact_count_per_week": {
		"params_schema": {"fields": []},
		"instance_schema": None,
	},
	"at_most_per_scope": {
		"params_schema": {
			"fields": [
				{"name": "scope", "type": "select", "label": "Phạm vi", "options": ["day", "week"], "default": "day", "ui_hidden": True},
				{"name": "source", "type": "text", "label": "Nguồn dữ liệu", "optional": True, "ui_hidden": True},
				{"name": "max", "type": "int", "label": "Giới hạn tối đa", "optional": True, "ui_hidden": True},
				{"name": "global_value", "type": "int", "label": "Giá trị áp dụng chung", "optional": True, "ui_hidden": True},
			],
		},
		"instance_schema": {
			"subject_type": "subject",
			"object_kind": "Int",
			"object_fields": [{"name": "max", "type": "int", "label": "Max tiết/ngày"}],
		},
	},
	"consecutive_required": {
		"params_schema": {
			"fields": [
				{"name": "size", "type": "int", "label": "Kích thước cặp", "default": 2},
				{"name": "no_break", "type": "bool", "label": "Không vắt break", "default": True},
			],
		},
		"instance_schema": {
			"subject_type": "subject",
			"object_kind": "None",
			"object_fields": [],
		},
	},
	"forbidden_at_slots": {
		"params_schema": {
			"fields": [
				{
					"name": "source",
					"type": "select",
					"label": "Chế độ",
					"options": [
						{"value": "teacher.unavailability", "label": "Đọc từ GV bận (DocType)"},
						{"value": "instances", "label": "Instance thủ công"},
					],
					"default": "teacher.unavailability",
				},
			],
		},
		"instance_schema": {
			"subject_type": "teacher",
			"object_kind": "Slots",
			"object_fields": [{"name": "slots", "type": "slot_list", "label": "Slot cấm"}],
		},
	},
	"forbidden_on_day": {
		"params_schema": {
			"fields": [
				{
					"name": "source",
					"type": "select",
					"label": "Chế độ",
					"options": [
						{"value": "instances", "label": "Instance thủ công"},
					],
					"default": "instances",
					"ui_hidden": True,
				},
			],
		},
		"instance_schema": {
			"subject_type": "teacher",
			"object_kind": "Day",
			"object_fields": [{"name": "days", "type": "day_list", "label": "Ngày cấm"}],
		},
	},
	"allow_only_at_slots": {
		"params_schema": {"fields": []},
		"instance_schema": {
			"subject_type": "subject",
			"object_kind": "Slots",
			"object_fields": [{"name": "slots", "type": "slot_list", "label": "Slot được phép"}],
		},
	},
	"exclude_subject": {
		"params_schema": {"fields": []},
		"instance_schema": {
			"subject_type": "class",
			"object_kind": "DocType",
			"object_fields": [
				{"name": "subject_id", "type": "entity", "entity": "timetable_subject", "label": "Môn loại trừ"},
			],
		},
	},
	"pinned_to_slot": {
		"params_schema": {"fields": []},
		"instance_schema": {
			"subject_type": "assignment",
			"object_kind": "SubjectSlot",
			"object_fields": [
				{"name": "subject_id", "type": "entity", "entity": "timetable_subject", "label": "Môn"},
				{"name": "day", "type": "day", "label": "Ngày"},
				{"name": "period_idx", "type": "int", "label": "Tiết (0-based)"},
			],
		},
	},
	"sync_class_pair": {
		"params_schema": {"fields": []},
		"instance_schema": {
			"subject_type": "class",
			"object_kind": "Pair",
			"object_fields": [
				{"name": "subject_id", "type": "entity", "entity": "timetable_subject", "label": "Môn"},
				{"name": "peer_class_id", "type": "entity", "entity": "class", "label": "Lớp đồng bộ"},
			],
		},
	},
	"order_before_same_day": {
		"params_schema": {"fields": []},
		"instance_schema": {
			"subject_type": "subject",
			"object_kind": "DocType",
			"object_fields": [
				{"name": "after_subject_id", "type": "entity", "entity": "timetable_subject", "label": "Môn sau"},
			],
		},
	},
	"at_most_simultaneous": {
		"params_schema": {"fields": []},
		"instance_schema": {
			"subject_type": "subject",
			"object_kind": "Int",
			"object_fields": [{"name": "max_classes", "type": "int", "label": "Max lớp đồng thời"}],
		},
	},
	"max_consecutive": {
		"params_schema": {
			"fields": [
				{"name": "max", "type": "int", "label": "Max liên tiếp", "default": 3},
				{"name": "global", "type": "bool", "label": "Áp dụng global", "default": False},
			],
		},
		"instance_schema": {
			"subject_type": "teacher",
			"object_kind": "Int",
			"object_fields": [{"name": "max", "type": "int", "label": "Max liên tiếp"}],
		},
	},
	"attribute_match": {
		"params_schema": {
			"fields": [
				{"name": "require", "type": "text", "label": "Điều kiện (require)"},
			],
		},
		"instance_schema": None,
	},
	"prefer_slot_range": {
		"params_schema": {
			"fields": [
				{"name": "periods", "type": "int_list", "label": "Tiết ưu tiên (0-based)", "default": [0, 1, 2, 3]},
			],
		},
		"instance_schema": None,
	},
	"spread_across_days": {"params_schema": {"fields": []}, "instance_schema": None},
	"avoid_gap": {"params_schema": {"fields": []}, "instance_schema": None},
	"avoid_single_visit": {"params_schema": {"fields": []}, "instance_schema": None},
	"balance_workload": {"params_schema": {"fields": []}, "instance_schema": None},
}


def get_verb_schema(verb_id: str) -> dict:
	base = VERB_SCHEMAS.get(verb_id, {"params_schema": {"fields": []}, "instance_schema": None})
	return {
		"params_schema": base.get("params_schema") or {"fields": []},
		"instance_schema": base.get("instance_schema"),
	}


def list_verb_schemas() -> List[dict]:
	return [{"verb_id": vid, **get_verb_schema(vid)} for vid in sorted(VERB_SCHEMAS)]
