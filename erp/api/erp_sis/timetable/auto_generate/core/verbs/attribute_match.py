from ..helpers import req_map
from ..registry import Verb, register_verb


@register_verb("attribute_match", supports=["assignment"], kind="both", description="Khớp thuộc tính (phòng, loại phòng)")
class AttributeMatch(Verb):
	def apply_hard(self, ctx, subject_set, params):
		# Hard room_type: validate trước solve; không có biến phòng trong CP-SAT
		pass

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
