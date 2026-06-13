from ..helpers import instances, resolve_target_class_ids
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


@register_verb("prefer_slot_range", supports=["assignment", "subject"], kind="soft", description="Ưu tiên slot trong dải period")
class PreferSlotRange(Verb):
	def build_soft(self, ctx, subject_set, params, weight: int):
		inp = ctx.inp
		inst_list = instances(params)
		if inst_list or params.get("source") == "instances":
			for inst in inst_list:
				obj = inst.get("object") or {}
				tier = obj.get("tier") if isinstance(obj, dict) else None
				tier = tier if tier in ("strong", "weak") else "weak"
				ts_ids = []
				for sid in obj.get("subject_ids") or []:
					if sid:
						ts_ids.append(str(sid).strip())
				legacy_subject = inst.get("subject")
				if legacy_subject:
					ts_ids.append(str(legacy_subject).strip())
				ts_ids = [sid for i, sid in enumerate(ts_ids) if sid and sid not in ts_ids[:i]]
				preferred_slots = _preferred_slots_from_object(obj, inp.working_days)
				if not ts_ids or not preferred_slots:
					continue
				target_classes = resolve_target_class_ids(inp, obj)
				for ts_id in ts_ids:
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
				tier = "weak"
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
