"""Load Rule Set từ Frappe DocType -> DTO; fallback offline khi chưa migrate."""

from __future__ import annotations

import json
from typing import List, Optional

import frappe

from .core.dto import Rule, RuleSet
from .core.default_rules import build_default_rule_set
from .core.rule_catalog import get_catalog_entry, is_parameterized


def load_rule_set(rule_set_id: str, overrides_json: str | None = None) -> RuleSet:
	overrides = _parse_overrides(overrides_json)

	if not rule_set_id or not frappe.db.table_exists("SIS Timetable Rule Set"):
		rs = build_default_rule_set("default")
		rs.overrides = overrides
		return rs

	if not frappe.db.exists("SIS Timetable Rule Set", rule_set_id):
		rs = build_default_rule_set("default")
		rs.overrides = overrides
		return rs

	doc = frappe.get_doc("SIS Timetable Rule Set", rule_set_id)
	raw_rules = []
	for row in doc.rules:
		raw_rules.append(Rule(
			rule_id=row.rule_id,
			kind=row.kind,
			verb=row.verb,
			subject_type=row.subject_type,
			subject_filter=_parse_json(row.subject_filter),
			params=_parse_json(row.params),
			weight=int(row.weight or 5),
			enabled=bool(row.enabled),
			allow_kind_override=bool(getattr(row, "allow_kind_override", 0)),
			description=row.description or "",
		))
	rules = _consolidate_instance_rules(raw_rules)
	return RuleSet(name=doc.name, rules=rules, overrides=overrides)


def _consolidate_instance_rules(rules: List[Rule]) -> List[Rule]:
	"""Gom nhiều dòng cùng rule_id parameterized -> params.instances[]."""
	grouped: dict[str, Rule] = {}
	order: List[str] = []

	for rule in rules:
		if not is_parameterized(rule.rule_id):
			key = f"{rule.rule_id}:{id(rule)}"
			grouped[key] = rule
			order.append(key)
			continue

		key = rule.rule_id
		if key not in grouped:
			grouped[key] = Rule(
				rule_id=rule.rule_id,
				kind=rule.kind,
				verb=rule.verb,
				subject_type=rule.subject_type,
				subject_filter=dict(rule.subject_filter),
				params={"instances": list((rule.params or {}).get("instances") or [])},
				weight=rule.weight,
				enabled=rule.enabled,
				allow_kind_override=rule.allow_kind_override,
				description=rule.description,
			)
			order.append(key)
			if not grouped[key].params["instances"]:
				inst = _row_to_instance(rule)
				if inst:
					grouped[key].params["instances"].append(inst)
		else:
			base = grouped[key]
			existing = base.params.get("instances") or []
			incoming = (rule.params or {}).get("instances") or []
			if incoming:
				existing.extend(incoming)
			else:
				inst = _row_to_instance(rule)
				if inst:
					existing.append(inst)
			base.params["instances"] = existing

	return [grouped[k] for k in order]


def _row_to_instance(rule: Rule) -> Optional[dict]:
	"""Chuyển 1 dòng rule parameterized (legacy multi-row) thành 1 instance."""
	sf = rule.subject_filter or {}
	params = dict(rule.params or {})
	subject = params.pop("instance_subject", None)

	for key in ("teacher_ids", "class_ids", "subject_ids", "room_ids"):
		if sf.get(key):
			vals = sf[key]
			subject = vals[0] if isinstance(vals, list) and vals else vals
			break

	if subject is None and sf.get("class_id"):
		subject = sf["class_id"]
	if subject is None and sf.get("before_subject_id"):
		subject = sf["before_subject_id"]

	# object từ params còn lại (trừ meta)
	skip = {"instances", "source", "scope", "global", "max", "size", "no_break", "require", "periods", "global_value"}
	obj = {k: v for k, v in params.items() if k not in skip}
	if not subject and not obj:
		return None
	return {"subject": subject, "object": obj}


def get_default_rule_set_id(campus_id: str) -> Optional[str]:
	if not frappe.db.table_exists("SIS Timetable Rule Set"):
		return None
	return frappe.db.get_value(
		"SIS Timetable Rule Set",
		{"campus_id": campus_id, "is_default": 1},
		"name",
	)


def _parse_overrides(raw) -> dict:
	if not raw:
		return {}
	if isinstance(raw, dict):
		return raw
	try:
		return json.loads(raw)
	except (json.JSONDecodeError, TypeError):
		return {}


def _parse_json(raw) -> dict:
	if not raw:
		return {}
	if isinstance(raw, dict):
		return raw
	try:
		return json.loads(raw)
	except (json.JSONDecodeError, TypeError):
		return {}
