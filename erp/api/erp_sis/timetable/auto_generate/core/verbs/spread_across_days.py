from ..helpers import req_map
from ..registry import Verb, register_verb
from ..spread_eligibility import cannot_spread_across_days


@register_verb("spread_across_days", supports=["assignment"], kind="soft", description="Rải tiết môn ra nhiều ngày")
class SpreadAcrossDays(Verb):
	def build_soft(self, ctx, subject_set, params, weight: int):
		inp = ctx.inp
		rmap = req_map(inp)
		for c in inp.classes:
			for ts_id in inp.class_subjects.get(c.name, []):
				req = rmap.get((c.name, ts_id))
				if req and cannot_spread_across_days(req.periods_per_week, req.force_pair):
					continue
				tier = getattr(req, "tier_spread", "weak") if req else "weak"
				day_vars = []
				for day in inp.working_days:
					dv = [ctx.x[k] for p in range(ctx.num_periods) if (k := (c.name, ts_id, day, p)) in ctx.x]
					if dv:
						has = ctx.model.NewBoolVar(f"spread_{c.name}_{ts_id}_{day}")
						ctx.model.AddMaxEquality(has, dv)
						day_vars.append(has)
				# Penalty khi dồn: ưu tiên has=1 trên nhiều ngày — maximize sum(has)
				for h in day_vars:
					ctx.add_soft(tier, h * weight)
		return []  # self-bucket theo tier per-môn
