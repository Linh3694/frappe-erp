"""Ràng buộc cặp tiết (force_pair) — dùng chung runner + consecutive_required."""

from __future__ import annotations

from typing import Any, List, Tuple

from .helpers import req_map


def _session_ranges(num_periods: int) -> List[Tuple[int, int]]:
	"""Chia buổi sáng/chiều theo nửa khung tiết."""
	half = num_periods // 2 or num_periods
	return [(0, half), (half, num_periods)]


def apply_force_pair_constraints(ctx: Any, class_id: str, subject_id: str, periods_per_week: int) -> None:
	"""
	Môn bắt buộc cặp tiết liên tiếp trong cùng buổi:
	- Tiết/tuần chẵn: mọi tiết xếp phải thuộc cặp (không có tiết lẻ).
	- Tiết/tuần lẻ: cho phép đúng 1 tiết lẻ trong tuần, xếp ở slot bất kỳ; các tiết còn lại phải theo cặp.
	"""
	if periods_per_week <= 0:
		return

	model = ctx.model
	num = ctx.num_periods
	is_even = periods_per_week % 2 == 0
	singleton_vars: List[Any] = []

	for day in ctx.working_days:
		for h0, h1 in _session_ranges(num):
			for p in range(h0, h1):
				v = ctx.x.get((class_id, subject_id, day, p))
				if v is None:
					continue

				left_v = ctx.x.get((class_id, subject_id, day, p - 1)) if p > h0 else None
				right_v = ctx.x.get((class_id, subject_id, day, p + 1)) if p < h1 - 1 else None

				paired_terms: List[Any] = []
				if left_v is not None:
					both_left = model.NewBoolVar(f"fp_l_{class_id}_{subject_id}_{day}_{p}")
					model.AddBoolAnd([v, left_v]).OnlyEnforceIf(both_left)
					model.AddBoolOr([v.Not(), left_v.Not()]).OnlyEnforceIf(both_left.Not())
					paired_terms.append(both_left)
				if right_v is not None:
					both_right = model.NewBoolVar(f"fp_r_{class_id}_{subject_id}_{day}_{p}")
					model.AddBoolAnd([v, right_v]).OnlyEnforceIf(both_right)
					model.AddBoolOr([v.Not(), right_v.Not()]).OnlyEnforceIf(both_right.Not())
					paired_terms.append(both_right)

				if is_even:
					# Tiết/tuần chẵn: mỗi tiết xếp phải có liền kề cùng môn trong buổi
					if paired_terms:
						model.AddBoolOr(paired_terms).OnlyEnforceIf(v)
					else:
						model.Add(v == 0)
				else:
					# Tiết/tuần lẻ: đánh dấu tiết lẻ (xếp 1 mình trong buổi)
					is_paired = model.NewBoolVar(f"fp_p_{class_id}_{subject_id}_{day}_{p}")
					if paired_terms:
						model.AddMaxEquality(is_paired, paired_terms)
					else:
						model.Add(is_paired == 0)

					singleton = model.NewBoolVar(f"fp_s_{class_id}_{subject_id}_{day}_{p}")
					model.AddBoolAnd([v, is_paired.Not()]).OnlyEnforceIf(singleton)
					model.AddBoolOr([v.Not(), is_paired]).OnlyEnforceIf(singleton.Not())
					singleton_vars.append(singleton)

	if not is_even and singleton_vars:
		model.Add(sum(singleton_vars) == 1)


def apply_requirement_force_pairs(ctx: Any) -> None:
	"""Áp dụng force_pair từ ma trận requirement (checkbox Cặp trên UI)."""
	rmap = req_map(ctx.inp)
	for c in ctx.inp.classes:
		for ts_id in ctx.inp.class_subjects.get(c.name, []):
			req = rmap.get((c.name, ts_id))
			if req and req.force_pair:
				apply_force_pair_constraints(ctx, c.name, ts_id, req.periods_per_week)
