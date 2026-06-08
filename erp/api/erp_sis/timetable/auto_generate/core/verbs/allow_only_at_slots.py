from ..helpers import instances
from ..registry import Verb, register_verb


@register_verb("allow_only_at_slots", supports=["subject"], kind="hard", description="Môn chỉ được xếp vào slots được chọn")
class AllowOnlyAtSlots(Verb):
	def apply_hard(self, ctx, subject_set, params):
		inp = ctx.inp
		for inst in instances(params):
			subject = inst.get("subject")
			obj = inst.get("object") or {}
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
						if v is not None:
							ctx.model.Add(v == 0)

		# Blocking pins
		for pin in getattr(inp, "pinned_slots", []) or []:
			if not pin.is_blocking:
				continue
			p_idx = inp.column_period_index.get(pin.timetable_column_id)
			if p_idx is None:
				continue
			for c in inp.classes:
				if pin.class_id and c.name != pin.class_id:
					continue
				for ts_id in inp.class_subjects.get(c.name, []):
					v = ctx.x.get((c.name, ts_id, pin.day_of_week, p_idx))
					if v is not None:
						ctx.model.Add(v == 0)
