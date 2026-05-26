"""Seed SIS Default Rule Set với 27 rule theo plan S+V+O."""

from __future__ import annotations

import json

import frappe

from erp.api.erp_sis.timetable.auto_generate.core.default_rules import DEFAULT_RULE_SPECS


# Re-export từ core (single source of truth)
DEFAULT_RULES = DEFAULT_RULE_SPECS


def execute():
	campuses = frappe.get_all("SIS Campus", pluck="name")
	for campus_id in campuses:
		existing = frappe.db.get_value(
			"SIS Timetable Rule Set",
			{"campus_id": campus_id, "is_default": 1},
			"name",
		)
		if existing:
			continue

		doc = frappe.new_doc("SIS Timetable Rule Set")
		doc.title_vn = "SIS Default Rule Set"
		doc.title_en = "SIS Default Rule Set"
		doc.campus_id = campus_id
		doc.is_default = 1
		doc.description = "27 rule mặc định cho auto-gen TKB (S+V+O)"

		for i, (rid, kind, verb, stype, sfilt, params, weight, desc) in enumerate(DEFAULT_RULES):
			doc.append("rules", {
				"rule_id": rid,
				"kind": kind,
				"verb": verb,
				"subject_type": stype,
				"subject_filter": json.dumps(sfilt),
				"params": json.dumps(params),
				"weight": weight,
				"enabled": 1,
				"sort_order": i,
				"description": desc,
			})
		doc.insert(ignore_permissions=True)

	# Gán rule set cho session Configuring chưa có rule_set_id
	if frappe.db.has_column("SIS Timetable Generation Session", "rule_set_id"):
		sessions = frappe.get_all(
			"SIS Timetable Generation Session",
			filters={"status": "Configuring", "rule_set_id": ("is", "not set")},
			fields=["name", "campus_id"],
		)
		for s in sessions:
			rs_id = frappe.db.get_value(
				"SIS Timetable Rule Set",
				{"campus_id": s.campus_id, "is_default": 1},
				"name",
			)
			if rs_id:
				frappe.db.set_value("SIS Timetable Generation Session", s.name, "rule_set_id", rs_id)

	frappe.db.commit()
