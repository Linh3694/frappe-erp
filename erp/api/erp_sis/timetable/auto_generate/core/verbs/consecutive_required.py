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
		num = ctx.num_periods
		half = num // 2 or num

		# Chỉ lấy môn từ instances — user chọn thủ công trong Rule Set Builder
		pair_subjects: set = set()
		for inst in instances(params):
			if inst.get("subject"):
				pair_subjects.add(inst["subject"])
		if not pair_subjects:
			return

		for c in inp.classes:
			g = c.education_grade_id
			for ts_id in inp.grade_subjects.get(g, []):
				if ts_id not in pair_subjects:
					continue
				for day in inp.working_days:
					for h0, h1 in [(0, half), (half, num)]:
						slots = list(range(h0, h1))
						k = 0
						while k + 1 < len(slots):
							pa, pb = slots[k], slots[k + 1]
							va = ctx.x.get((c.name, ts_id, day, pa))
							vb = ctx.x.get((c.name, ts_id, day, pb))
							if va is not None and vb is not None:
								ctx.model.Add(va == vb)
							k += 2
						if len(slots) % 2 == 1:
							vl = ctx.x.get((c.name, ts_id, day, slots[-1]))
							if vl is not None:
								ctx.model.Add(vl == 0)
