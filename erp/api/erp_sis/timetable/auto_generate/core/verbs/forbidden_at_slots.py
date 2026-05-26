from ..helpers import class_subject_weekdays, instances, teacher_class_subjects
from ..registry import Verb, register_verb


@register_verb("forbidden_at_slots", supports=["teacher"], kind="hard", description="GV không dạy tại slot")
class ForbiddenAtSlots(Verb):
	def apply_hard(self, ctx, subject_set, params):
		inp = ctx.inp
		tcs = teacher_class_subjects(inp)

		# Đọc unavailability từ TeacherDTO
		if params.get("source") == "teacher.unavailability":
			for t_id, cs_list in tcs.items():
				info = inp.teachers.get(t_id)
				if not info or not info.unavailable_slots:
					continue
				for day, p_idx in info.unavailable_slots:
					for (c_id, ts_id) in cs_list:
						v = ctx.x.get((c_id, ts_id, day, p_idx))
						if v is not None:
							ctx.model.Add(v == 0)

		# Instance: subject=teacher, object.slots [{day, period_idx}]
		for inst in instances(params):
			teacher = inst.get("subject")
			obj = inst.get("object") or {}
			slots = obj.get("slots") or []
			for sl in slots:
				day = sl.get("day")
				p_idx = sl.get("period_idx", sl.get("period"))
				if teacher is None or day is None or p_idx is None:
					continue
				for (c_id, ts_id) in tcs.get(teacher, []):
					v = ctx.x.get((c_id, ts_id, day, int(p_idx)))
					if v is not None:
						ctx.model.Add(v == 0)

		# Weekday availability từ assignment
		csw = class_subject_weekdays(inp)
		for (c_id, ts_id), allowed in csw.items():
			for day in inp.working_days:
				if day not in allowed:
					for p_idx in range(ctx.num_periods):
						v = ctx.x.get((c_id, ts_id, day, p_idx))
						if v is not None:
							ctx.model.Add(v == 0)
