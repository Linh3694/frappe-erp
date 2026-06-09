"""Đánh giá post-hoc rule cứng/mềm trên draft TKB."""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, Dict, List, Tuple

import frappe

from .core.force_pair_check import check_force_pair_violations
from .core.helpers import req_map, sorted_periods
from .core.rule_catalog import get_catalog_entry
from .data_collector import TimetableDataCollector
from .excel_preview import DAY_LABEL_VN, draft_has_variant_index
from .rule_loader import load_rule_set


def _parse_teacher_ids(raw) -> List[str]:
	if not raw:
		return []
	try:
		parsed = json.loads(raw) if isinstance(raw, str) else raw
		return [str(t) for t in parsed if t]
	except (json.JSONDecodeError, TypeError):
		return []


def _display_name(rule_id: str, fallback: str) -> str:
	entry = get_catalog_entry(rule_id)
	return (entry or {}).get("display_name_vn") or fallback


def _class_label(inp, class_id: str) -> str:
	return next((c.title for c in inp.classes if c.name == class_id), class_id)


def _teacher_label(inp, teacher_id: str) -> str:
	teacher = inp.teachers.get(teacher_id)
	if not teacher:
		return teacher_id
	name = (teacher.full_name or "").strip()
	if name and name not in (teacher_id, teacher.user_id):
		return name
	return teacher_id


def _day_label(day: str) -> str:
	return DAY_LABEL_VN.get(day, day)


def _period_label(periods, idx: int) -> str:
	if 0 <= idx < len(periods):
		return periods[idx].period_name or f"Tiết {idx + 1}"
	return f"Tiết {idx + 1}"


def _hard_result(rule_id: str, fallback: str, violations: List[str]) -> Dict:
	return {
		"rule_id": rule_id,
		"display_name_vn": _display_name(rule_id, fallback),
		"status": "fail" if violations else "pass",
		"violations": violations,
		"violations_count": len(violations),
	}


def _soft_result(
	rule_id: str,
	fallback: str,
	violations: List[str],
	*,
	partial_threshold: int = 3,
) -> Dict:
	count = len(violations)
	if count == 0:
		status = "met"
	elif count <= partial_threshold:
		status = "partial"
	else:
		status = "unmet"
	return {
		"rule_id": rule_id,
		"display_name_vn": _display_name(rule_id, fallback),
		"status": status,
		"violations_count": count,
		"violations": violations,
	}


def _load_slots(session_id: str, variant_index: int) -> List[dict]:
	v_clause = "AND variant_index = %(variant_index)s" if draft_has_variant_index() else ""
	return frappe.db.sql(f"""
		SELECT class_id, day_of_week, timetable_column_id, timetable_subject_id,
		       teacher_ids, room_id, period_priority
		FROM `tabSIS_TKB_Gen_Result`
		WHERE session_id = %(session_id)s {v_clause}
	""", {"session_id": session_id, "variant_index": int(variant_index)}, as_dict=True)


def _rule_enabled(rule_set, rule) -> bool:
	ov = (rule_set.overrides or {}).get(rule.rule_id) or {}
	if "enabled" in ov:
		return bool(ov["enabled"])
	return bool(rule.enabled)


def _rule_kind(rule_set, rule) -> str:
	ov = (rule_set.overrides or {}).get(rule.rule_id) or {}
	return ov.get("kind") or rule.kind


