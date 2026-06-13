from ..helpers import instances
from ..registry import Verb, register_verb


def _slot_key(day: str, period_idx: int) -> tuple[str, int]:
	return (str(day), int(period_idx))


def _preferred_slots_from_object(obj: dict, working_days: list[str]) -> set[tuple[str, int]]:
	"""Đọc slot ưu tiên từ object; fallback periods cũ -> tất cả ngày làm việc."""
	out: set[tuple[str, int]] = set()
	raw_slots = obj.get("slots") or []
	if isinstance(raw_slots, list) and raw_slots:
		for s in raw_slots:
			if not isinstance(s, dict):
				continue
			day = s.get("day")
			p_idx = s.get("period_idx", s.get("period"))
			if day is None or p_idx is None:
				continue
			out.add(_slot_key(day, p_idx))
		if out:
			return out

	legacy_periods = obj.get("periods") or []
	if isinstance(legacy_periods, list) and legacy_periods:
		for day in working_days:
			for p_idx in legacy_periods:
				out.add(_slot_key(day, p_idx))
	return out


def _target_class_ids(inp, obj: dict) -> set[str]:
	"""Lọc lớp áp dụng theo class_ids/grade_ids; rỗng = áp dụng mọi lớp có môn."""
	class_ids = obj.get("class_ids") or []
	if not isinstance(class_ids, list):
		class_ids = []
	class_ids = {str(c).strip() for c in class_ids if c}

	grade_ids = obj.get("grade_ids") or []
	if not isinstance(grade_ids, list):
		grade_ids = []
	grade_ids = {str(g).strip() for g in grade_ids if g}

	if grade_ids:
		for c in inp.classes:
			grade_id = getattr(c, "education_grade_id", None)
			if grade_id in grade_ids:
				class_ids.add(c.name if hasattr(c, "name") else c)
	return class_ids


@register_verb("prefer_slot_range", supports=["assignment", "subject"], kind="soft", description="Ưu tiên slot trong dải period")
class PreferSlotRange(Verb):
	def build_soft(self, ctx, subject_set, params, weight: int):
		inp = ctx.inp
		# Tier per-môn (từ SIS Timetable Subject qua requirement).
		pref_tier = {r.timetable_subject_id: getattr(r, "tier_preferred", "weak") for r in inp.requirements}
		inst_list = instances(params)
		if inst_list or params.get("source") == "instances":
			for inst in inst_list:
				ts_id = inst.get("subject")
				obj = inst.get("object") or {}
				preferred_slots = _preferred_slots_from_object(obj, inp.working_days)
				if not ts_id or not preferred_slots:
					continue
				tier = pref_tier.get(ts_id, "weak")
				target_classes = _target_class_ids(inp, obj)
				for c in inp.classes:
					class_id = c.name if hasattr(c, "name") else c
					if target_classes and class_id not in target_classes:
						continue
					if ts_id not in inp.class_subjects.get(class_id, []):
						continue
					for day in inp.working_days:
						for p_idx in range(ctx.num_periods):
							v = ctx.x.get((class_id, ts_id, day, p_idx))
							if v is None:
								continue
							if (day, p_idx) in preferred_slots:
								ctx.add_soft(tier, v * weight)
							else:
								ctx.add_soft(tier, v * (-weight * max(p_idx // 2, 1)))
			return []  # self-bucket theo tier per-môn

		# Legacy global periods (deprecated)
		preferred = set(params.get("periods") or [0, 1, 2, 3])
		for c in inp.classes:
			for ts_id in inp.class_subjects.get(c.name, []):
				if subject_set and ts_id not in subject_set:
					continue
				tier = pref_tier.get(ts_id, "weak")
				for day in inp.working_days:
					for p_idx in range(ctx.num_periods):
						v = ctx.x.get((c.name, ts_id, day, p_idx))
						if v is None:
							continue
						if p_idx in preferred:
							ctx.add_soft(tier, v * weight)
						else:
							ctx.add_soft(tier, v * (-weight * max(p_idx // 2, 1)))
		return []  # self-bucket theo tier per-môn
