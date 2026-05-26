from ..helpers import teacher_class_subjects
from ..registry import Verb, register_verb


@register_verb("avoid_single_visit", supports=["teacher"], kind="soft", description="Tránh GV chỉ 1 tiết/buổi")
class AvoidSingleVisit(Verb):
	def build_soft(self, ctx, subject_set, params, weight: int):
		inp = ctx.inp
		tcs = teacher_class_subjects(inp)
		penalties = []
		half = ctx.num_periods // 2 or ctx.num_periods
		for t_id, cs_list in tcs.items():
			for day in inp.working_days:
				for h0, h1 in [(0, half), (half, ctx.num_periods)]:
					session_vars = []
					for p_idx in range(h0, h1):
						tvars = [ctx.x[k] for (c_id, ts_id) in cs_list if (k := (c_id, ts_id, day, p_idx)) in ctx.x]
						if tvars:
							session_vars.extend(tvars)
					if len(session_vars) == 1:
						penalties.append(session_vars[0] * (-weight))
		return penalties
