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
	},
	"pinned_slot": {
		"parameterized": True,
		"object_kind": "Slots",
		"display_name_vn": "Môn chỉ ở slots chọn",
	},
	"teacher_not_at_slot": {
		"parameterized": True,
		"object_kind": "Slots",
		"display_name_vn": "GV không dạy slot",
	},
	"teacher_not_on_day": {
		"parameterized": True,
		"object_kind": "Day",
		"display_name_vn": "GV không dạy cả ngày",
	},
	"class_excluded_subject": {
		"parameterized": True,
		"object_kind": "DocType",
		"display_name_vn": "Lớp không học môn",
	},
	"pin_class_subject_slot": {
		"parameterized": True,
		"object_kind": "SubjectSlot",
		"display_name_vn": "Pin lớp+môn+slot",
	},
	"subject_max_n_per_day": {
		"parameterized": True,
		"object_kind": "Int",
		"display_name_vn": "Override max tiết/ngày môn",
	},
	"class_pair_simultaneous_subject": {
		"parameterized": True,
		"object_kind": "Pair",
		"display_name_vn": "2 lớp cùng môn cùng slot",
	},
	"subject_before_subject": {
		"parameterized": True,
		"object_kind": "DocType",
		"display_name_vn": "Thứ tự môn trong ngày",
	},
	"subject_max_simultaneous_classes": {
		"parameterized": True,
		"object_kind": "Int",
		"display_name_vn": "Max lớp đồng thời",
	},
	"teacher_max_consecutive": {
		"parameterized": True,
		"object_kind": "Int",
		"display_name_vn": "Max liên tiếp (theo GV)",
		"allow_kind_override": True,
	},
}


def _build_catalog() -> Dict[str, dict]:
	out: Dict[str, dict] = {}
	for rid, kind, verb, stype, sfilt, params, weight, desc in DEFAULT_RULE_SPECS:
		extra = _CATALOG_EXTRA.get(rid, {})
		out[rid] = {
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
	return out


RULE_CATALOG: Dict[str, dict] = _build_catalog()


def get_catalog_entry(rule_id: str) -> Optional[dict]:
	return RULE_CATALOG.get(rule_id)


def list_rule_catalog() -> List[dict]:
	return list(RULE_CATALOG.values())


def is_parameterized(rule_id: str) -> bool:
	entry = RULE_CATALOG.get(rule_id)
	return bool(entry and entry.get("parameterized"))
