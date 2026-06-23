from ..helpers import instances, pin_var
from ..registry import Verb, register_verb


def _force_others_off(ctx, c_id, ts_id, day, p_idx):
	"""Ép các môn khác của lớp rời slot (chỉ khi pin cứng).

	Đi qua ctx.add_hard để pin mang assumption literal → UNSAT core khoanh được pin
	khi pin mâu thuẫn với ràng buộc cứng khác (no_overlap, teacher bận, nhóm lớp...).
	"""
	for other in ctx.inp.class_subjects.get(c_id, []):
		if other == ts_id:
			continue
		k = (c_id, other, day, p_idx)
		if k in ctx.x:
			ctx.add_hard(ctx.model.Add(ctx.x[k] == 0))


@register_verb("pinned_to_slot", supports=["assignment"], kind="hard", description="Pin (lớp, môn) vào slot cố định")
class PinnedToSlot(Verb):
	def apply_hard(self, ctx, subject_set, params):
		inp = ctx.inp

		# Session pinned slots (P0 data) — per-pin enforcement (mandatory cứng / relaxable pin mềm)
		for pin in getattr(inp, "pinned_slots", []) or []:
			if pin.is_blocking:
				continue
			p_idx = inp.column_period_index.get(pin.timetable_column_id)
			if p_idx is None or not pin.timetable_subject_id:
				continue
			pin_enf = getattr(pin, "enforcement", "mandatory")
			pin_w = int(getattr(pin, "weight", 5) or 5)
			classes = [c for c in inp.classes if not pin.class_id or c.name == pin.class_id]
			for c in classes:
				ts_id = pin.timetable_subject_id
				pk = (c.name, ts_id, pin.day_of_week, p_idx)
				hard = pin_var(
					ctx, ctx.x.get(pk), enforcement=pin_enf, weight=pin_w, rule_id="pin_session",
					scope={"class_id": c.name, "subject_id": ts_id,
					       "day": pin.day_of_week, "period_idx": p_idx},
					tag=f"sess_{c.name}_{ts_id}_{pin.day_of_week}_{p_idx}",
				)
				if hard:
					_force_others_off(ctx, c.name, ts_id, pin.day_of_week, p_idx)

		for inst in instances(params):
			c_id = inst.get("subject") or inst.get("class_id")
			obj = inst.get("object") or {}
			ts_id = obj.get("subject_id") or obj.get("timetable_subject_id")
			day = obj.get("day")
			p_idx = obj.get("period_idx", obj.get("period"))
			if not all([c_id, ts_id, day]) or p_idx is None:
				continue
			p_idx = int(p_idx)
			hard = pin_var(
				ctx, ctx.x.get((c_id, ts_id, day, p_idx)),
				enforcement=obj.get("enforcement"), weight=int(obj.get("weight", 5) or 5),
				rule_id=ctx.cur_rule_id,
				scope={"class_id": c_id, "subject_id": ts_id, "day": day, "period_idx": p_idx},
				tag=f"inst_{c_id}_{ts_id}_{day}_{p_idx}",
			)
			if hard:
				_force_others_off(ctx, c_id, ts_id, day, p_idx)
