from ..helpers import le_limit, req_map, teacher_class_subjects
from ..registry import Verb, register_verb


@register_verb("at_most_per_scope", supports=["assignment", "teacher", "subject"], kind="both", description="Giới hạn tiết theo scope day/week")
class AtMostPerScope(Verb):
	def apply_hard(self, ctx, subject_set, params):
		self._apply(ctx, subject_set, params, kind="hard", weight=0)

	def build_soft(self, ctx, subject_set, params, weight: int):
		self._apply(ctx, subject_set, params, kind="soft", weight=weight)
		return []

	def _apply(self, ctx, subject_set, params, *, kind: str, weight: int) -> None:
		scope = params.get("scope", "day")
		inp = ctx.inp
		rmap = req_map(inp)

		if ctx.cur_subject_type == "assignment" and scope == "day":
			for c in inp.classes:
				grade = c.education_grade_id
				for ts_id in inp.grade_subjects.get(grade, []):
					req = rmap.get((grade, ts_id))
					max_d = req.max_periods_per_day if req else 2
					if params.get("max") is not None:
						max_d = int(params["max"])
					for day in inp.working_days:
						day_vars = [
							ctx.x[(c.name, ts_id, day, p_idx)]
							for p_idx in range(ctx.num_periods)
							if (c.name, ts_id, day, p_idx) in ctx.x
						]
						le_limit(ctx, day_vars, max_d, kind=kind, weight=weight, tag=f"asg_{c.name}_{ts_id}_{day}")

		elif ctx.cur_subject_type == "subject" and scope == "day":
			for ts_id in subject_set:
				max_d = int(params.get("max", 2))
				for c in inp.classes:
					grade = c.education_grade_id
					if ts_id not in inp.grade_subjects.get(grade, []):
						continue
					for day in inp.working_days:
						day_vars = [
							ctx.x[k] for p in range(ctx.num_periods)
							if (k := (c.name, ts_id, day, p)) in ctx.x
						]
						le_limit(ctx, day_vars, max_d, kind=kind, weight=weight, tag=f"sub_{ts_id}_{c.name}_{day}")

		elif ctx.cur_subject_type == "teacher":
			tcs = teacher_class_subjects(inp)
			for t_id in (subject_set or tcs.keys()):
				tid = t_id.name if hasattr(t_id, "name") else t_id
				info = inp.teachers.get(tid)
				if not info:
					continue
				limit = info.max_periods_per_day if scope == "day" else (info.max_periods_per_week or 24)
				if params.get("global_value") is not None:
					limit = int(params["global_value"])
				if scope == "day":
					for day in inp.working_days:
						day_vars = []
						for (c_id, ts_id) in tcs.get(tid, []):
							for p_idx in range(ctx.num_periods):
								v = ctx.x.get((c_id, ts_id, day, p_idx))
								if v is not None:
									day_vars.append(v)
						le_limit(ctx, day_vars, limit, kind=kind, weight=weight, tag=f"tch_{tid}_{day}")
				else:
					week_vars = []
					for (c_id, ts_id) in tcs.get(tid, []):
						for day in inp.working_days:
							for p_idx in range(ctx.num_periods):
								v = ctx.x.get((c_id, ts_id, day, p_idx))
								if v is not None:
									week_vars.append(v)
					le_limit(ctx, week_vars, limit, kind=kind, weight=weight, tag=f"tch_{tid}_week")
