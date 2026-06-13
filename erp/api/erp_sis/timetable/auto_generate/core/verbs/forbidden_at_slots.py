from ..helpers import class_subject_weekdays, instances, resolve_target_class_ids, teacher_class_subjects
from ..registry import Verb, register_verb
from ..tiers import STRONG, normalize_enforcement


def _norm_unavail(slot):
	"""Chuẩn hoá 1 entry unavailable_slots về (day, period_idx, enforcement, weight).

	Khoan dung dữ liệu cũ dạng 2-tuple (day, period_idx).
	"""
	if isinstance(slot, (list, tuple)):
		day = slot[0]
		p_idx = slot[1]
		enforcement = normalize_enforcement(slot[2]) if len(slot) > 2 else "mandatory"
		weight = int(slot[3]) if len(slot) > 3 else 5
		return day, p_idx, enforcement, weight
	# object/namedtuple
	return (
		getattr(slot, "day", None),
		getattr(slot, "period_idx", None),
		normalize_enforcement(getattr(slot, "enforcement", None)),
		int(getattr(slot, "weight", 5) or 5),
	)


@register_verb("forbidden_at_slots", supports=["teacher", "subject"], kind="hard", description="Cấm xếp tại slot")
class ForbiddenAtSlots(Verb):
	def apply_hard(self, ctx, subject_set, params):
		inp = ctx.inp
		tcs = teacher_class_subjects(inp)

		# Đọc unavailability từ TeacherDTO (per-slot enforcement: mandatory cứng / relaxable nới)
		if params.get("source") == "teacher.unavailability":
			for t_id, cs_list in tcs.items():
				info = inp.teachers.get(t_id)
				if not info or not info.unavailable_slots:
					continue
				for slot in info.unavailable_slots:
					day, p_idx, enforcement, weight = _norm_unavail(slot)
					for (c_id, ts_id) in cs_list:
						v = ctx.x.get((c_id, ts_id, day, p_idx))
						if v is None:
							continue
						if enforcement == "relaxable":
							# GV "hạn chế": phạt nếu vẫn phải xếp (tầng strong), ghi báo cáo.
							ctx.add_soft(STRONG, v * (-weight))
							ctx.add_violation(
								ctx.cur_rule_id, "forbidden",
								{"teacher_id": t_id, "day": day, "period_idx": p_idx,
								 "class_id": c_id, "subject_id": ts_id},
								v,
							)
						else:
							ctx.add_hard(ctx.model.Add(v == 0))

		# Instance: subject=teacher|timetable_subject, object.slots [{day, period_idx}]
		for inst in instances(params):
			obj = inst.get("object") or {}
			entity_ids = []
			for sid in obj.get("subject_ids") or []:
				if sid:
					entity_ids.append(str(sid).strip())
			legacy_subject = inst.get("subject")
			if legacy_subject:
				entity_ids.append(str(legacy_subject).strip())
			entity_ids = [sid for i, sid in enumerate(entity_ids) if sid and sid not in entity_ids[:i]]
			slots = obj.get("slots") or []
			if not entity_ids:
				continue
			for sl in slots:
				day = sl.get("day")
				p_idx = sl.get("period_idx", sl.get("period"))
				if day is None or p_idx is None:
					continue
				p_idx = int(p_idx)
				enforcement = normalize_enforcement(sl.get("enforcement"))
				weight = int(sl.get("weight", 5) or 5)
				for entity_id in entity_ids:
					# GV: cấm mọi lớp×môn GV dạy tại slot
					if entity_id in tcs:
						for (c_id, ts_id) in tcs.get(entity_id, []):
							v = ctx.x.get((c_id, ts_id, day, p_idx))
							if v is not None:
								if enforcement == "relaxable":
									ctx.add_soft(STRONG, v * (-weight))
									ctx.add_violation(
										ctx.cur_rule_id, "forbidden",
										{"teacher_id": entity_id, "day": day, "period_idx": p_idx,
										 "class_id": c_id, "subject_id": ts_id, "enforcement": "relaxable"},
										v,
									)
								else:
									ctx.add_hard(ctx.model.Add(v == 0))
						continue
					# Môn: cấm môn tại slot theo phạm vi class_ids/grade_ids (rỗng = mọi lớp có môn).
					target_classes = resolve_target_class_ids(inp, obj)
					for c in inp.classes:
						class_id = c.name if hasattr(c, "name") else c
						if target_classes and class_id not in target_classes:
							continue
						if entity_id not in inp.class_subjects.get(class_id, []):
							continue
						v = ctx.x.get((class_id, entity_id, day, p_idx))
						if v is not None:
							if enforcement == "relaxable":
								ctx.add_soft(STRONG, v * (-weight))
								ctx.add_violation(
									ctx.cur_rule_id, "forbidden",
									{"subject_id": entity_id, "day": day, "period_idx": p_idx,
									 "class_id": class_id, "enforcement": "relaxable"},
									v,
								)
							else:
								ctx.add_hard(ctx.model.Add(v == 0))

		# Weekday availability từ assignment
		csw = class_subject_weekdays(inp)
		for (c_id, ts_id), allowed in csw.items():
			for day in inp.working_days:
				if day not in allowed:
					for p_idx in range(ctx.num_periods):
						v = ctx.x.get((c_id, ts_id, day, p_idx))
						if v is not None:
							ctx.add_hard(ctx.model.Add(v == 0))
