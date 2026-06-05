from ..helpers import instances, inst_object_int
from ..registry import Verb, register_verb


@register_verb("at_most_simultaneous", supports=["subject"], kind="hard", description="Tối đa N lớp học môn X cùng slot")
class AtMostSimultaneous(Verb):
	def apply_hard(self, ctx, subject_set, params):
		inp = ctx.inp
		for inst in instances(params):
			ts_id = inst.get("subject")
			n = inst_object_int(inst, "max_classes", params.get("max_classes", 1))
			if not ts_id:
				continue
			for day in inp.working_days:
				for p_idx in range(ctx.num_periods):
					vars_ = []
					for c in inp.classes:
						if ts_id not in inp.grade_subjects.get(c.education_grade_id, []):
							continue
						v = ctx.x.get((c.name, ts_id, day, p_idx))
						if v is not None:
							vars_.append(v)
					if vars_:
						ctx.model.Add(sum(vars_) <= n)
