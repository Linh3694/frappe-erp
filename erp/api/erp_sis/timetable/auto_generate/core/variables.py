"""Tạo biến CP-SAT x[class, subject, day, period_idx]."""

from __future__ import annotations

from .context import SolverContext


def create_variables(ctx: SolverContext) -> None:
	inp = ctx.inp
	for c in inp.classes:
		grade = c.education_grade_id
		for ts_id in inp.grade_subjects.get(grade, []):
			for day in inp.working_days:
				for p_idx, period in enumerate(sorted(inp.periods, key=lambda x: x.period_priority)):
					key = (c.name, ts_id, day, p_idx)
					ctx.x[key] = ctx.model.NewBoolVar(f"x_{c.name}_{ts_id}_{day}_{p_idx}")
					ctx.period_index_map[period.name] = p_idx

	for i, r in enumerate(inp.rooms):
		ctx.room_index_map[r.name] = i
		ctx.room_list.append(r.name)
