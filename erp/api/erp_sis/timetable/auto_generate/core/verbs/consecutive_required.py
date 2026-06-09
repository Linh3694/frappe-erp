from ..force_pair_constraints import apply_force_pair_constraints
from ..helpers import instances, req_map
from ..registry import Verb, register_verb


@register_verb("consecutive_required", supports=["subject", "assignment"], kind="hard", description="Tiết phải theo cặp liên tiếp trong buổi")
class ConsecutiveRequired(Verb):
	def apply_hard(self, ctx, subject_set, params):
		inp = ctx.inp
		rmap = req_map(inp)
		size = int(params.get("size", 2))
		if size != 2:
			return

		# Chỉ lấy môn từ instances — user chọn thủ công trong Rule Set Builder
		pair_subjects: set = set()
		for inst in instances(params):
			if inst.get("subject"):
				pair_subjects.add(inst["subject"])
		if not pair_subjects:
			return

		for c in inp.classes:
			for ts_id in inp.class_subjects.get(c.name, []):
				if ts_id not in pair_subjects:
					continue
				req = rmap.get((c.name, ts_id))
				ppw = req.periods_per_week if req else 0
				if ppw <= 0:
					continue
				apply_force_pair_constraints(ctx, c.name, ts_id, ppw)
