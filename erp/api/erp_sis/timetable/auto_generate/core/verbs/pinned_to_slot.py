from ..helpers import instances
from ..registry import Verb, register_verb


@register_verb("pinned_to_slot", supports=["assignment"], kind="hard", description="Pin (lớp, môn) vào slot cố định")
class PinnedToSlot(Verb):
	def apply_hard(self, ctx, subject_set, params):
		inp = ctx.inp

		# Session pinned slots (P0 data)
		for pin in getattr(inp, "pinned_slots", []) or []:
			if pin.is_blocking:
				continue
			p_idx = inp.column_period_index.get(pin.timetable_column_id)
			if p_idx is None or not pin.timetable_subject_id:
				continue
			classes = [c for c in inp.classes if not pin.class_id or c.name == pin.class_id]
			for c in classes:
				pk = (c.name, pin.timetable_subject_id, pin.day_of_week, p_idx)
				if pk in ctx.x:
					ctx.model.Add(ctx.x[pk] == 1)
				for ts_id in inp.class_subjects.get(c.name, []):
					if ts_id == pin.timetable_subject_id:
						continue
					k = (c.name, ts_id, pin.day_of_week, p_idx)
					if k in ctx.x:
						ctx.model.Add(ctx.x[k] == 0)

		for inst in instances(params):
			c_id = inst.get("subject") or inst.get("class_id")
			obj = inst.get("object") or {}
			ts_id = obj.get("subject_id") or obj.get("timetable_subject_id")
			day = obj.get("day")
			p_idx = obj.get("period_idx", obj.get("period"))
			if not all([c_id, ts_id, day]) or p_idx is None:
				continue
			p_idx = int(p_idx)
			pk = (c_id, ts_id, day, p_idx)
			if pk in ctx.x:
				ctx.model.Add(ctx.x[pk] == 1)
			for other in inp.class_subjects.get(c_id, []):
				if other == ts_id:
					continue
				k = (c_id, other, day, p_idx)
				if k in ctx.x:
					ctx.model.Add(ctx.x[k] == 0)
