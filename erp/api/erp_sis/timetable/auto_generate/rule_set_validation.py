"""Validation rule set trước khi lưu — kiểm tra instance bắt buộc."""

from __future__ import annotations

import json
from typing import Any, Dict, List

from .core.rule_catalog import get_catalog_entry

# Rule bắt buộc phải có ít nhất 1 instance khi bật
_STRICT_INSTANCE_RULES = frozenset({"subject_pair_periods", "teacher_not_on_day"})


def _parse_json_field(val: Any) -> dict:
	if isinstance(val, dict):
		return val
	if isinstance(val, str):
		try:
			return json.loads(val) if val else {}
		except json.JSONDecodeError:
			return {}
	return {}


def _instances(params: dict) -> list:
	raw = params.get("instances")
	return raw if isinstance(raw, list) else []


def _instance_valid(rule_id: str, inst: dict, object_kind: str) -> bool:
	obj = inst.get("object") or {}
	has_subject_group = False
	subject_ids = obj.get("subject_ids") or []
	if isinstance(subject_ids, list):
		has_subject_group = len([str(s).strip() for s in subject_ids if s]) > 0
	if rule_id == "class_group_simultaneous_subject" or object_kind == "ClassGroup":
		mode = (obj.get("mode") or "sync").strip().lower()
		ts_id = obj.get("timetable_subject_id") or obj.get("subject_id")
		target_ts_ids = obj.get("target_timetable_subject_ids") or []
		if not isinstance(target_ts_ids, list):
			target_ts_ids = []
		legacy_target = obj.get("target_timetable_subject_id") or obj.get("target_subject_id")
		if legacy_target:
			target_ts_ids = [*target_ts_ids, legacy_target]
		target_ts_ids = [str(s).strip() for s in target_ts_ids if s]
		class_ids = obj.get("class_ids") or []
		if not ts_id:
			return False
		if len([c for c in class_ids if c]) < 2:
			return False
		if mode == "desync":
			valid_targets = [s for s in target_ts_ids if s != ts_id]
			return len(valid_targets) > 0
		return True
	if rule_id == "subject_max_simultaneous_classes":
		subject_ids = obj.get("subject_ids") or []
		if not isinstance(subject_ids, list):
			subject_ids = []
		subject_ids = [str(s).strip() for s in subject_ids if s]
		if not subject_ids and not inst.get("subject"):
			return False
		if obj.get("max_classes") is None and obj.get("max") is None and obj.get("value") is None:
			return False
		return True
	if not inst.get("subject") and not has_subject_group:
		return False
	if rule_id == "teacher_not_on_day" or object_kind == "Day":
		days = obj.get("days") or []
		if not days:
			day = obj.get("day")
			if not day:
				return False
	if object_kind == "Slots":
		slots = obj.get("slots") or []
		if not slots:
			return False
	if object_kind == "Int":
		if obj.get("max") is None and obj.get("max_classes") is None and obj.get("value") is None:
			return False
	if object_kind == "DocType":
		if rule_id == "class_excluded_subject" and not obj.get("subject_id"):
			return False
		if rule_id == "subject_before_subject" and not obj.get("before_subject_id"):
			return False
	if object_kind == "SubjectSlot":
		if not obj.get("subject_id"):
			return False
		if rule_id == "pin_class_subject_slot":
			if not obj.get("day") or obj.get("period_idx") is None:
				return False
	return True


def validate_rule_rows(rules: List[dict]) -> List[str]:
	"""Trả danh sách lỗi; rỗng = hợp lệ."""
	errors: List[str] = []
	for row in rules or []:
		rule_id = row.get("rule_id") or ""
		if not row.get("enabled"):
			continue
		catalog = get_catalog_entry(rule_id) or {}
		if not catalog.get("instance_required"):
			continue
		params = _parse_json_field(row.get("params"))
		instances = _instances(params)
		display = catalog.get("display_name_vn") or rule_id
		object_kind = catalog.get("object_kind") or "None"
		if rule_id in _STRICT_INSTANCE_RULES and not instances:
			errors.append(f'Rule "{display}": cần ít nhất một điều kiện áp dụng')
			continue
		if not instances:
			continue
		for i, inst in enumerate(instances):
			if not _instance_valid(rule_id, inst, object_kind):
				errors.append(
					f'Rule "{display}" — điều kiện #{i + 1}: chưa đủ chủ ngữ hoặc vị ngữ',
				)
	return errors
