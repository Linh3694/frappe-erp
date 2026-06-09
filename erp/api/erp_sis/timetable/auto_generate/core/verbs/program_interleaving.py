from __future__ import annotations

from ..helpers import req_map
from ..registry import Verb, register_verb


@register_verb(
	"program_interleaving",
	supports=["assignment"],
	kind="soft",
	description="Ưu tiên xen kẽ chương trình trong ngày",
)
class ProgramInterleaving(Verb):
	def build_soft(self, ctx, subject_set, params, weight: int):
		inp = ctx.inp
		rmap = req_map(inp)
		objectives = []
		balance_weight = max(1, weight // 2)

		for cls in inp.classes:
			# Gom môn theo curriculum_id (program_id)
			program_subjects = {}
			for ts_id in inp.class_subjects.get(cls.name, []):
				req = rmap.get((cls.name, ts_id))
				program_id = getattr(req, "program_id", None) if req else None
				if not program_id:
					continue
				program_subjects.setdefault(program_id, []).append(ts_id)

			# Chỉ tối ưu xen kẽ khi trong lớp có >=2 chương trình
			if len(program_subjects) < 2:
				continue

			for day in inp.working_days:
				per_program_period = {}
				day_loads = []

				for program_id, subjects in program_subjects.items():
					period_vars = []
					for p_idx in range(ctx.num_periods):
						slot_vars = []
						for ts_id in subjects:
							key = (cls.name, ts_id, day, p_idx)
							v = ctx.x.get(key)
							if v is not None:
								slot_vars.append(v)
						if not slot_vars:
							continue
						has_program = ctx.model.NewBoolVar(f"pg_{cls.name}_{program_id}_{day}_{p_idx}")
						ctx.model.AddMaxEquality(has_program, slot_vars)
						period_vars.append((p_idx, has_program))
					if not period_vars:
						continue

					per_program_period[program_id] = {p: v for p, v in period_vars}
					load = ctx.model.NewIntVar(0, ctx.num_periods, f"pgl_{cls.name}_{program_id}_{day}")
					ctx.model.Add(load == sum(v for _, v in period_vars))
					day_loads.append(load)

				# Thành phần 1: phạt chuỗi liên tiếp cùng chương trình
				for program_id, pmap in per_program_period.items():
					for p_idx in range(ctx.num_periods - 1):
						v1 = pmap.get(p_idx)
						v2 = pmap.get(p_idx + 1)
						if v1 is None or v2 is None:
							continue
						same2 = ctx.model.NewBoolVar(f"pg2_{cls.name}_{program_id}_{day}_{p_idx}")
						ctx.model.AddBoolAnd([v1, v2]).OnlyEnforceIf(same2)
						ctx.model.AddBoolOr([v1.Not(), v2.Not()]).OnlyEnforceIf(same2.Not())
						objectives.append(same2 * (-weight))

					for p_idx in range(ctx.num_periods - 2):
						v1 = pmap.get(p_idx)
						v2 = pmap.get(p_idx + 1)
						v3 = pmap.get(p_idx + 2)
						if v1 is None or v2 is None or v3 is None:
							continue
						same3 = ctx.model.NewBoolVar(f"pg3_{cls.name}_{program_id}_{day}_{p_idx}")
						ctx.model.AddBoolAnd([v1, v2, v3]).OnlyEnforceIf(same3)
						ctx.model.AddBoolOr([v1.Not(), v2.Not(), v3.Not()]).OnlyEnforceIf(same3.Not())
						objectives.append(same3 * (-weight))

				# Thành phần 2: cân bằng tải chương trình trong cùng ngày
				if len(day_loads) >= 2:
					max_load = ctx.model.NewIntVar(0, ctx.num_periods, f"pgmx_{cls.name}_{day}")
					min_load = ctx.model.NewIntVar(0, ctx.num_periods, f"pgmn_{cls.name}_{day}")
					ctx.model.AddMaxEquality(max_load, day_loads)
					ctx.model.AddMinEquality(min_load, day_loads)
					diff = ctx.model.NewIntVar(0, ctx.num_periods, f"pgdf_{cls.name}_{day}")
					ctx.model.Add(diff == max_load - min_load)
					objectives.append(diff * (-balance_weight))

		return objectives
