from ..registry import Verb, register_verb


@register_verb("order_before_same_day", supports=["subject"], kind="hard", description="Môn A trước môn B trong cùng ngày")
class OrderBeforeSameDay(Verb):
	def apply_hard(self, ctx, subject_set, params):
		inp = ctx.inp
		from ..helpers import instances
		for inst in instances(params):
			before = inst.get("subject")
			after = (inst.get("object") or {}).get("subject_id")
			if not before or not after:
				continue
			for c in inp.classes:
				if before not in inp.class_subjects.get(c.name, []) or after not in inp.class_subjects.get(c.name, []):
					continue
				for day in inp.working_days:
					for p_b in range(ctx.num_periods):
						for p_a in range(ctx.num_periods):
							if p_b < p_a:
								continue
							va = ctx.x.get((c.name, before, day, p_b))
							vb = ctx.x.get((c.name, after, day, p_a))
							if va is not None and vb is not None:
								ctx.model.Add(va + vb <= 1)
