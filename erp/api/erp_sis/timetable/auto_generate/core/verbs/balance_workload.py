from ..helpers import teacher_class_subjects
from ..registry import Verb, register_verb


@register_verb("balance_workload", supports=["teacher"], kind="soft", description="Cân bằng tiết GV giữa các ngày")
class BalanceWorkload(Verb):
	def build_soft(self, ctx, subject_set, params, weight: int):
		inp = ctx.inp
		tcs = teacher_class_subjects(inp)
		for t_id, cs_list in tcs.items():
			info = inp.teachers.get(t_id)
			mode = getattr(info, "workload_spread_mode", "auto") if info else "auto"
			if mode == "auto":
				continue
			tier = getattr(info, "tier_balance", "weak") if info else "weak"

			day_loads = []
			for day in inp.working_days:
				dv = []
				for p_idx in range(ctx.num_periods):
					for (c_id, ts_id) in cs_list:
						v = ctx.x.get((c_id, ts_id, day, p_idx))
						if v is not None:
							dv.append(v)
				if dv:
					load = ctx.model.NewIntVar(0, ctx.num_periods, f"bw_{t_id}_{day}")
					ctx.model.Add(load == sum(dv))
					day_loads.append(load)
			if len(day_loads) < 2:
				continue

			mx = ctx.model.NewIntVar(0, ctx.num_periods, f"bwmx_{t_id}")
			mn = ctx.model.NewIntVar(0, ctx.num_periods, f"bwmn_{t_id}")
			ctx.model.AddMaxEquality(mx, day_loads)
			ctx.model.AddMinEquality(mn, day_loads)
			diff = ctx.model.NewIntVar(0, ctx.num_periods, f"bwd_{t_id}")
			ctx.model.Add(diff == mx - mn)

			if mode == "even":
				# Dạy đều — giảm chênh lệch giữa ngày nhiều/nhất và ít nhất
				ctx.add_soft(tier, diff * (-weight))
			elif mode == "concentrated":
				# Dồn 1 ngày — ưu tiên tăng chênh lệch (dồn tiết vào ít ngày)
				ctx.add_soft(tier, diff * weight)
		return []  # self-bucket theo tier per-GV
