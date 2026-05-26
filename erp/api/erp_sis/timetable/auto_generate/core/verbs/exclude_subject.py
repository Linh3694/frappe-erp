from ..helpers import instances
from ..registry import Verb, register_verb


@register_verb("exclude_subject", supports=["class"], kind="hard", description="Lớp không học môn X")
class ExcludeSubject(Verb):
	def apply_hard(self, ctx, subject_set, params):
		inp = ctx.inp
		for inst in instances(params):
			c_id = inst.get("subject") or inst.get("class_id")
			ts_id = (inst.get("object") or {}).get("subject_id")
			if not c_id or not ts_id:
				continue
			for day in inp.working_days:
				for p_idx in range(ctx.num_periods):
					v = ctx.x.get((c_id, ts_id, day, p_idx))
					if v is not None:
						ctx.model.Add(v == 0)
