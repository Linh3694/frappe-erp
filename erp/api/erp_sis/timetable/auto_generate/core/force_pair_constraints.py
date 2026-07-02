"""Ràng buộc cặp tiết (force_pair) — dùng chung runner + consecutive_required.

3 nấc (force_pair_mode): hard = cứng tuyệt đối (vô nghiệm nếu không ghép nổi);
relaxable = phá khi bí, phạt nặng THEO TỪNG tiết lẻ + báo cáo force_pair_broken;
soft = ưu tiên ghép ở tầng weak, nhường khi đụng ràng buộc khác.
"""

from __future__ import annotations

from typing import Any, List, Tuple

from .helpers import req_map
from .tiers import (
	FP_HARD,
	FP_RELAX_BREAK_PENALTY,
	FP_RELAXABLE,
	FP_SOFT,
	FP_SOFT_WEIGHT,
	RELAX_FORBIDDEN_PENALTY,
	RELAXABLE,
	WEAK,
	normalize_fp_mode,
)


def _session_ranges(num_periods: int) -> List[Tuple[int, int]]:
	"""Chia buổi sáng/chiều theo nửa khung tiết."""
	half = num_periods // 2 or num_periods
	return [(0, half), (half, num_periods)]


def _apply_pair_preference(
	ctx: Any, class_id: str, subject_id: str, periods_per_week: int, *, mode: str,
) -> None:
	"""Cặp mềm/hạn chế: đếm tiết lẻ (kể cả slot không có hàng xóm trong buổi) rồi
	phạt phần vượt quá số tiết lẻ được phép (ppw lẻ → 1). Phạt theo SỐ LƯỢNG nên
	vỡ một cặp không "thả trôi" các cặp còn lại như cờ all-or-nothing."""
	model = ctx.model
	num = ctx.num_periods
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
					both_left = model.NewBoolVar(f"fpp_l_{class_id}_{subject_id}_{day}_{p}")
					model.AddBoolAnd([v, left_v]).OnlyEnforceIf(both_left)
					model.AddBoolOr([v.Not(), left_v.Not()]).OnlyEnforceIf(both_left.Not())
					paired_terms.append(both_left)
				if right_v is not None:
					both_right = model.NewBoolVar(f"fpp_r_{class_id}_{subject_id}_{day}_{p}")
					model.AddBoolAnd([v, right_v]).OnlyEnforceIf(both_right)
					model.AddBoolOr([v.Not(), right_v.Not()]).OnlyEnforceIf(both_right.Not())
					paired_terms.append(both_right)

				is_paired = model.NewBoolVar(f"fpp_p_{class_id}_{subject_id}_{day}_{p}")
				if paired_terms:
					model.AddMaxEquality(is_paired, paired_terms)
				else:
					# Slot cô lập trong buổi (không có hàng xóm) — xếp vào là tiết lẻ.
					model.Add(is_paired == 0)

				singleton = model.NewBoolVar(f"fpp_s_{class_id}_{subject_id}_{day}_{p}")
				model.AddBoolAnd([v, is_paired.Not()]).OnlyEnforceIf(singleton)
				model.AddBoolOr([v.Not(), is_paired]).OnlyEnforceIf(singleton.Not())
				singleton_vars.append(singleton)

	if not singleton_vars:
		return
	allowed = periods_per_week % 2  # ppw lẻ được đúng 1 tiết lẻ "miễn phí"
	excess = model.NewIntVar(0, len(singleton_vars), f"fpp_excess_{class_id}_{subject_id}")
	model.Add(excess >= sum(singleton_vars) - allowed)
	if mode == FP_RELAXABLE:
		ctx.add_soft(RELAXABLE, excess * (-FP_RELAX_BREAK_PENALTY))
		ctx.add_violation(
			getattr(ctx, "cur_rule_id", "") or "system_force_pair",
			"force_pair_broken",
			{"class_id": class_id, "subject_id": subject_id},
			excess,
		)
	else:
		ctx.add_soft(WEAK, excess * (-FP_SOFT_WEIGHT))


def apply_force_pair_constraints(
	ctx: Any, class_id: str, subject_id: str, periods_per_week: int, mode: str = FP_HARD,
) -> None:
	"""
	Môn bắt buộc cặp tiết liên tiếp trong cùng buổi:
	- Tiết/tuần chẵn: mọi tiết xếp phải thuộc cặp (không có tiết lẻ).
	- Tiết/tuần lẻ: cho phép đúng 1 tiết lẻ trong tuần, xếp ở slot bất kỳ; các tiết còn lại phải theo cặp.

	mode: hard (mặc định — hành vi cũ) | relaxable | soft (xem _apply_pair_preference).
	"""
	if periods_per_week <= 0:
		return
	if mode in (FP_RELAXABLE, FP_SOFT):
		_apply_pair_preference(ctx, class_id, subject_id, periods_per_week, mode=mode)
		return

	model = ctx.model
	num = ctx.num_periods
	is_even = periods_per_week % 2 == 0
	singleton_vars: List[Any] = []

	# Chế độ chẩn đoán: gắn 1 cờ "phá cặp" cho mỗi (lớp, môn) để nới toàn bộ ràng buộc
	# force_pair của cặp đó thành slack (phạt RELAXABLE) → định vị được force_pair gây
	# vô nghiệm thay vì trả UNSAT core rỗng. Lần giải thật giữ cứng.
	fp_broken = None
	if getattr(ctx, "diagnostic", False):
		fp_broken = model.NewBoolVar(f"fp_broken_{class_id}_{subject_id}")
		ctx.add_soft(RELAXABLE, fp_broken * (-RELAX_FORBIDDEN_PENALTY))
		ctx.add_violation(
			getattr(ctx, "cur_rule_id", "") or "system_force_pair",
			"force_pair_broken",
			{"class_id": class_id, "subject_id": subject_id},
			fp_broken,
		)

	def _gate(lits):
		"""enforce-if cho ràng buộc cứng; ở chẩn đoán thêm fp_broken.Not()."""
		out = list(lits)
		if fp_broken is not None:
			out.append(fp_broken.Not())
		return out

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
						model.AddBoolOr(paired_terms).OnlyEnforceIf(_gate([v]))
					elif fp_broken is not None:
						model.Add(v == 0).OnlyEnforceIf(fp_broken.Not())
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
		if fp_broken is not None:
			model.Add(sum(singleton_vars) == 1).OnlyEnforceIf(fp_broken.Not())
		else:
			model.Add(sum(singleton_vars) == 1)


def apply_requirement_force_pairs(ctx: Any) -> None:
	"""Áp dụng force_pair từ ma trận requirement (chọn Cặp trên UI, 3 nấc)."""
	rmap = req_map(ctx.inp)
	for c in ctx.inp.classes:
		for ts_id in ctx.inp.class_subjects.get(c.name, []):
			req = rmap.get((c.name, ts_id))
			if not req or not req.force_pair:
				continue
			mode = normalize_fp_mode(req.force_pair)
			if mode:
				apply_force_pair_constraints(ctx, c.name, ts_id, req.periods_per_week, mode=mode)
