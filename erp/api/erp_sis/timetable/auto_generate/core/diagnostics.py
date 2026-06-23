"""Chẩn đoán INFEASIBLE bằng 1 lần chạy — nới relaxable, trả % đáp ứng + chỗ thiếu.

Thay cho cách leave-one-out cũ (N+1 lần solve, chỉ ra "rule nào"): chạy 1 lần ở
chế độ diagnostic (mọi ràng buộc đếm/giới hạn chính sách nới thành slack), solver
luôn ra lời giải tốt nhất có thể, rồi đọc ctx.slacks để biết:
  - coverage_pct: đáp ứng bao nhiêu %.
  - shortfalls: lớp–môn nào thiếu mấy tiết (vô nghiệm ở đâu).
  - limit_violations: limit GV/môn nào bị vượt.
"""

from __future__ import annotations

from typing import Any

from .coverage import build_coverage_report
from .default_rules import build_default_rule_set
from .dto import RuleSet
from .runner import build_and_solve


def diagnose_infeasibility(inp: Any, rule_set: RuleSet | None = None) -> dict:
	"""Trả dict báo cáo chẩn đoán (1 lần solve, diagnostic mode)."""
	rs = rule_set or build_default_rule_set()
	solver, _builder, status, ctx = build_and_solve(inp, rs, diagnostic=True)

	if status not in ("OPTIMAL", "FEASIBLE"):
		# Nới hết relaxable vẫn vô nghiệm => xung đột ở rule cứng. Chạy UNSAT core
		# (1 lần solve nữa) để lần ra tập rule cứng mâu thuẫn tối thiểu.
		core = []
		try:
			_s, _b, _st, ctx2 = build_and_solve(inp, rs, diagnostic=True, assume_mode=True)
			core = ctx2.conflict_core
		except Exception:
			core = []
		return {
			"status": status,
			"feasible_relaxed": False,
			"coverage_pct": 0.0,
			"total_required": 0,
			"total_placed": 0,
			"total_short": 0,
			"shortfalls": [],
			"limit_violations": [],
			"forbidden_used": [],
			"pins_missed": [],
			"room_ineligible": [],
			"force_pair_broken": [],
			"conflict_core": core,
			"suspects": _core_suspects(core),
		}

	report = build_coverage_report(solver, ctx)
	report["status"] = status
	report["feasible_relaxed"] = True
	report["conflict_core"] = []
	report["suspects"] = _summarize_suspects(report)
	return report


def _core_suspects(core: list) -> list:
	"""Tập rule cứng mâu thuẫn -> list nghi phạm cho UI."""
	if not core:
		return [{
			"rule_id": "", "verb": "", "scope": {},
			"message": "Vô nghiệm do ràng buộc cứng nhưng không khoanh được rule cụ thể "
			           "(có thể do force_pair/cấu trúc). Kiểm tra pin, slot cấm, nhóm lớp.",
		}]
	return [{
		"rule_id": rid, "verb": "", "scope": {},
		"message": f"Rule cứng mâu thuẫn (không thể đồng thời thỏa): {rid}",
	} for rid in core]


def _summarize_suspects(report: dict) -> list:
	"""Tóm tắt vi phạm theo dạng list 'nghi phạm' cho UI hiện tại."""
	out = []
	for sf in report.get("shortfalls", []):
		out.append({
			"rule_id": "curriculum_exact_periods",
			"verb": "exact_count_per_week",
			"scope": {"class_id": sf.get("class_id"), "subject_id": sf.get("subject_id")},
			"message": (
				f"Lớp {sf.get('class_id')} — môn {sf.get('subject_id')} "
				f"thiếu {sf.get('short')}/{sf.get('required')} tiết"
			),
		})
	for lv in report.get("limit_violations", []):
		tag = lv.get("tag", "") or ""
		if tag.startswith("room:"):
			# tag = "room:{room_id}:{day}:{period_idx}" — phòng quá tải (đụng room_max).
			parts = tag.split(":")
			room = parts[1] if len(parts) > 1 else ""
			day = parts[2] if len(parts) > 2 else ""
			period = parts[3] if len(parts) > 3 else ""
			out.append({
				"rule_id": lv.get("rule_id", "") or "room_max_simultaneous",
				"verb": "room_max_simultaneous",
				"scope": {"room_id": room, "day": day, "period_idx": period},
				"message": f"Phòng {room} quá tải: thừa {lv.get('over')} lớp tại {day}/tiết {period}",
			})
		else:
			out.append({
				"rule_id": lv.get("rule_id", ""),
				"verb": "",
				"scope": {"tag": tag},
				"message": f"Vượt giới hạn {tag} thêm {lv.get('over')} tiết",
			})
	# Thiếu phòng hợp lệ — gộp theo (lớp, môn) đếm số slot để báo cáo gọn.
	room_inelig_agg: dict = {}
	for ri in report.get("room_ineligible", []):
		key = (ri.get("class_id"), ri.get("subject_id"))
		room_inelig_agg[key] = room_inelig_agg.get(key, 0) + 1
	for (class_id, subject_id), cnt in room_inelig_agg.items():
		out.append({
			"rule_id": "room_eligibility",
			"verb": "room_eligibility",
			"scope": {"class_id": class_id, "subject_id": subject_id},
			"message": (
				f"Lớp {class_id} môn {subject_id}: không còn phòng hợp lệ trống ở {cnt} slot "
				f"(thiếu phòng hoặc đụng giới hạn room_max)"
			),
		})
	for fp in report.get("force_pair_broken", []):
		out.append({
			"rule_id": fp.get("rule_id", "") or "system_force_pair",
			"verb": "force_pair",
			"scope": {"class_id": fp.get("class_id"), "subject_id": fp.get("subject_id")},
			"message": (
				f"Lớp {fp.get('class_id')} môn {fp.get('subject_id')}: không xếp được cặp tiết "
				f"(force_pair) — xem lại số tiết/buổi/pin"
			),
		})
	for fb in report.get("forbidden_used", []):
		out.append({
			"rule_id": fb.get("rule_id", ""),
			"verb": "forbidden_at_slots",
			"scope": {k: fb.get(k) for k in ("teacher_id", "day", "period_idx", "class_id", "subject_id")},
			"message": (
				f"Slot hạn chế bị buộc xếp: lớp {fb.get('class_id')} môn {fb.get('subject_id')} "
				f"{fb.get('day')}/tiết {fb.get('period_idx')}"
			),
		})
	for pm in report.get("pins_missed", []):
		out.append({
			"rule_id": pm.get("rule_id", ""),
			"verb": "pinned_to_slot",
			"scope": {k: pm.get(k) for k in ("class_id", "subject_id", "day", "period_idx")},
			"message": (
				f"Pin mềm không đạt: lớp {pm.get('class_id')} môn {pm.get('subject_id')} "
				f"không xếp được vào {pm.get('day')}/tiết {pm.get('period_idx')}"
			),
		})
	return out
