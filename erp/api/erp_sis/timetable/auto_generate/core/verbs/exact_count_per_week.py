from ..helpers import req_map
from ..registry import Verb, register_verb
from ..tiers import RELAX_SHORT_PENALTY, RELAXABLE, normalize_enforcement


@register_verb("exact_count_per_week", supports=["assignment"], kind="hard", description="Tổng tiết/tuần = periods_per_week")
class ExactCountPerWeek(Verb):
	def apply_hard(self, ctx, subject_set, params):
		inp = ctx.inp
		rmap = req_map(inp)
		for c in inp.classes:
			for ts_id in inp.class_subjects.get(c.name, []):
				req = rmap.get((c.name, ts_id))
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
				if not week_vars:
					continue

				n = req.periods_per_week
				# Per-cell enforcement: relaxable -> cho thiếu tiết (slack), tính vào coverage.
				# Chế độ diagnostic nới mọi ô để luôn ra lời giải + báo cáo % đáp ứng.
				enforcement = normalize_enforcement(getattr(req, "enforcement", None))
				if ctx.diagnostic or enforcement == "relaxable":
					short = ctx.model.NewIntVar(0, n, f"short_{c.name}_{ts_id}")
					# short >= 0 + (sum + short == n) => sum <= n: cho phép xếp ÍT hơn, không nhiều hơn.
					ctx.model.Add(sum(week_vars) + short == n)
					ctx.add_violation(
						ctx.cur_rule_id, "short",
						{"class_id": c.name, "subject_id": ts_id, "required": n},
						short,
					)
					w = int(getattr(req, "enforcement_weight", 1) or 1)
					ctx.add_soft(RELAXABLE, short * (-(RELAX_SHORT_PENALTY * w)))
				else:
					ctx.add_hard(ctx.model.Add(sum(week_vars) == n))
