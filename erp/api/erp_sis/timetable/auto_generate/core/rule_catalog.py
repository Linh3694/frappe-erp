"""Catalog 26 rule — metadata cho UI builder."""

from __future__ import annotations

from typing import Dict, List, Optional

from .default_rules import DEFAULT_RULE_SPECS

# rule_id -> metadata UI (bổ sung DEFAULT_RULE_SPECS)
_CATALOG_EXTRA: Dict[str, dict] = {
	"subject_pair_periods": {
		"parameterized": True,
		"object_kind": "None",
		"display_name_vn": "Cặp tiết bắt buộc",
		"subject_label_vn": "Môn",
		"object_label_vn": None,
		"instance_required": True,
		"help_text_vn": "Chọn các môn phải xếp theo cặp 2 tiết liên tiếp trong cùng buổi.",
	},
	"pinned_slot": {
		"parameterized": True,
		"object_kind": "Slots",
		"display_name_vn": "Môn chỉ ở slots chọn",
		"subject_label_vn": "Môn",
		"object_label_vn": "Slot được phép",
		"instance_required": True,
		"help_text_vn": "Mỗi dòng: chọn môn và các slot trên lưới TKB.",
	},
	"teacher_not_at_slot": {
		"parameterized": True,
		"object_kind": "Slots",
		"display_name_vn": "GV không dạy slot",
		"subject_label_vn": "Giáo viên",
		"object_label_vn": "Slot cấm",
		"instance_required": True,
		"help_text_vn": "Mỗi dòng: chọn GV và các slot GV không được dạy.",
	},
	"teacher_not_on_day": {
		"parameterized": True,
		"object_kind": "Day",
		"display_name_vn": "GV không dạy cả ngày",
		"subject_label_vn": "Giáo viên",
		"object_label_vn": "Ngày không dạy",
		"instance_required": True,
		"help_text_vn": "Mỗi dòng: chọn GV và các ngày trong tuần GV không dạy.",
	},
	"class_excluded_subject": {
		"parameterized": True,
		"object_kind": "DocType",
		"display_name_vn": "Lớp không học môn",
		"subject_label_vn": "Lớp",
		"object_label_vn": "Môn loại trừ",
		"instance_required": True,
		"help_text_vn": "Mỗi dòng: chọn lớp và môn lớp đó không học.",
	},
	"pin_class_subject_slot": {
		"parameterized": True,
		"object_kind": "SubjectSlot",
		"display_name_vn": "Pin lớp+môn+slot",
		"subject_label_vn": "Lớp",
		"object_label_vn": "Môn + slot",
		"instance_required": True,
		"help_text_vn": "Mỗi dòng: chọn lớp, môn và slot cố định.",
	},
	"subject_max_n_per_day": {
		"parameterized": True,
		"object_kind": "Int",
		"display_name_vn": "Override max tiết/ngày môn",
		"subject_label_vn": "Môn",
		"object_label_vn": "Max tiết/ngày",
		"instance_required": True,
		"help_text_vn": "Mỗi dòng: chọn môn và giới hạn tiết tối đa mỗi ngày.",
	},
	"class_pair_simultaneous_subject": {
		"parameterized": True,
		"object_kind": "Pair",
		"display_name_vn": "2 lớp cùng môn cùng slot",
		"subject_label_vn": "Lớp",
		"object_label_vn": "Lớp đích + môn",
		"instance_required": True,
		"help_text_vn": "Mỗi dòng: chọn lớp nguồn, lớp đích và môn đồng bộ.",
	},
	"subject_before_subject": {
		"parameterized": True,
		"object_kind": "DocType",
		"display_name_vn": "Thứ tự môn trong ngày",
		"subject_label_vn": "Môn trước",
		"object_label_vn": "Môn sau",
		"instance_required": True,
		"help_text_vn": "Mỗi dòng: môn A phải xếp trước môn B trong cùng ngày.",
	},
	"subject_max_simultaneous_classes": {
		"parameterized": True,
		"object_kind": "Int",
		"display_name_vn": "Max lớp đồng thời",
		"subject_label_vn": "Môn",
		"object_label_vn": "Số lớp tối đa",
		"instance_required": True,
		"help_text_vn": "Mỗi dòng: chọn môn và số lớp tối đa học cùng lúc.",
	},
	"teacher_max_consecutive": {
		"parameterized": True,
		"object_kind": "Int",
		"display_name_vn": "Max liên tiếp (theo GV)",
		"subject_label_vn": "Giáo viên",
		"object_label_vn": "Max tiết liên tiếp",
		"instance_required": False,
		"allow_kind_override": True,
		"help_text_vn": "Mỗi dòng: chọn GV và số tiết liên tiếp tối đa (hoặc dùng params global).",
	},
}

_UI_META_KEYS = (
	"subject_label_vn",
	"object_label_vn",
	"instance_required",
	"help_text_vn",
)


def _build_catalog() -> Dict[str, dict]:
	out: Dict[str, dict] = {}
	for rid, kind, verb, stype, sfilt, params, weight, desc in DEFAULT_RULE_SPECS:
		extra = _CATALOG_EXTRA.get(rid, {})
		entry = {
			"rule_id": rid,
			"display_name_vn": extra.get("display_name_vn") or desc,
			"description": desc,
			"default_kind": kind,
			"verb": verb,
			"subject_type": stype,
			"default_weight": weight,
			"parameterized": extra.get("parameterized", False),
			"object_kind": extra.get("object_kind", "None"),
			"allow_kind_override": extra.get("allow_kind_override", False),
			"default_subject_filter": dict(sfilt or {}),
			"default_params": dict(params or {}),
		}
		for key in _UI_META_KEYS:
			if key in extra:
				entry[key] = extra[key]
		out[rid] = entry
	return out


RULE_CATALOG: Dict[str, dict] = _build_catalog()


def get_catalog_entry(rule_id: str) -> Optional[dict]:
	return RULE_CATALOG.get(rule_id)


def list_rule_catalog() -> List[dict]:
	return list(RULE_CATALOG.values())


def is_parameterized(rule_id: str) -> bool:
	entry = RULE_CATALOG.get(rule_id)
	return bool(entry and entry.get("parameterized"))
