"""Dựng báo cáo "% đáp ứng / vô nghiệm ở đâu" từ ctx.slacks sau khi solve.

Đọc giá trị slack (short/limit) qua solver.Value() và tổng hợp:
  - coverage_pct: % tiết yêu cầu đã xếp được.
  - shortfalls:   từng cặp lớp–môn thiếu mấy tiết (sort giảm dần).
  - limit_violations: các limit chính sách (GV/môn) bị vượt khi nới.
"""

from __future__ import annotations

from typing import Any


def build_coverage_report(solver: Any, ctx: Any) -> dict:
	"""Trả dict báo cáo. Gọi sau khi solve xong (status OPTIMAL/FEASIBLE)."""
	total_required = sum(
		int(getattr(r, "periods_per_week", 0) or 0) for r in ctx.inp.requirements
	)

	shortfalls = []
	limit_violations = []
	forbidden_used = []
	pins_missed = []
	total_short = 0

	for s in ctx.slacks:
		try:
			val = int(round(solver.Value(s["var"])))
		except Exception:
			continue
		if val <= 0:
			continue
		kind = s.get("kind")
		scope = dict(s.get("scope") or {})
		if kind == "short":
			total_short += val
			shortfalls.append({**scope, "short": val})
		elif kind == "limit":
			limit_violations.append({"rule_id": s.get("rule_id", ""), **scope, "over": val})
		elif kind == "forbidden":
			# Slot "hạn chế" (relaxable) bị buộc phải xếp.
			forbidden_used.append({"rule_id": s.get("rule_id", ""), **scope})
		elif kind == "pin_missed":
			# Pin mềm (relaxable) không đặt được đúng slot mong muốn.
			pins_missed.append({"rule_id": s.get("rule_id", ""), **scope})

	if total_required > 0:
		coverage_pct = round(100.0 * (total_required - total_short) / total_required, 1)
	else:
		coverage_pct = 100.0

	return {
		"coverage_pct": coverage_pct,
		"total_required": total_required,
		"total_placed": total_required - total_short,
		"total_short": total_short,
		"shortfalls": sorted(shortfalls, key=lambda x: -x["short"]),
		"limit_violations": limit_violations,
		"forbidden_used": forbidden_used,
		"pins_missed": pins_missed,
	}
