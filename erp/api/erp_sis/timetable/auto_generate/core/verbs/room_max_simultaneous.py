from ..helpers import instances, le_limit
from ..registry import Verb, register_verb


@register_verb("room_max_simultaneous", supports=["room"], kind="both", description="Tối đa N lớp dùng cùng phòng/slot")
class RoomMaxSimultaneous(Verb):
	def _collect_uses(self, ctx, room_idx: int, day: str, p_idx: int):
		uses = []
		for c in ctx.inp.classes:
			room_var = ctx.room.get((c.name, day, p_idx))
			if room_var is None:
				continue
			slot_vars = ctx.vars_for_class_slot(c.name, day, p_idx)
			if not slot_vars:
				continue
			busy = ctx.model.NewBoolVar(f"rms_busy_{c.name}_{day}_{p_idx}_{room_idx}")
			ctx.model.Add(sum(slot_vars) >= 1).OnlyEnforceIf(busy)
			ctx.model.Add(sum(slot_vars) == 0).OnlyEnforceIf(busy.Not())
			at_room = ctx.model.NewBoolVar(f"rms_room_{c.name}_{day}_{p_idx}_{room_idx}")
			ctx.model.Add(room_var == room_idx).OnlyEnforceIf(at_room)
			ctx.model.Add(room_var != room_idx).OnlyEnforceIf(at_room.Not())
			use = ctx.model.NewBoolVar(f"rms_use_{c.name}_{day}_{p_idx}_{room_idx}")
			ctx.model.AddBoolAnd([busy, at_room]).OnlyEnforceIf(use)
			ctx.model.AddBoolOr([busy.Not(), at_room.Not()]).OnlyEnforceIf(use.Not())
			uses.append(use)
		return uses

	def _apply_limit(self, ctx, room_idx: int, limit: int, *, kind: str, weight: int, room_id: str = ""):
		for day in ctx.working_days:
			for p_idx in range(ctx.num_periods):
				uses = self._collect_uses(ctx, room_idx, day, p_idx)
				if not uses:
					continue
				# relaxable=True: ở chế độ chẩn đoán, vượt sức chứa phòng nới thành slack
				# (kind="limit") để định vị "phòng nào quá tải tại slot nào". Lần giải
				# thật giữ cứng vì le_limit chỉ nới khi ctx.diagnostic.
				le_limit(
					ctx,
					uses,
					max(1, limit),
					kind=kind,
					weight=max(1, weight),
					tag=f"room:{room_id or room_idx}:{day}:{p_idx}",
					rule_id="room_max_simultaneous",
					relaxable=True,
					scope={"room_id": room_id or str(room_idx), "day": day, "period_idx": p_idx},
				)

	def _limits(self, ctx, params):
		global_max = int((params or {}).get("max", 1) or 1)
		limit_map = {}
		for inst in instances(params or {}):
			room_id = inst.get("subject")
			if not room_id:
				continue
			obj = inst.get("object") or {}
			limit_map[room_id] = int(obj.get("max", global_max) or global_max)
		return global_max, limit_map

	def apply_hard(self, ctx, subject_set, params):
		if not (ctx.use_room_vars and ctx.room):
			return
		global_max, limit_map = self._limits(ctx, params)
		for room in subject_set:
			room_id = room.name if hasattr(room, "name") else room
			room_idx = ctx.room_index_map.get(room_id)
			if room_idx is None:
				continue
			self._apply_limit(
				ctx,
				room_idx,
				limit_map.get(room_id, global_max),
				kind="hard",
				weight=0,
				room_id=room_id,
			)

	def build_soft(self, ctx, subject_set, params, weight: int):
		if not (ctx.use_room_vars and ctx.room):
			return []
		global_max, limit_map = self._limits(ctx, params)
		for room in subject_set:
			room_id = room.name if hasattr(room, "name") else room
			room_idx = ctx.room_index_map.get(room_id)
			if room_idx is None:
				continue
			self._apply_limit(
				ctx,
				room_idx,
				limit_map.get(room_id, global_max),
				kind="soft",
				weight=weight,
				room_id=room_id,
			)
		return []

