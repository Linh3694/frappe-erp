from ..helpers import instances
from ..registry import Verb, register_verb


@register_verb("sync_class_group", supports=["class"], kind="hard", description="Nhóm lớp cùng môn cùng slot")
class SyncClassGroup(Verb):
	def apply_hard(self, ctx, subject_set, params):
		inp = ctx.inp
		for inst in instances(params):
			obj = inst.get("object") or {}
			ts_id = obj.get("timetable_subject_id") or obj.get("subject_id")
			class_ids = obj.get("class_ids") or []
			if not ts_id or not isinstance(class_ids, list) or len(class_ids) < 2:
				continue
			unique = [c for c in class_ids if c]
			if len(unique) < 2:
				continue
			for day in inp.working_days:
				for p_idx in range(ctx.num_periods):
					vars_ = []
					for c_id in unique:
						v = ctx.x.get((c_id, ts_id, day, p_idx))
						if v is not None:
							vars_.append(v)
					for i in range(1, len(vars_)):
						ctx.model.Add(vars_[0] == vars_[i])
