"""Kiểm tra post-hoc force_pair — logic khớp force_pair_constraints."""

from __future__ import annotations

from typing import Dict, List, Tuple


def session_ranges(num_periods: int) -> List[Tuple[int, int]]:
	"""Chia buổi sáng/chiều theo nửa khung tiết."""
	half = num_periods // 2 or num_periods
	return [(0, half), (half, num_periods)]


def _paired_in_session(p: int, scheduled: set, h0: int, h1: int) -> bool:
	"""Tiết p có liền kề cùng môn trong buổi (h0..h1-1)."""
	if (p - 1) in scheduled and p > h0:
		return True
	if (p + 1) in scheduled and p < h1 - 1:
		return True
	return False


def check_force_pair_violations(
	num_periods: int,
	working_days: List[str],
	by_day: Dict[str, List[int]],
	periods_per_week: int,
) -> List[Tuple[str, int]]:
	"""
	Trả danh sách (day, period_index) vi phạm force_pair.
	- Tuần chẵn: mọi tiết xếp phải có cặp trong cùng buổi.
	- Tuần lẻ: cả tuần đúng 1 tiết lẻ (singleton trong buổi).
	"""
	if periods_per_week <= 0:
		return []

	ranges = session_ranges(num_periods)
	is_even = periods_per_week % 2 == 0
	violations: List[Tuple[str, int]] = []

	if is_even:
		for day in working_days:
			indices = by_day.get(day) or []
			scheduled = set(indices)
			for h0, h1 in ranges:
				for p in range(h0, h1):
					if p in scheduled and not _paired_in_session(p, scheduled, h0, h1):
						violations.append((day, p))
		return violations

	# Tuần lẻ: đếm singleton toàn tuần
	singletons: List[Tuple[str, int]] = []
	for day in working_days:
		indices = by_day.get(day) or []
		scheduled = set(indices)
		for h0, h1 in ranges:
			for p in range(h0, h1):
				if p in scheduled and not _paired_in_session(p, scheduled, h0, h1):
					singletons.append((day, p))

	if len(singletons) == 1:
		return []
	# 0 hoặc >1 singleton → báo tất cả singleton (hoặc thiếu tiết lẻ)
	return list(singletons)
