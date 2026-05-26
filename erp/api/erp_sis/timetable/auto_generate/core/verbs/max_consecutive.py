from ..helpers import instances, teacher_class_subjects
from ..registry import Verb, register_verb


@register_verb("max_consecutive", supports=["teacher"], kind="both", description="Giới hạn tiết liên tiếp GV")
class MaxConsecutive(Verb):
	def apply_hard(self, ctx, subject_set, params):
		if params.get("global"):
			return
		inp = ctx.inp
		tcs = teacher_class_subjects(inp)

		if params.get("use_teacher_field"):
			for t_id in tcs:
				info = inp.teachers.get(t_id)
				if info:
					self._apply_limit(ctx, t_id, info.max_consecutive_periods, tcs)
			return

		for inst in instances(params):
			t_id = inst.get("subject")
			n = int((inst.get("object") or {}).get("value", params.get("max", 3)))
			self._apply_limit(ctx, t_id, n, tcs)

		for t_id in subject_set or []:
			tid = t_id.name if hasattr(t_id, "name") else t_id
			info = inp.teachers.get(tid)
			if info and not instances(params):
				self._apply_limit(ctx, tid, info.max_consecutive_periods, tcs)

	def _apply_limit(self, ctx, t_id, max_consec, tcs):
		if max_consec >= ctx.num_periods:
			return
		for day in ctx.working_days:
			for start in range(ctx.num_periods - max_consec):
				window = []
				for p in range(start, start + max_consec + 1):
					for (c_id, ts_id) in tcs.get(t_id, []):
						v = ctx.x.get((c_id, ts_id, day, p))
						if v is not None:
							window.append(v)
				if window:
					ctx.model.Add(sum(window) <= max_consec)

	def build_soft(self, ctx, subject_set, params, weight: int):
		return []
