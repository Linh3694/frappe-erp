"""Helper ràng buộc phòng dùng chung cho các verb."""

from __future__ import annotations

from typing import List


def eligible_room_indices(inp, class_id: str, ts_id: str, room_index_map: dict) -> List[int]:
	"""Tập phòng hợp lệ theo môn/lớp:
	1) Môn gắn homeroom -> phòng chủ nhiệm lớp
	2) Môn có allowed_rooms -> danh sách phòng cho môn
	"""
	class_info = next((c for c in inp.classes if c.name == class_id), None)
	if class_info is None:
		return []

	if inp.subject_is_homeroom.get(ts_id) and class_info.room_id:
		idx = room_index_map.get(class_info.room_id)
		return [idx] if idx is not None else []

	allowed_room_ids = inp.subject_allowed_room_ids.get(ts_id, [])
	valid = [room_index_map[rid] for rid in allowed_room_ids if rid in room_index_map]
	return list(dict.fromkeys(valid))


def restrict_room_for_assignment(ctx, class_id: str, ts_id: str, valid_indices: List[int], *, kind: str, weight: int, tag: str) -> None:
	"""Ràng buộc room_var theo tập phòng hợp lệ cho từng slot của assignment."""
	if not valid_indices:
		return
	inp = ctx.inp
	allowed = [[i] for i in valid_indices]
	for day in inp.working_days:
		for p_idx in range(ctx.num_periods):
			x_var = ctx.x.get((class_id, ts_id, day, p_idx))
			room_var = ctx.room.get((class_id, day, p_idx))
			if x_var is None or room_var is None:
				continue
			if kind == "hard":
				ctx.model.AddAllowedAssignments([room_var], allowed).OnlyEnforceIf(x_var)
				continue

			match = ctx.model.NewBoolVar(f"room_match_{tag}_{class_id}_{ts_id}_{day}_{p_idx}")
			ctx.model.AddAllowedAssignments([room_var], allowed).OnlyEnforceIf(match)
			ctx.model.AddForbiddenAssignments([room_var], allowed).OnlyEnforceIf(match.Not())
			score = ctx.model.NewIntVar(0, 1, f"room_match_score_{tag}_{class_id}_{ts_id}_{day}_{p_idx}")
			ctx.model.Add(score == 1).OnlyEnforceIf([x_var, match])
			ctx.model.Add(score == 0).OnlyEnforceIf([x_var, match.Not()])
			ctx.model.Add(score == 0).OnlyEnforceIf(x_var.Not())
			ctx.objectives.append(score * max(1, weight))

