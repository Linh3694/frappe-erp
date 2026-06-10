from ..helpers import le_limit
from ..registry import Verb, register_verb


@register_verb("no_overlap", supports=["class", "teacher", "room"], kind="both", description="Tối đa 1 assignment/slot theo entity")
class NoOverlap(Verb):
	def apply_hard(self, ctx, subject_set, params):
		if ctx.cur_subject_type == "class":
			for c in subject_set:
				for day in ctx.working_days:
					for p_idx in range(ctx.num_periods):
						vars_ = ctx.vars_for_class_slot(c.name if hasattr(c, "name") else c, day, p_idx)
						if len(vars_) > 1:
							ctx.model.Add(sum(vars_) <= 1)
		elif ctx.cur_subject_type == "teacher":
			for t_id in subject_set:
				tid = t_id.name if hasattr(t_id, "name") else t_id
				for day in ctx.working_days:
					for p_idx in range(ctx.num_periods):
						vars_ = ctx.vars_for_teacher_slot(tid, day, p_idx)
						if len(vars_) > 1:
							ctx.model.Add(sum(vars_) <= 1)
		elif ctx.cur_subject_type == "room" and ctx.use_room_vars and ctx.room:
			self._apply_room_no_overlap(ctx)

	def _apply_room_no_overlap(self, ctx) -> None:
		"""Mỗi phòng tối đa 1 lớp/slot — dùng biến room[class, day, period]."""
		num_rooms = len(ctx.room_list)
		if num_rooms == 0:
			return
		for day in ctx.working_days:
			for p_idx in range(ctx.num_periods):
				for r_idx in range(num_rooms):
					indicators = []
					for c in ctx.inp.classes:
						room_var = ctx.room.get((c.name, day, p_idx))
						if room_var is None:
							continue
						slot_vars = ctx.vars_for_class_slot(c.name, day, p_idx)
						if not slot_vars:
							continue
						busy = ctx.model.NewBoolVar(f"busy_{c.name}_{day}_{p_idx}_{r_idx}")
						ctx.model.Add(sum(slot_vars) >= 1).OnlyEnforceIf(busy)
						ctx.model.Add(sum(slot_vars) == 0).OnlyEnforceIf(busy.Not())
						at_room = ctx.model.NewBoolVar(f"atroom_{c.name}_{day}_{p_idx}_{r_idx}")
						ctx.model.Add(room_var == r_idx).OnlyEnforceIf(at_room)
						ctx.model.Add(room_var != r_idx).OnlyEnforceIf(at_room.Not())
						uses = ctx.model.NewBoolVar(f"uses_{c.name}_{day}_{p_idx}_{r_idx}")
						ctx.model.AddBoolAnd([busy, at_room]).OnlyEnforceIf(uses)
						ctx.model.AddBoolOr([busy.Not(), at_room.Not()]).OnlyEnforceIf(uses.Not())
						indicators.append(uses)
					if len(indicators) > 1:
						ctx.model.Add(sum(indicators) <= 1)

	def build_soft(self, ctx, subject_set, params, weight: int):
		if not (ctx.cur_subject_type == "room" and ctx.use_room_vars and ctx.room):
			return []
		num_rooms = len(ctx.room_list)
		if num_rooms == 0:
			return []
		for day in ctx.working_days:
			for p_idx in range(ctx.num_periods):
				for r_idx in range(num_rooms):
					indicators = []
					for c in ctx.inp.classes:
						room_var = ctx.room.get((c.name, day, p_idx))
						if room_var is None:
							continue
						slot_vars = ctx.vars_for_class_slot(c.name, day, p_idx)
						if not slot_vars:
							continue
						busy = ctx.model.NewBoolVar(f"soft_busy_{c.name}_{day}_{p_idx}_{r_idx}")
						ctx.model.Add(sum(slot_vars) >= 1).OnlyEnforceIf(busy)
						ctx.model.Add(sum(slot_vars) == 0).OnlyEnforceIf(busy.Not())
						at_room = ctx.model.NewBoolVar(f"soft_room_{c.name}_{day}_{p_idx}_{r_idx}")
						ctx.model.Add(room_var == r_idx).OnlyEnforceIf(at_room)
						ctx.model.Add(room_var != r_idx).OnlyEnforceIf(at_room.Not())
						uses = ctx.model.NewBoolVar(f"soft_use_{c.name}_{day}_{p_idx}_{r_idx}")
						ctx.model.AddBoolAnd([busy, at_room]).OnlyEnforceIf(uses)
						ctx.model.AddBoolOr([busy.Not(), at_room.Not()]).OnlyEnforceIf(uses.Not())
						indicators.append(uses)
					le_limit(
						ctx,
						indicators,
						1,
						kind="soft",
						weight=max(1, weight),
						tag=f"room_overlap_{day}_{p_idx}_{r_idx}",
					)
		return []
