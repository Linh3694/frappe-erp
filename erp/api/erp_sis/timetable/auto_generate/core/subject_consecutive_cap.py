"""Ràng buộc hệ thống: không môn nào quá N tiết liền."""

from __future__ import annotations

from typing import Any


def apply_subject_max_consecutive_system_cap(ctx: Any, max_consecutive: int = 3) -> None:
	"""
	Áp hard constraint theo cửa sổ trượt:
	với mọi chuỗi dài max_consecutive+1 trong ngày, tổng biến <= max_consecutive.
	"""
	if max_consecutive <= 0:
		return

	window = max_consecutive + 1
	num_periods = ctx.num_periods
	if num_periods < window:
		return

	for c in ctx.inp.classes:
		for ts_id in ctx.inp.class_subjects.get(c.name, []):
			for day in ctx.working_days:
				for start in range(0, num_periods - window + 1):
					window_vars = []
					for p_idx in range(start, start + window):
						key = (c.name, ts_id, day, p_idx)
						v = ctx.x.get(key)
						if v is not None:
							window_vars.append(v)
					if len(window_vars) == window:
						ctx.model.Add(sum(window_vars) <= max_consecutive)
