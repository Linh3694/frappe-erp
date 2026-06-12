from ..helpers import instances, inst_object_int
from ..registry import Verb, register_verb


@register_verb("at_most_simultaneous", supports=["subject"], kind="hard", description="Tối đa N lớp học môn X cùng slot")
class AtMostSimultaneous(Verb):
	def apply_hard(self, ctx, subject_set, params):
		inp = ctx.inp
		for inst in instances(params):
			obj = inst.get("object") or {}
			ts_ids = []
			for sid in obj.get("subject_ids") or []:
				if sid:
					ts_ids.append(str(sid).strip())
			legacy_subject = obj.get("subject_id") or inst.get("subject")
			if legacy_subject:
				ts_ids.append(str(legacy_subject).strip())
			ts_ids = [sid for i, sid in enumerate(ts_ids) if sid and sid not in ts_ids[:i]]
			n = inst_object_int(inst, "max_classes", params.get("max_classes", 1))
			if not ts_ids:
				continue
			for day in inp.working_days:
				for p_idx in range(ctx.num_periods):
					vars_ = []
					for c in inp.classes:
						class_subjects = inp.class_subjects.get(c.name, [])
						for ts_id in ts_ids:
							if ts_id not in class_subjects:
								continue
							v = ctx.x.get((c.name, ts_id, day, p_idx))
							if v is not None:
								vars_.append(v)
					if vars_:
						ctx.add_hard(ctx.model.Add(sum(vars_) <= n))
