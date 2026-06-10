from ..registry import Verb, register_verb


@register_verb("no_overlap", supports=["class", "teacher"], kind="both", description="Tối đa 1 assignment/slot theo entity")
class NoOverlap(Verb):
	def apply_hard(self, ctx, subject_set, params):
		if ctx.cur_subject_type == "class":
			for c in subject_set:
				for day in ctx.working_days:
					for p_idx in range(ctx.num_periods):
						vars_ = ctx.vars_for_class_slot(c.name if hasattr(c, "name") else c, day, p_idx)
						if len(vars_) > 1:
							ctx.model.Add(sum(vars_) <= 1)
		elif ctx.cur_subject_type == "teacher":
			for t_id in subject_set:
				tid = t_id.name if hasattr(t_id, "name") else t_id
				for day in ctx.working_days:
					for p_idx in range(ctx.num_periods):
						vars_ = ctx.vars_for_teacher_slot(tid, day, p_idx)
						if len(vars_) > 1:
							ctx.model.Add(sum(vars_) <= 1)

	def build_soft(self, ctx, subject_set, params, weight: int):
		return []
