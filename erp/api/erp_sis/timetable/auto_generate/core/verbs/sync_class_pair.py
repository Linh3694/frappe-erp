from ..helpers import instances
from ..registry import Verb, register_verb


@register_verb("sync_class_pair", supports=["class"], kind="hard", description="Hai lớp cùng môn cùng slot")
class SyncClassPair(Verb):
	def apply_hard(self, ctx, subject_set, params):
		inp = ctx.inp
		for inst in instances(params):
			c1 = inst.get("subject") or inst.get("class_id")
			obj = inst.get("object") or {}
			c2 = obj.get("peer_class_id") or obj.get("class_id")
			ts_id = obj.get("subject_id") or obj.get("timetable_subject_id")
			if not all([c1, c2, ts_id]):
				continue
			for day in inp.working_days:
				for p_idx in range(ctx.num_periods):
					v1 = ctx.x.get((c1, ts_id, day, p_idx))
					v2 = ctx.x.get((c2, ts_id, day, p_idx))
					if v1 is not None and v2 is not None:
						ctx.model.Add(v1 == v2)
