"""Đánh giá post-hoc rule cứng/mềm trên draft TKB."""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Dict, List, Tuple

import frappe

from .core.helpers import req_map, sorted_periods
from .core.rule_catalog import get_catalog_entry
from .data_collector import TimetableDataCollector
from .excel_preview import draft_has_variant_index
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
	class_map = {c.name: c for c in inp.classes}
	rmap = req_map(inp)

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
				cls = next((c.title for c in inp.classes if c.name == req.class_id), req.class_id)
				failures.append(
					f"{cls} — {req.timetable_subject_title}: cần {req.periods_per_week}, có {actual}"
				)
		hard_results.append({
			"rule_id": "curriculum_exact_periods",
			"display_name_vn": _display_name("curriculum_exact_periods", "Đúng số tiết/tuần"),
			"status": "fail" if failures else "pass",
			"detail": "; ".join(failures[:5]) if failures else None,
		})

	# ── Hard: GV không trùng slot ──
	rule = next((r for r in rule_set.rules if r.rule_id == "teacher_no_overlap"), None)
	if rule and _rule_enabled(rule_set, rule):
		by_teacher_slot: Dict[Tuple, List[str]] = defaultdict(list)
		for s in slots:
			for t_id in _parse_teacher_ids(s.get("teacher_ids")):
				key = (t_id, s["day_of_week"], s["timetable_column_id"])
				by_teacher_slot[key].append(s["class_id"])
		conflicts = []
		for (t_id, day, col), classes in by_teacher_slot.items():
			unique = list(dict.fromkeys(classes))
			if len(unique) > 1:
				conflicts.append(f"GV {t_id} dạy {len(unique)} lớp cùng {day}/{col}")
		hard_results.append({
			"rule_id": "teacher_no_overlap",
			"display_name_vn": _display_name("teacher_no_overlap", "GV không trùng slot"),
			"status": "fail" if conflicts else "pass",
			"detail": "; ".join(conflicts[:5]) if conflicts else None,
		})

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
						f"{req.timetable_subject_title} lớp {req.class_id}: {cnt}>{max_day} tiết/{day}"
					)
		hard_results.append({
			"rule_id": "subject_max_per_day",
			"display_name_vn": _display_name("subject_max_per_day", "Max tiết/ngày/môn"),
			"status": "fail" if violations else "pass",
			"detail": "; ".join(violations[:5]) if violations else None,
		})

	# ── Hard: cặp tiết (force_pair từ ma trận) ──
	pair_failures = []
	for req in inp.requirements:
		if not req.force_pair or req.periods_per_week <= 0:
			continue
		class_slots = [s for s in slots if s["class_id"] == req.class_id
		               and s.get("timetable_subject_id") == req.timetable_subject_id]
		by_day: Dict[str, List[int]] = defaultdict(list)
		for s in class_slots:
			idx = col_index.get(s["timetable_column_id"])
			if idx is not None:
				by_day[s["day_of_week"]].append(idx)
		for day, indices in by_day.items():
			indices.sort()
			if req.periods_per_week % 2 == 0:
				# Chẵn: mọi tiết phải thành cặp liên tiếp
				used = set()
				for i in indices:
					if i in used:
						continue
					if i + 1 in indices:
						used.add(i)
						used.add(i + 1)
					else:
						pair_failures.append(
							f"{req.timetable_subject_title} ({req.class_id}) {day}: tiết {i+1} không có cặp"
						)
			else:
				# Lẻ: đúng 1 tiết lẻ
				unpaired = [i for i in indices if (i - 1) not in indices and (i + 1) not in indices]
				if len(unpaired) != 1:
					pair_failures.append(
						f"{req.timetable_subject_title} ({req.class_id}) {day}: cần 1 tiết lẻ, có {len(unpaired)}"
					)
	if pair_failures:
		hard_results.append({
			"rule_id": "subject_pair_periods",
			"display_name_vn": _display_name("subject_pair_periods", "Cặp tiết bắt buộc"),
			"status": "fail",
			"detail": "; ".join(pair_failures[:5]),
		})
	elif any(r.force_pair for r in inp.requirements):
		hard_results.append({
			"rule_id": "subject_pair_periods",
			"display_name_vn": _display_name("subject_pair_periods", "Cặp tiết bắt buộc"),
			"status": "pass",
		})

	# ── Soft: tránh gap GV ──
	rule = next((r for r in rule_set.rules if r.rule_id == "avoid_teacher_gap"), None)
	if rule and _rule_enabled(rule_set, rule):
		gap_count = 0
		gap_details = []
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
				gap_count += gaps
				if len(gap_details) < 3:
					gap_details.append(f"GV {t_id} {day}: {gaps} gap")
		status = "met" if gap_count == 0 else ("partial" if gap_count <= 3 else "unmet")
		soft_results.append({
			"rule_id": "avoid_teacher_gap",
			"display_name_vn": _display_name("avoid_teacher_gap", "Tránh gap GV"),
			"status": status,
			"violations_count": gap_count,
			"detail": "; ".join(gap_details) if gap_details else None,
		})

	# ── Soft: rải môn nhiều ngày ──
	rule = next((r for r in rule_set.rules if r.rule_id == "spread_subject_across_week"), None)
	if rule and _rule_enabled(rule_set, rule):
		spread_violations = 0
		details = []
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
				spread_violations += 1
				if len(details) < 3:
					details.append(f"{req.timetable_subject_title} ({req.class_id}): chỉ {days_used} ngày")
		status = "met" if spread_violations == 0 else ("partial" if spread_violations <= 2 else "unmet")
		soft_results.append({
			"rule_id": "spread_subject_across_week",
			"display_name_vn": _display_name("spread_subject_across_week", "Rải môn nhiều ngày"),
			"status": status,
			"violations_count": spread_violations,
			"detail": "; ".join(details) if details else None,
		})

	# ── Soft: phòng chủ nhiệm ──
	rule = next((r for r in rule_set.rules if r.rule_id == "prefer_home_room"), None)
	if rule and _rule_enabled(rule_set, rule):
		total_with_room = 0
		non_home = 0
		for s in slots:
			if not s.get("timetable_subject_id"):
				continue
			cls = class_map.get(s["class_id"])
			if not cls or not cls.room_id:
				continue
			total_with_room += 1
			if s.get("room_id") and s["room_id"] != cls.room_id:
				non_home += 1
		pct = int(100 * non_home / total_with_room) if total_with_room else 0
		status = "met" if pct <= 10 else ("partial" if pct <= 30 else "unmet")
		soft_results.append({
			"rule_id": "prefer_home_room",
			"display_name_vn": _display_name("prefer_home_room", "Phòng chủ nhiệm"),
			"status": status,
			"violations_count": non_home,
			"detail": f"{pct}% slot không dùng phòng chủ nhiệm ({non_home}/{total_with_room})" if total_with_room else None,
		})

	# ── Soft: cân bằng tiết/tuần GV ──
	rule = next((r for r in rule_set.rules if r.rule_id == "balance_workload_across_week"), None)
	if rule and _rule_enabled(rule_set, rule):
		teacher_day_load: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
		for s in slots:
			for t_id in _parse_teacher_ids(s.get("teacher_ids")):
				teacher_day_load[t_id][s["day_of_week"]] += 1
		imbalance = 0
		details = []
		for t_id, day_load in teacher_day_load.items():
			if not day_load:
				continue
			vals = list(day_load.values())
			diff = max(vals) - min(vals)
			if diff > 2:
				imbalance += 1
				if len(details) < 3:
					details.append(f"GV {t_id}: lệch {diff} tiết/ngày")
		status = "met" if imbalance == 0 else ("partial" if imbalance <= 2 else "unmet")
		soft_results.append({
			"rule_id": "balance_workload_across_week",
			"display_name_vn": _display_name("balance_workload_across_week", "Cân bằng tiết/tuần"),
			"status": status,
			"violations_count": imbalance,
			"detail": "; ".join(details) if details else None,
		})

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
		off_pref = 0
		for s in slots:
			ts = s.get("timetable_subject_id")
			if not ts or ts not in preferred_by_subject:
				continue
			pp = s.get("period_priority") or 0
			if pp not in preferred_by_subject[ts]:
				off_pref += 1
		status = "met" if off_pref == 0 else ("partial" if off_pref <= 5 else "unmet")
		soft_results.append({
			"rule_id": "subject_preferred_periods",
			"display_name_vn": _display_name("subject_preferred_periods", "Tiết ưu tiên"),
			"status": status,
			"violations_count": off_pref,
			"detail": f"{off_pref} tiết ngoài danh sách ưu tiên" if off_pref else None,
		})

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
