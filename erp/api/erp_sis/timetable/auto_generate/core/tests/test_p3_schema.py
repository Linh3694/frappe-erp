"""Unit test rule catalog + gom instance — không cần frappe."""

from __future__ import annotations

from core.dto import Rule
from core.filter_keys import list_subject_filter_keys
from core.rule_catalog import get_catalog_entry, is_parameterized, list_rule_catalog
from core.verb_schemas import get_verb_schema


def _consolidate_instance_rules(rules):
	"""Copy logic từ rule_loader để test offline."""
	grouped = {}
	order = []
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
				description=rule.description,
			)
			order.append(key)
			if not grouped[key].params["instances"]:
				sf = rule.subject_filter or {}
				subject = None
				for k in ("teacher_ids", "class_ids", "subject_ids"):
					if sf.get(k):
						vals = sf[k]
						subject = vals[0] if isinstance(vals, list) else vals
						break
				if subject:
					grouped[key].params["instances"].append({"subject": subject, "object": {}})
		else:
			base = grouped[key]
			existing = base.params.get("instances") or []
			incoming = (rule.params or {}).get("instances") or []
			if incoming:
				existing.extend(incoming)
			else:
				sf = rule.subject_filter or {}
				subject = None
				for k in ("teacher_ids", "class_ids", "subject_ids"):
					if sf.get(k):
						vals = sf[k]
						subject = vals[0] if isinstance(vals, list) else vals
						break
				if subject:
					existing.append({"subject": subject, "object": {}})
			base.params["instances"] = existing
	return [grouped[k] for k in order]


def test_rule_catalog_has_27_entries():
	assert len(list_rule_catalog()) == 27


def test_teacher_not_at_slot_is_parameterized():
	entry = get_catalog_entry("teacher_not_at_slot")
	assert entry is not None
	assert entry["parameterized"] is True
	assert entry["verb"] == "forbidden_at_slots"


def test_teacher_not_on_day_in_catalog():
	entry = get_catalog_entry("teacher_not_on_day")
	assert entry is not None
	assert entry["parameterized"] is True
	assert entry.get("subject_label_vn") == "Giáo viên"
	assert entry.get("instance_required") is True


def test_subject_pair_periods_manual_only():
	entry = get_catalog_entry("subject_pair_periods")
	assert entry is not None
	assert "requirement.force_pair" not in str(entry.get("default_params", {}))
	assert entry["default_params"].get("size") == 2


def test_forbidden_at_slots_has_instance_schema():
	schema = get_verb_schema("forbidden_at_slots")
	assert schema["instance_schema"]["object_kind"] == "Slots"


def test_assignment_filter_keys():
	keys = list_subject_filter_keys("assignment")
	assert any(k["key"] == "is_heavy" for k in keys)


def test_consolidate_instance_rules_merges_rows():
	r1 = Rule(
		rule_id="teacher_not_at_slot",
		kind="hard",
		verb="forbidden_at_slots",
		subject_type="teacher",
		subject_filter={"teacher_ids": ["T1"]},
		params={"source": "instances"},
	)
	r2 = Rule(
		rule_id="teacher_not_at_slot",
		kind="hard",
		verb="forbidden_at_slots",
		subject_type="teacher",
		subject_filter={},
		params={
			"instances": [{"subject": "T3", "object": {"slots": [{"day": "mon", "period_idx": 0}]}}],
		},
	)
	out = _consolidate_instance_rules([r1, r2])
	assert len(out) == 1
	instances = out[0].params["instances"]
	assert len(instances) == 2
	subjects = {i["subject"] for i in instances}
	assert subjects == {"T1", "T3"}
