from ..registry import Verb, register_verb


@register_verb("prefer_slot_range", supports=["assignment"], kind="soft", description="Ưu tiên slot trong dải period")
class PreferSlotRange(Verb):
	def build_soft(self, ctx, subject_set, params, weight: int):
		inp = ctx.inp
		preferred = set(params.get("periods", [0, 1, 2, 3]))
		terms = []
		for c in inp.classes:
			g = c.education_grade_id
			for ts_id in inp.grade_subjects.get(g, []):
				if subject_set and ts_id not in subject_set and not inp.subject_is_heavy.get(ts_id):
					continue
				if not inp.subject_is_heavy.get(ts_id) and subject_set:
					continue
				for day in inp.working_days:
					for p_idx in range(ctx.num_periods):
						v = ctx.x.get((c.name, ts_id, day, p_idx))
						if v is None:
							continue
						if p_idx in preferred:
							terms.append(v * weight)
						else:
							terms.append(v * (-weight * p_idx // 2 or 1))
		return terms
