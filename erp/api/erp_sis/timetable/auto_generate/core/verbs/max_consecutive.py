from ...requirements_matrix import LEGACY_DEFAULT_MAX_CONSECUTIVE
from ..helpers import instances, inst_object_int, le_limit, teacher_class_subjects
from ..registry import Verb, register_verb


@register_verb("max_consecutive", supports=["teacher"], kind="both", description="Giới hạn tiết liên tiếp GV")
class MaxConsecutive(Verb):
	def apply_hard(self, ctx, subject_set, params):
		self._apply(ctx, subject_set, params, kind="hard", weight=0)

	def build_soft(self, ctx, subject_set, params, weight: int):
		self._apply(ctx, subject_set, params, kind="soft", weight=weight)
		return []

	def _apply(self, ctx, subject_set, params, *, kind: str, weight: int) -> None:
		if params.get("global") and kind == "hard":
			return
		inp = ctx.inp
		tcs = teacher_class_subjects(inp)

		if params.get("use_teacher_field"):
			for t_id in tcs:
				info = inp.teachers.get(t_id)
				if info:
					self._apply_limit(ctx, t_id, info.max_consecutive_periods, tcs, kind=kind, weight=weight)
			return

		for inst in instances(params):
			t_id = inst.get("subject")
			n = inst_object_int(inst, "max", params.get("max", LEGACY_DEFAULT_MAX_CONSECUTIVE))
			self._apply_limit(ctx, t_id, n, tcs, kind=kind, weight=weight)

		for t_id in subject_set or []:
			tid = t_id.name if hasattr(t_id, "name") else t_id
			info = inp.teachers.get(tid)
			if info and not instances(params):
				self._apply_limit(ctx, tid, info.max_consecutive_periods, tcs, kind=kind, weight=weight)

	def _apply_limit(self, ctx, t_id, max_consec, tcs, *, kind: str, weight: int) -> None:
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
				le_limit(ctx, window, max_consec, kind=kind, weight=weight, tag=f"mc_{t_id}_{day}_{start}")
