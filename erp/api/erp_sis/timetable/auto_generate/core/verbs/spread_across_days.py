from ..registry import Verb, register_verb


@register_verb("spread_across_days", supports=["assignment"], kind="soft", description="Rải tiết môn ra nhiều ngày")
class SpreadAcrossDays(Verb):
	def build_soft(self, ctx, subject_set, params, weight: int):
		inp = ctx.inp
		terms = []
		for c in inp.classes:
			for ts_id in inp.class_subjects.get(c.name, []):
				day_vars = []
				for day in inp.working_days:
					dv = [ctx.x[k] for p in range(ctx.num_periods) if (k := (c.name, ts_id, day, p)) in ctx.x]
					if dv:
						has = ctx.model.NewBoolVar(f"spread_{c.name}_{ts_id}_{day}")
						ctx.model.AddMaxEquality(has, dv)
						day_vars.append(has)
				# Penalty khi dồn: ưu tiên has=1 trên nhiều ngày — maximize sum(has)
				for h in day_vars:
					terms.append(h * weight)
		return terms
