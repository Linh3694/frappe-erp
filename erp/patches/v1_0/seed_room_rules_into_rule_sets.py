"""Seed thêm rule phòng mới vào Rule Set hiện có."""

from __future__ import annotations

import json

import frappe

from erp.api.erp_sis.timetable.auto_generate.core.default_rules import DEFAULT_RULE_SPECS


ROOM_RULE_IDS = {"room_no_overlap", "room_type_match", "room_eligibility", "room_max_simultaneous"}


def _ensure_rule_set_scope(doc) -> bool:
	"""Backfill năm học + cấp học cho rule set legacy (seed cũ chỉ có campus)."""
	if doc.school_year_id and doc.education_stage_id:
		return True
	if not doc.campus_id:
		return False

	if not doc.school_year_id:
		doc.school_year_id = frappe.db.get_value(
			"SIS School Year",
			{"is_enable": 1, "campus_id": doc.campus_id},
			"name",
			order_by="start_date desc",
		)
	if not doc.education_stage_id:
		doc.education_stage_id = frappe.db.get_value(
			"SIS Education Stage",
			{"campus_id": doc.campus_id},
			"name",
			order_by="creation asc",
		)

	return bool(doc.school_year_id and doc.education_stage_id)


def execute():
	if not frappe.db.table_exists("SIS Timetable Rule Set"):
		return

	spec_map = {rid: (kind, verb, stype, sfilt, params, weight, desc) for rid, kind, verb, stype, sfilt, params, weight, desc in DEFAULT_RULE_SPECS}
	rule_sets = frappe.get_all("SIS Timetable Rule Set", pluck="name")
	for rs_id in rule_sets:
		doc = frappe.get_doc("SIS Timetable Rule Set", rs_id)
		if not _ensure_rule_set_scope(doc):
			frappe.logger().warning(
				f"seed_room_rules: bỏ qua {rs_id} — thiếu school_year_id/education_stage_id"
			)
			continue

		existing = {row.rule_id for row in (doc.rules or [])}
		max_sort = max((int(row.sort_order or 0) for row in (doc.rules or [])), default=0)

		for rid in ROOM_RULE_IDS:
			spec = spec_map.get(rid)
			if not spec:
				continue
			if rid in existing:
				for row in doc.rules:
					if row.rule_id == rid:
						row.allow_kind_override = 1
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
				"enabled": 0,
				"allow_kind_override": 1,
				"sort_order": max_sort,
				"description": desc,
			})

		doc.save(ignore_permissions=True)

	frappe.db.commit()

