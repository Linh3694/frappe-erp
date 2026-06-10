"""Refactor rule phòng trên các Rule Set hiện có.

- Xoá hẳn row room_no_overlap + prefer_home_room + room_type_match (không còn dùng).
- Luôn bật room_max_simultaneous + room_eligibility (append từ spec mặc định nếu thiếu).
- Đảm bảo room_max_simultaneous có params.max = 1 (mặc định mỗi phòng 1 lớp/slot).
"""

from __future__ import annotations

import json

import frappe

from erp.api.erp_sis.timetable.auto_generate.core.default_rules import DEFAULT_RULE_SPECS

REMOVE_RULE_IDS = ("room_no_overlap", "prefer_home_room", "room_type_match")
ALWAYS_ON_RULE_IDS = ("room_max_simultaneous", "room_eligibility")

_SPEC_MAP = {
	rid: (kind, verb, stype, sfilt, params, weight, desc)
	for rid, kind, verb, stype, sfilt, params, weight, desc in DEFAULT_RULE_SPECS
}


def _load_params(raw) -> dict:
	if not raw:
		return {}
	try:
		parsed = json.loads(raw)
	except (ValueError, TypeError):
		return {}
	return parsed if isinstance(parsed, dict) else {}


def execute():
	if not frappe.db.table_exists("SIS Timetable Rule Set"):
		return

	# 1) Xoá hẳn row rule đã bỏ
	frappe.db.sql(
		"""
		DELETE FROM `tabSIS Timetable Rule`
		WHERE parenttype = 'SIS Timetable Rule Set'
		  AND rule_id IN ('room_no_overlap', 'prefer_home_room', 'room_type_match')
		"""
	)

	# 2) Luôn bật room_max_simultaneous + room_eligibility trên mọi rule set
	for rs_id in frappe.get_all("SIS Timetable Rule Set", pluck="name"):
		doc = frappe.get_doc("SIS Timetable Rule Set", rs_id)
		existing = {row.rule_id: row for row in (doc.rules or [])}
		max_sort = max((int(row.sort_order or 0) for row in (doc.rules or [])), default=0)

		for rid in ALWAYS_ON_RULE_IDS:
			row = existing.get(rid)
			if row is None:
				spec = _SPEC_MAP.get(rid)
				if not spec:
					continue
				kind, verb, stype, sfilt, params, weight, desc = spec
				max_sort += 1
				doc.append("rules", {
					"rule_id": rid,
					"kind": kind,
					"verb": verb,
					"subject_type": stype,
					"subject_filter": json.dumps(sfilt or {}),
					"params": json.dumps(params or {}),
					"weight": weight,
					"enabled": 1,
					"sort_order": max_sort,
					"description": desc,
				})
				continue

			row.enabled = 1
			if rid == "room_max_simultaneous":
				params = _load_params(row.params)
				if not params.get("max"):
					params["max"] = 1
					row.params = json.dumps(params)

		doc.save(ignore_permissions=True)

	frappe.db.commit()
