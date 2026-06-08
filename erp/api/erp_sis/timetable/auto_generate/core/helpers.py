"""Helper dùng chung cho verbs — không import frappe."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple


def req_map(inp: Any) -> Dict[Tuple[str, str], Any]:
	return {(r.class_id, r.timetable_subject_id): r for r in inp.requirements}


def teacher_class_subjects(inp: Any) -> Dict[str, List[Tuple[str, str]]]:
	out: Dict[str, List[Tuple[str, str]]] = {}
	for c in inp.classes:
		for ts_id in inp.class_subjects.get(c.name, []):
			key_a = f"{c.name}|{ts_id}"
			for t_id in inp.class_subject_teachers.get(key_a, []):
				out.setdefault(t_id, []).append((c.name, ts_id))
	return out


def class_subject_weekdays(inp: Any) -> Dict[Tuple[str, str], set]:
	out: Dict[Tuple[str, str], set] = {}
	for a in inp.assignments:
		key = (a.class_id, a.timetable_subject_id)
		allowed = set(a.weekdays) if a.weekdays else set(inp.working_days)
		if key not in out:
			out[key] = set()
		out[key].update(allowed)
	return out


def num_periods(inp: Any) -> int:
	return len(inp.periods)


def sorted_periods(inp: Any):
	return sorted(inp.periods, key=lambda x: x.period_priority)


def instances(params: dict) -> list:
	return params.get("instances") or []


def inst_object_int(inst: dict, field: str, default: int) -> int:
	"""Đọc số từ instances[].object[field]; fallback legacy object.value."""
	obj = inst.get("object") or {}
	if field in obj and obj[field] is not None:
		return int(obj[field])
	if "value" in obj and obj["value"] is not None:
		return int(obj["value"])
	return int(default)


def resolve_room_id(inp: Any, class_info, ts_id: str, rmap) -> str:
	req = rmap.get((class_info.name, ts_id))
	if req and req.room_type_required:
		for r in inp.rooms:
			if r.room_type == req.room_type_required:
				return r.name
	return class_info.room_id or ""


def le_limit(ctx, vars_, limit: int, *, kind: str, weight: int, tag: str) -> None:
	"""Ràng buộc sum(vars_) <= limit; hard = constraint, soft = phạt phần vượt (Maximize)."""
	if not vars_:
		return
	if kind == "hard":
		ctx.model.Add(sum(vars_) <= limit)
	else:
		over = ctx.model.NewIntVar(0, len(vars_), f"over_{tag}")
		ctx.model.Add(over >= sum(vars_) - limit)
		ctx.objectives.append(over * (-weight))
