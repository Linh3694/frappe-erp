"""Catalog rule mặc định — metadata cho UI builder."""

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
	"subject_preferred_periods": {
		"parameterized": True,
		"object_kind": "IntList",
		"display_name_vn": "Tiết ưu tiên",
		"subject_label_vn": "Môn",
		"object_label_vn": "Các tiết ưu tiên",
		"instance_required": False,
		"help_text_vn": "Chọn môn và các tiết solver sẽ ưu tiên xếp (áp dụng mọi lớp có môn).",
	},
	"interleave_programs_within_day": {
		"parameterized": False,
		"object_kind": "None",
		"display_name_vn": "Xen kẽ chương trình trong ngày",
		"subject_label_vn": None,
		"object_label_vn": None,
		"instance_required": False,
		"help_text_vn": "Rule mềm hệ thống: ưu tiên xen kẽ và cân bằng chương trình (curriculum_id) trong cùng ngày.",
	},
	"subject_not_at_slot": {
		"parameterized": True,
		"object_kind": "Slots",
		"display_name_vn": "Môn không xếp tại slot",
		"subject_label_vn": "Môn",
		"object_label_vn": "Slot cấm",
		"instance_required": False,
		"help_text_vn": "Chọn môn và slot cấm; có thể giới hạn phạm vi theo lớp/khối, để trống sẽ áp dụng mọi lớp có môn.",
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
	"class_group_simultaneous_subject": {
		"parameterized": True,
		"object_kind": "ClassGroup",
		"display_name_vn": "Nhóm lớp đồng bộ/không đồng bộ môn",
		"subject_label_vn": None,
		"object_label_vn": "Mode + môn + danh sách lớp",
		"instance_required": True,
		"help_text_vn": "Mỗi nhóm: chọn mode, môn chính và ≥2 lớp; mode Không đồng bộ cần thêm môn đối ngược.",
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
	"room_eligibility": {
		"parameterized": False,
		"object_kind": "None",
		"display_name_vn": "Phòng hợp lệ theo môn/lớp",
		"instance_required": False,
		"allow_kind_override": False,
		"help_text_vn": (
			"Giới hạn mỗi (lớp + môn) chỉ được xếp vào phòng hợp lệ của môn: "
			"(1) môn gắn chủ nhiệm → đúng phòng chủ nhiệm của lớp; "
			"(2) môn có danh sách phòng cho phép → chỉ các phòng trong danh sách. "
			"Cấu hình tại Môn học (is_homeroom + danh sách phòng)."
		),
	},
	"room_max_simultaneous": {
		"parameterized": True,
		"object_kind": "Int",
		"display_name_vn": "Max lớp dùng chung phòng",
		"subject_label_vn": "Phòng",
		"object_label_vn": "Số lớp tối đa",
		"instance_required": False,
		"allow_kind_override": False,
		"help_text_vn": (
			"Luôn áp dụng. Mặc định mỗi phòng (gồm phòng lớp học) tối đa 1 lớp/slot; "
			"giáo vụ khai ngoại lệ cho từng phòng chức năng."
		),
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