def evaluate_draft(session_id: str, variant_index: int = 0) -> Dict:
	session = frappe.get_doc("SIS Timetable Generation Session", session_id)
	collector = TimetableDataCollector(session_id)
	inp = collector.collect()
	slots = _load_slots(session_id, variant_index)

	rule_set = load_rule_set(session.rule_set_id or "", session.rule_overrides)
	periods = sorted_periods(inp)
	col_index = {p.name: i for i, p in enumerate(periods)}
	col_name = {p.name: p.period_name for p in periods}
	class_map = {c.name: c for c in inp.classes}

	hard_results: List[Dict] = []
	soft_results: List[Dict] = []

	# ── Hard: đúng số tiết/tuần ──
	rule = next((r for r in rule_set.rules if r.rule_id == "curriculum_exact_periods"), None)
	if rule and _rule_enabled(rule_set, rule) and _rule_kind(rule_set, rule) == "hard":
		counts: Dict[Tuple[str, str], int] = defaultdict(int)
		for s in slots:
			if s.get("timetable_subject_id"):
				counts[(s["class_id"], s["timetable_subject_id"])] += 1
		failures = []
		for req in inp.requirements:
			if req.periods_per_week <= 0:
				continue
			actual = counts.get((req.class_id, req.timetable_subject_id), 0)
			if actual != req.periods_per_week:
				failures.append(
					f"{_class_label(inp, req.class_id)} — {req.timetable_subject_title}: "
					f"cần {req.periods_per_week}, có {actual}"
				)
		hard_results.append(_hard_result("curriculum_exact_periods", "Đúng số tiết/tuần", failures))

	# ── Hard: GV không trùng slot ──
	rule = next((r for r in rule_set.rules if r.rule_id == "teacher_no_overlap"), None)
	if rule and _rule_enabled(rule_set, rule):
		by_teacher_slot: Dict[Tuple, List[str]] = defaultdict(list)
		for s in slots:
			for t_id in _parse_teacher_ids(s.get("teacher_ids")):
				key = (t_id, s["day_of_week"], s["timetable_column_id"])
				by_teacher_slot[key].append(s["class_id"])
		conflicts = []
		for (t_id, day, col_id), classes in by_teacher_slot.items():
			unique = list(dict.fromkeys(classes))
			if len(unique) > 1:
				class_names = ", ".join(_class_label(inp, c) for c in unique)
				period = col_name.get(col_id, col_id)
				conflicts.append(
					f"{_teacher_label(inp, t_id)} — {_day_label(day)}, {period}: "
					f"dạy {len(unique)} lớp ({class_names})"
				)
		hard_results.append(_hard_result("teacher_no_overlap", "GV không trùng slot", conflicts))

	# ── Hard: max tiết/ngày môn ──
	rule = next((r for r in rule_set.rules if r.rule_id == "subject_max_per_day"), None)
	if rule and _rule_enabled(rule_set, rule) and _rule_kind(rule_set, rule) == "hard":
		day_counts: Dict[Tuple[str, str, str], int] = defaultdict(int)
		for s in slots:
			ts = s.get("timetable_subject_id")
			if ts:
				day_counts[(s["class_id"], ts, s["day_of_week"])] += 1
		violations = []
		for req in inp.requirements:
			max_day = req.max_periods_per_day or 2
			for day in inp.working_days:
				cnt = day_counts.get((req.class_id, req.timetable_subject_id, day), 0)
				if cnt > max_day:
					violations.append(
						f"{req.timetable_subject_title} — lớp {_class_label(inp, req.class_id)}, "
						f"{_day_label(day)}: {cnt} tiết (tối đa {max_day})"
					)
		hard_results.append(_hard_result("subject_max_per_day", "Max tiết/ngày/môn", violations))

	# ── Hard: cặp tiết (force_pair từ ma trận) ──
	pair_failures: List[str] = []
	num_periods = len(periods)
	for req in inp.requirements:
		if not req.force_pair or req.periods_per_week <= 0:
			continue
		class_slots = [
			s for s in slots
			if s["class_id"] == req.class_id
			and s.get("timetable_subject_id") == req.timetable_subject_id
		]
		by_day: Dict[str, List[int]] = defaultdict(list)
		for s in class_slots:
			idx = col_index.get(s["timetable_column_id"])
			if idx is not None:
				by_day[s["day_of_week"]].append(idx)
		raw_violations = check_force_pair_violations(
			num_periods, inp.working_days, dict(by_day), req.periods_per_week
		)
		cls = _class_label(inp, req.class_id)
		for day, p_idx in raw_violations:
			pair_failures.append(
				f"{req.timetable_subject_title} — lớp {cls}, {_day_label(day)}, "
				f"{_period_label(periods, p_idx)}: không có cặp trong buổi"
			)
	if pair_failures:
		hard_results.append(_hard_result("subject_pair_periods", "Cặp tiết bắt buộc", pair_failures))
	elif any(r.force_pair for r in inp.requirements):
		hard_results.append(_hard_result("subject_pair_periods", "Cặp tiết bắt buộc", []))

	# ── Soft: tránh gap GV ──
	rule = next((r for r in rule_set.rules if r.rule_id == "avoid_teacher_gap"), None)
	if rule and _rule_enabled(rule_set, rule):
		gap_details: List[str] = []
		teacher_day_periods: Dict[Tuple[str, str], List[int]] = defaultdict(list)
		for s in slots:
			for t_id in _parse_teacher_ids(s.get("teacher_ids")):
				idx = col_index.get(s["timetable_column_id"])
				if idx is not None:
					teacher_day_periods[(t_id, s["day_of_week"])].append(idx)
		for (t_id, day), indices in teacher_day_periods.items():
			if len(indices) < 2:
				continue
			lo, hi = min(indices), max(indices)
			gaps = (hi - lo + 1) - len(set(indices))
			if gaps > 0:
				gap_details.append(
					f"{_teacher_label(inp, t_id)} — {_day_label(day)}: {gaps} khoảng trống"
				)
		soft_results.append(_soft_result(
			"avoid_teacher_gap", "Tránh gap GV", gap_details, partial_threshold=5
		))

	# ── Soft: rải môn nhiều ngày ──
	rule = next((r for r in rule_set.rules if r.rule_id == "spread_subject_across_week"), None)
	if rule and _rule_enabled(rule_set, rule):
		details: List[str] = []
		subject_days: Dict[Tuple[str, str], set] = defaultdict(set)
		for s in slots:
			ts = s.get("timetable_subject_id")
			if ts:
				subject_days[(s["class_id"], ts)].add(s["day_of_week"])
		for req in inp.requirements:
			if req.periods_per_week < 2:
				continue
			days_used = len(subject_days.get((req.class_id, req.timetable_subject_id), set()))
			if days_used < 2:
				details.append(
					f"{req.timetable_subject_title} — lớp {_class_label(inp, req.class_id)}: "
					f"chỉ {days_used} ngày"
				)
		soft_results.append(_soft_result(
			"spread_subject_across_week", "Rải môn nhiều ngày", details, partial_threshold=5
		))

	# ── Soft: phòng chủ nhiệm ──
	rule = next((r for r in rule_set.rules if r.rule_id == "prefer_home_room"), None)
	if rule and _rule_enabled(rule_set, rule):
		home_violations: List[str] = []
		for s in slots:
			if not s.get("timetable_subject_id"):
				continue
			cls = class_map.get(s["class_id"])
			if not cls or not cls.room_id:
				continue
			if s.get("room_id") and s["room_id"] != cls.room_id:
				subj = frappe.db.get_value(
					"SIS Timetable Subject", s["timetable_subject_id"], "title_vn"
				) or s["timetable_subject_id"]
				col = col_name.get(s["timetable_column_id"], s["timetable_column_id"])
				home_violations.append(
					f"{subj} — lớp {_class_label(inp, s['class_id'])}, "
					f"{_day_label(s['day_of_week'])} {col}: không dùng phòng chủ nhiệm"
				)
		soft_results.append(_soft_result(
			"prefer_home_room", "Phòng chủ nhiệm", home_violations, partial_threshold=10
		))

	# ── Soft: cân bằng tiết/tuần GV ──
	rule = next((r for r in rule_set.rules if r.rule_id == "balance_workload_across_week"), None)
	if rule and _rule_enabled(rule_set, rule):
		teacher_day_load: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
		for s in slots:
			for t_id in _parse_teacher_ids(s.get("teacher_ids")):
				teacher_day_load[t_id][s["day_of_week"]] += 1
		details = []
		for t_id, day_load in teacher_day_load.items():
			if not day_load:
				continue
			vals = list(day_load.values())
			diff = max(vals) - min(vals)
			if diff > 2:
				details.append(f"{_teacher_label(inp, t_id)}: lệch {diff} tiết/ngày")
		soft_results.append(_soft_result(
			"balance_workload_across_week", "Cân bằng tiết/tuần", details, partial_threshold=3
		))

	# ── Soft: tiết ưu tiên ──
	rule = next((r for r in rule_set.rules if r.rule_id == "subject_preferred_periods"), None)
	if rule and _rule_enabled(rule_set, rule):
		instances = (rule.params or {}).get("instances") or []
		preferred_by_subject: Dict[str, set] = {}
		for inst in instances:
			subj = (inst.get("subject") or {}).get("value")
			periods_pref = (inst.get("object") or {}).get("periods") or (inst.get("object") or {}).get("value")
			if subj and periods_pref:
				preferred_by_subject[subj] = set(int(p) for p in periods_pref)
		pref_violations: List[str] = []
		for s in slots:
			ts = s.get("timetable_subject_id")
			if not ts or ts not in preferred_by_subject:
				continue
			pp = s.get("period_priority") or 0
			if pp not in preferred_by_subject[ts]:
				subj = frappe.db.get_value("SIS Timetable Subject", ts, "title_vn") or ts
				col = col_name.get(s["timetable_column_id"], s["timetable_column_id"])
				pref_violations.append(
					f"{subj} — lớp {_class_label(inp, s['class_id'])}, "
					f"{_day_label(s['day_of_week'])} {col}: ngoài tiết ưu tiên"
				)
		soft_results.append(_soft_result(
			"subject_preferred_periods", "Tiết ưu tiên", pref_violations, partial_threshold=5
		))

	# Solver warnings từ session
	solver_warnings: List[str] = []
	if session.solver_stats:
		try:
			stats = json.loads(session.solver_stats) if isinstance(session.solver_stats, str) else session.solver_stats
			solver_warnings = list(stats.get("warnings") or [])
		except (json.JSONDecodeError, TypeError):
			pass

	return {
		"hard_rules": hard_results,
		"soft_rules": soft_results,
		"solver_warnings": solver_warnings,
	}
