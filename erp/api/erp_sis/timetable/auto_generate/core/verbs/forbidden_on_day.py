from ..helpers import forbid_var, instances, teacher_class_subjects
from ..registry import Verb, register_verb


@register_verb("forbidden_on_day", supports=["teacher"], kind="hard", description="GV không dạy cả ngày")
class ForbiddenOnDay(Verb):
	def apply_hard(self, ctx, subject_set, params):
		inp = ctx.inp
		tcs = teacher_class_subjects(inp)
		for inst in instances(params):
			teacher = inst.get("subject")
			obj = inst.get("object") or {}
			enforcement = obj.get("enforcement")
			weight = int(obj.get("weight", 5) or 5)
			days = obj.get("days") or ([obj["day"]] if obj.get("day") else [])
			for day in days:
				for (c_id, ts_id) in tcs.get(teacher, []):
					for p_idx in range(ctx.num_periods):
						v = ctx.x.get((c_id, ts_id, day, p_idx))
						forbid_var(
							ctx, v, enforcement=enforcement, weight=weight,
							rule_id=ctx.cur_rule_id,
							scope={"teacher_id": teacher, "day": day, "period_idx": p_idx,
							       "class_id": c_id, "subject_id": ts_id},
						)
