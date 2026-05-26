from ..helpers import req_map, teacher_class_subjects
from ..registry import Verb, register_verb


@register_verb("at_most_per_scope", supports=["assignment", "teacher", "subject"], kind="hard", description="Giới hạn tiết theo scope day/week")
class AtMostPerScope(Verb):
	def apply_hard(self, ctx, subject_set, params):
		scope = params.get("scope", "day")
		source = params.get("source", "")
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
						day_vars = []
						for p_idx in range(ctx.num_periods):
							v = ctx.x.get((c.name, ts_id, day, p_idx))
							if v is not None:
								day_vars.append(v)
						if day_vars:
							ctx.model.Add(sum(day_vars) <= max_d)

		elif ctx.cur_subject_type == "subject" and scope == "day":
			for ts_id in subject_set:
				max_d = int(params.get("max", 2))
				for c in inp.classes:
					grade = c.education_grade_id
					if ts_id not in inp.grade_subjects.get(grade, []):
						continue
					for day in inp.working_days:
						day_vars = [ctx.x[k] for p in range(ctx.num_periods) if (k := (c.name, ts_id, day, p)) in ctx.x]
						if day_vars:
							ctx.model.Add(sum(day_vars) <= max_d)

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
				vars_ = []
				for (c_id, ts_id) in tcs.get(tid, []):
					days = inp.working_days if scope == "week" else inp.working_days
					for day in days:
						for p_idx in range(ctx.num_periods):
							v = ctx.x.get((c_id, ts_id, day, p_idx))
							if v is not None:
								vars_.append(v)
				if vars_:
					ctx.model.Add(sum(vars_) <= limit)
