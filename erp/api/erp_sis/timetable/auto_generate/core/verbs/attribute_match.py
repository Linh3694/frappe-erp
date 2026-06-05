from ..helpers import req_map
from ..registry import Verb, register_verb


@register_verb("attribute_match", supports=["assignment"], kind="both", description="Khớp thuộc tính (phòng, loại phòng)")
class AttributeMatch(Verb):
	def apply_hard(self, ctx, subject_set, params):
		require = params.get("require", "")
		if require == "room_type==required" and ctx.use_room_vars and ctx.room:
			self._apply_room_type_match(ctx)
		# room==home_room chỉ soft

	def _apply_room_type_match(self, ctx) -> None:
		"""Môn yêu cầu loại phòng X -> room_var chỉ được gán index phòng loại X."""
		inp = ctx.inp
		rmap = req_map(inp)
		for c in inp.classes:
			grade = c.education_grade_id
			for ts_id in inp.grade_subjects.get(grade, []):
				req = rmap.get((grade, ts_id))
				if not req or not req.room_type_required:
					continue
				valid = [
					ctx.room_index_map[r.name]
					for r in inp.rooms
					if r.room_type == req.room_type_required and r.name in ctx.room_index_map
				]
				if not valid:
					continue
				for day in inp.working_days:
					for p_idx in range(ctx.num_periods):
						x_var = ctx.x.get((c.name, ts_id, day, p_idx))
						room_var = ctx.room.get((c.name, day, p_idx))
						if x_var is None or room_var is None:
							continue
						ctx.model.AddAllowedAssignments([room_var], [[i] for i in valid]).OnlyEnforceIf(x_var)

	def build_soft(self, ctx, subject_set, params, weight: int):
		require = params.get("require", "")
		if require != "room==home_room":
			return []
		inp = ctx.inp
		rmap = req_map(inp)
		bonuses = []
		for c in inp.classes:
			if not c.room_id:
				continue
			g = c.education_grade_id
			for ts_id in inp.grade_subjects.get(g, []):
				req = rmap.get((g, ts_id))
				if req and req.room_type_required:
					continue
				for day in inp.working_days:
					for p_idx in range(ctx.num_periods):
						v = ctx.x.get((c.name, ts_id, day, p_idx))
						if v is not None:
							bonuses.append(v * (weight // 10))
		return bonuses
