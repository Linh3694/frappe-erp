from ..helpers import class_subject_weekdays, instances, teacher_class_subjects
from ..registry import Verb, register_verb


def _assignment_forbidden_slots(ctx, inst) -> None:
	"""Cấm lớp+môn tại slot — instance giống pin (subject=class_id, object.subject_id + day/period hoặc slots[])."""
	c_id = inst.get("subject") or inst.get("class_id")
	obj = inst.get("object") or {}
	ts_id = obj.get("subject_id") or obj.get("timetable_subject_id")
	if not c_id or not ts_id:
		return

	slot_list = list(obj.get("slots") or [])
	if not slot_list and obj.get("day") is not None and obj.get("period_idx") is not None:
		slot_list = [{"day": obj.get("day"), "period_idx": obj.get("period_idx")}]

	for sl in slot_list:
		day = sl.get("day")
		p_idx = sl.get("period_idx", sl.get("period"))
		if day is None or p_idx is None:
			continue
		p_idx = int(p_idx)
		v = ctx.x.get((c_id, ts_id, day, p_idx))
		if v is not None:
			ctx.model.Add(v == 0)


@register_verb("forbidden_at_slots", supports=["teacher", "subject", "assignment"], kind="hard", description="Cấm xếp tại slot")
class ForbiddenAtSlots(Verb):
	def apply_hard(self, ctx, subject_set, params):
		inp = ctx.inp
		tcs = teacher_class_subjects(inp)
		subject_type = getattr(ctx, "cur_subject_type", None)

		# Rule assignment_not_at_slot — chỉ xử lý instance lớp+môn
		if subject_type == "assignment" and params.get("source") == "instances":
			for inst in instances(params):
				_assignment_forbidden_slots(ctx, inst)
			return

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

		# Instance: subject=teacher|timetable_subject, object.slots [{day, period_idx}]
		for inst in instances(params):
			entity_id = inst.get("subject")
			obj = inst.get("object") or {}
			slots = obj.get("slots") or []
			if entity_id is None:
				continue
			for sl in slots:
				day = sl.get("day")
				p_idx = sl.get("period_idx", sl.get("period"))
				if day is None or p_idx is None:
					continue
				p_idx = int(p_idx)
				# GV: cấm mọi lớp×môn GV dạy tại slot
				if entity_id in tcs:
					for (c_id, ts_id) in tcs.get(entity_id, []):
						v = ctx.x.get((c_id, ts_id, day, p_idx))
						if v is not None:
							ctx.model.Add(v == 0)
					continue
				# Môn: cấm môn tại slot cho mọi lớp có môn đó
				for c in inp.classes:
					if entity_id not in inp.class_subjects.get(c.name, []):
						continue
					v = ctx.x.get((c.name, entity_id, day, p_idx))
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
