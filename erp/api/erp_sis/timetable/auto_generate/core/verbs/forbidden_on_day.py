from ..helpers import instances, teacher_class_subjects
from ..registry import Verb, register_verb


@register_verb("forbidden_on_day", supports=["teacher"], kind="hard", description="GV không dạy cả ngày")
class ForbiddenOnDay(Verb):
	def apply_hard(self, ctx, subject_set, params):
		inp = ctx.inp
		tcs = teacher_class_subjects(inp)
		for inst in instances(params):
			teacher = inst.get("subject")
			obj = inst.get("object") or {}
			days = obj.get("days") or ([obj["day"]] if obj.get("day") else [])
			for day in days:
				for (c_id, ts_id) in tcs.get(teacher, []):
					for p_idx in range(ctx.num_periods):
						v = ctx.x.get((c_id, ts_id, day, p_idx))
						if v is not None:
							ctx.model.Add(v == 0)
