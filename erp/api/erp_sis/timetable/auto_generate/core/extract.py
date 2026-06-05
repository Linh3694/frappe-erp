"""Trích xuất solution từ CP-SAT solver."""

from __future__ import annotations

from typing import Any, Dict, List

from .context import SolverContext
from .helpers import req_map, resolve_room_id, sorted_periods


def _resolve_room_for_slot(solver, ctx, class_info, day, p_idx, ts_id, rmap, pin) -> str:
	if pin and pin.room_id:
		return pin.room_id
	room_var = ctx.room.get((class_info.name, day, p_idx))
	if room_var is not None and ctx.room_list:
		idx = solver.Value(room_var)
		if 0 <= idx < len(ctx.room_list):
			return ctx.room_list[idx]
	return resolve_room_id(ctx.inp, class_info, ts_id, rmap)


def extract_solution(solver, ctx: SolverContext) -> List[Dict]:
	inp = ctx.inp
	rmap = req_map(inp)
	periods = sorted_periods(inp)
	results = []

	pin_lookup = {}
	for pin in getattr(inp, "pinned_slots", []) or []:
		p_idx = inp.column_period_index.get(pin.timetable_column_id)
		if p_idx is None:
			continue
		target = [c.name for c in inp.classes if not pin.class_id or c.name == pin.class_id]
		for c_id in target:
			pin_lookup[(c_id, pin.day_of_week, p_idx, pin.timetable_subject_id or "")] = pin

	for c in inp.classes:
		grade = c.education_grade_id
		for ts_id in inp.grade_subjects.get(grade, []):
			for day in inp.working_days:
				for p_idx, period in enumerate(periods):
					key = (c.name, ts_id, day, p_idx)
					if key in ctx.x and solver.Value(ctx.x[key]) == 1:
						key_a = f"{c.name}|{ts_id}"
						teacher_ids = list(inp.class_subject_teachers.get(key_a, []))
						pin = pin_lookup.get((c.name, day, p_idx, ts_id)) or pin_lookup.get((c.name, day, p_idx, ""))
						room_id = _resolve_room_for_slot(solver, ctx, c, day, p_idx, ts_id, rmap, pin)
						if pin and pin.teacher_id:
							teacher_ids = [pin.teacher_id]
						results.append({
							"class_id": c.name,
							"day_of_week": day,
							"timetable_column_id": period.name,
							"timetable_subject_id": ts_id,
							"teacher_ids": teacher_ids,
							"room_id": room_id,
							"period_priority": period.period_priority,
						})
	return results
