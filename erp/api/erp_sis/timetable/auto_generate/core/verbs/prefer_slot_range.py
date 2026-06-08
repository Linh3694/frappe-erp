from ..helpers import instances
from ..registry import Verb, register_verb


@register_verb("prefer_slot_range", supports=["assignment", "subject"], kind="soft", description="Ưu tiên slot trong dải period")
class PreferSlotRange(Verb):
	def build_soft(self, ctx, subject_set, params, weight: int):
		inp = ctx.inp
		inst_list = instances(params)
		if inst_list or params.get("source") == "instances":
			terms = []
			for inst in inst_list:
				ts_id = inst.get("subject")
				obj = inst.get("object") or {}
				preferred = set(obj.get("periods") or [])
				if not ts_id or not preferred:
					continue
				for c in inp.classes:
					if ts_id not in inp.class_subjects.get(c.name, []):
						continue
					for day in inp.working_days:
						for p_idx in range(ctx.num_periods):
							v = ctx.x.get((c.name, ts_id, day, p_idx))
							if v is None:
								continue
							if p_idx in preferred:
								terms.append(v * weight)
							else:
								terms.append(v * (-weight * max(p_idx // 2, 1)))
			return terms

		# Legacy global periods (deprecated)
		preferred = set(params.get("periods") or [0, 1, 2, 3])
		terms = []
		for c in inp.classes:
			for ts_id in inp.class_subjects.get(c.name, []):
				if subject_set and ts_id not in subject_set:
					continue
				for day in inp.working_days:
					for p_idx in range(ctx.num_periods):
						v = ctx.x.get((c.name, ts_id, day, p_idx))
						if v is None:
							continue
						if p_idx in preferred:
							terms.append(v * weight)
						else:
							terms.append(v * (-weight * max(p_idx // 2, 1)))
		return terms
