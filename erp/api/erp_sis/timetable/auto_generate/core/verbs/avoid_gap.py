from ..helpers import teacher_class_subjects
from ..registry import Verb, register_verb


@register_verb("avoid_gap", supports=["teacher"], kind="soft", description="Giảm tiết trống xen giữa buổi GV")
class AvoidGap(Verb):
	def build_soft(self, ctx, subject_set, params, weight: int):
		inp = ctx.inp
		tcs = teacher_class_subjects(inp)
		for t_id, cs_list in tcs.items():
			if subject_set and t_id not in subject_set and not any(
				(hasattr(s, "name") and s.name == t_id) or s == t_id for s in subject_set
			):
				continue
			info = inp.teachers.get(t_id)
			tier = getattr(info, "tier_avoid_gap", "weak") if info else "weak"
			for day in inp.working_days:
				teaching_at = []
				for p_idx in range(ctx.num_periods):
					tvars = [ctx.x[k] for (c_id, ts_id) in cs_list if (k := (c_id, ts_id, day, p_idx)) in ctx.x]
					if tvars:
						is_t = ctx.model.NewBoolVar(f"avgap_{t_id}_{day}_{p_idx}")
						ctx.model.AddMaxEquality(is_t, tvars)
						teaching_at.append(is_t)
				for i in range(len(teaching_at)):
					for j in range(i + 2, len(teaching_at)):
						for k in range(i + 1, j):
							gap = ctx.model.NewBoolVar(f"gap_{t_id}_{day}_{i}_{k}_{j}")
							ctx.model.AddBoolAnd([teaching_at[i], teaching_at[j], teaching_at[k].Not()]).OnlyEnforceIf(gap)
							ctx.model.AddBoolOr([teaching_at[i].Not(), teaching_at[j].Not(), teaching_at[k]]).OnlyEnforceIf(gap.Not())
							ctx.add_soft(tier, gap * (-weight))
		return []  # self-bucket theo tier per-GV
