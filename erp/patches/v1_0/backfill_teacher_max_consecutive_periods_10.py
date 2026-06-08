"""Backfill max tiết liên tiếp GV và rule TKB về mặc định 10."""

from __future__ import annotations

import json

import frappe

from erp.api.erp_sis.timetable.auto_generate.requirements_matrix import LEGACY_DEFAULT_MAX_CONSECUTIVE

_TARGET = LEGACY_DEFAULT_MAX_CONSECUTIVE
_OLD_VALUES = frozenset({None, 0, 3, 4})


def _normalize_max(value) -> int | None:
	try:
		n = int(value)
	except (TypeError, ValueError):
		return None
	return n if n > 0 else None


def _update_rule_params(rule_id: str, params: dict) -> tuple[dict, bool]:
	changed = False
	if rule_id == "limit_consecutive_teaching":
		current = _normalize_max(params.get("max"))
		if current is None or current in _OLD_VALUES or current != _TARGET:
			params["max"] = _TARGET
			changed = True
		return params, changed

	if rule_id != "teacher_max_consecutive":
		return params, False

	if "max" in params:
		current = _normalize_max(params.get("max"))
		if current is None or current in _OLD_VALUES or current != _TARGET:
			params["max"] = _TARGET
			changed = True

	for inst in params.get("instances") or []:
		if not isinstance(inst, dict):
			continue
		obj = inst.get("object")
		if not isinstance(obj, dict) or "max" not in obj:
			continue
		current = _normalize_max(obj.get("max"))
		if current is None or current in _OLD_VALUES or current != _TARGET:
			obj["max"] = _TARGET
			inst["object"] = obj
			changed = True

	return params, changed


def execute():
	# Cập nhật toàn bộ GV — kể cả giá trị cũ 3/4 từ mặc định trước đó
	if frappe.db.has_column("SIS Teacher", "max_consecutive_periods"):
		frappe.db.sql(
			"""
			UPDATE `tabSIS Teacher`
			SET max_consecutive_periods = %(target)s
			""",
			{"target": _TARGET},
		)

	# Đồng bộ params rule toàn trường / per-GV trong rule set
	if frappe.db.table_exists("SIS Timetable Rule"):
		rows = frappe.db.sql(
			"""
			SELECT name, rule_id, params
			FROM `tabSIS Timetable Rule`
			WHERE rule_id IN ('limit_consecutive_teaching', 'teacher_max_consecutive')
			""",
			as_dict=True,
		)
		for row in rows:
			raw = row.get("params") or "{}"
			params = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
			updated, changed = _update_rule_params(row["rule_id"], params)
			if changed:
				frappe.db.set_value(
					"SIS Timetable Rule",
					row["name"],
					"params",
					json.dumps(updated, ensure_ascii=False),
				)

	frappe.db.commit()
