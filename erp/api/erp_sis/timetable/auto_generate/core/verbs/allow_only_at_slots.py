from ..helpers import forbid_var, instances
from ..registry import Verb, register_verb


@register_verb("allow_only_at_slots", supports=["subject"], kind="hard", description="Môn chỉ được xếp vào slots được chọn")
class AllowOnlyAtSlots(Verb):
	def apply_hard(self, ctx, subject_set, params):
		inp = ctx.inp
		for inst in instances(params):
			subject = inst.get("subject")
			obj = inst.get("object") or {}
			enforcement = obj.get("enforcement")
			weight = int(obj.get("weight", 5) or 5)
			slot_dicts = obj.get("slots") or []
			selected = set()
			for sd in slot_dicts:
				day = sd.get("day")
				p_idx = sd.get("period_idx", sd.get("period"))
				if day is not None and p_idx is not None:
					selected.add((day, int(p_idx)))
			if not subject:
				continue
			for c in inp.classes:
				if subject not in inp.class_subjects.get(c.name, []):
					continue
				for day in inp.working_days:
					for p_idx in range(ctx.num_periods):
						if (day, p_idx) in selected:
							continue
						v = ctx.x.get((c.name, subject, day, p_idx))
						forbid_var(
							ctx, v, enforcement=enforcement, weight=weight,
							rule_id=ctx.cur_rule_id,
							scope={"class_id": c.name, "subject_id": subject,
							       "day": day, "period_idx": p_idx},
						)

		# Blocking pins (session) — per-pin enforcement
		for pin in getattr(inp, "pinned_slots", []) or []:
			if not pin.is_blocking:
				continue
			p_idx = inp.column_period_index.get(pin.timetable_column_id)
			if p_idx is None:
				continue
			pin_enf = getattr(pin, "enforcement", "mandatory")
			pin_w = int(getattr(pin, "weight", 5) or 5)
			for c in inp.classes:
				if pin.class_id and c.name != pin.class_id:
					continue
				for ts_id in inp.class_subjects.get(c.name, []):
					v = ctx.x.get((c.name, ts_id, pin.day_of_week, p_idx))
					forbid_var(
						ctx, v, enforcement=pin_enf, weight=pin_w,
						rule_id="pin_blocking",
						scope={"class_id": c.name, "subject_id": ts_id,
						       "day": pin.day_of_week, "period_idx": p_idx},
					)
