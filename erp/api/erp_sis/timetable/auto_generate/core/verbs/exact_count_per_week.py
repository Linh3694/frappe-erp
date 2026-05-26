from ..helpers import req_map
from ..registry import Verb, register_verb


@register_verb("exact_count_per_week", supports=["assignment"], kind="hard", description="Tổng tiết/tuần = periods_per_week")
class ExactCountPerWeek(Verb):
	def apply_hard(self, ctx, subject_set, params):
		inp = ctx.inp
		rmap = req_map(inp)
		for c in inp.classes:
			grade = c.education_grade_id
			for ts_id in inp.grade_subjects.get(grade, []):
				req = rmap.get((grade, ts_id))
				if not req or req.periods_per_week == 0:
					continue
				if subject_set and (c.name, ts_id) not in subject_set:
					continue
				week_vars = []
				for day in inp.working_days:
					for p_idx in range(ctx.num_periods):
						v = ctx.x.get((c.name, ts_id, day, p_idx))
						if v is not None:
							week_vars.append(v)
				if week_vars:
					ctx.model.Add(sum(week_vars) == req.periods_per_week)
