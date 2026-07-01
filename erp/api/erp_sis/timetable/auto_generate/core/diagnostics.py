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
		# Nới hết relaxable vẫn vô nghiệm => xung đột ở ràng buộc cứng còn lại
		# (pin / slot cấm / nhóm lớp / thứ tự / trùng lịch...).
		# Số tiết yêu cầu vẫn đo được — KHÔNG trả 0/0 giả (dễ hiểu nhầm "đã đủ").
		total_required = sum(
			int(getattr(r, "periods_per_week", 0) or 0)
			for r in (getattr(inp, "requirements", None) or [])
		)
		# 1) UNSAT core: chỉ bắt được rule cứng nào có gắn assumption literal.
		core = []
		try:
			_s, _b, _st, ctx2 = build_and_solve(inp, rs, diagnostic=True, assume_mode=True)
			core = ctx2.conflict_core
		except Exception:
			core = []
		# 2) Ablation: nếu core rỗng, tắt lần lượt từng họ ràng buộc cứng rồi giải lại;
		# họ nào bỏ đi thì xếp được chính là nguồn gây vô nghiệm — báo có TÊN.
		suspects = _core_suspects(core)
		if not core:
			try:
				ablation = _ablation_culprits(inp, rs)
				if ablation:
					suspects = ablation
			except Exception:
				pass
		return {
			"status": status,
			"feasible_relaxed": False,
			"coverage_pct": 0.0,
			"total_required": total_required,
			"total_placed": 0,
			"total_short": total_required,
			"shortfalls": [],
			"limit_violations": [],
			"forbidden_used": [],
			"pins_missed": [],
			"room_ineligible": [],
			"force_pair_broken": [],
			"conflict_core": core,
			"suspects": suspects,
		}

	report = build_coverage_report(solver, ctx)
	report["status"] = status
	report["feasible_relaxed"] = True
	report["conflict_core"] = []
	report["suspects"] = _summarize_suspects(report)
	return report


# Nhãn thân thiện cho từng họ ràng buộc cứng khi báo cáo ablation.
_FAMILY_LABELS = {
	"class_no_overlap": "Mỗi lớp tối đa 1 môn/slot (trùng lịch lớp)",
	"teacher_no_overlap": "Mỗi GV tối đa 1 lớp/slot (trùng lịch GV)",
	"teacher_unavailable": "Slot bận của giáo viên",
	"subject_not_at_slot": "Slot cấm theo môn",
	"teacher_not_at_slot": "Slot cấm theo giáo viên",
	"teacher_not_on_day": "Ngày cấm của giáo viên",
	"pin_class_subject_slot": "Pin lớp + môn + slot",
	"class_group_simultaneous_subject": "Nhóm lớp cùng môn cùng slot",
	"subject_before_subject": "Thứ tự môn trong ngày",
	"subject_max_simultaneous_classes": "Giới hạn số lớp đồng thời",
	"system_subject_consecutive_cap": "Không quá 3 tiết liền/môn/ngày",
	"system_teacher_max_consecutive": "Max tiết liên tiếp của giáo viên",
}

# Các họ đã bị nới thành slack ở diagnostic mode → tắt cũng không đổi tính khả thi;
# bỏ qua trong ablation để khỏi tốn lượt giải vô ích.
_RELAXED_IN_DIAGNOSTIC = frozenset({
	"curriculum_exact_periods", "subject_max_per_day",
	"teacher_max_periods_per_day", "teacher_max_periods_per_week",
	"room_max_simultaneous", "room_eligibility", "system_force_pair",
})

_SYSTEM_FAMILIES = ("system_subject_consecutive_cap", "system_teacher_max_consecutive")


def _diag_feasible(inp, rs, *, overrides=None, skip_system=None) -> bool:
	"""Giải lại ở diagnostic mode (đã nới coverage) và trả True nếu ra được lời giải."""
	rs_use = rs
	if overrides is not None:
		rs_use = RuleSet(name=rs.name, rules=rs.rules, overrides=overrides)
	_s, _b, st, _c = build_and_solve(inp, rs_use, diagnostic=True, skip_system=skip_system)
	return st in ("OPTIMAL", "FEASIBLE")


def _ablation_culprits(inp, rs, *, max_report: int = 4) -> list:
	"""Tắt lần lượt từng họ ràng buộc cứng (giữ diagnostic=True) rồi giải lại. Họ nào
	bỏ đi thì xếp được chính là nguồn gây vô nghiệm → trả list nghi phạm CÓ TÊN.

	Chỉ chạy khi lời giải nới-lỏng đã vô nghiệm và UNSAT core rỗng. Rút ngắn thời
	gian mỗi lượt giải vì chỉ cần biết khả thi hay không.
	"""
	orig_limit = getattr(inp, "solver_time_limit", None)
	culprits: list = []
	try:
		if isinstance(orig_limit, (int, float)) and orig_limit > 8:
			inp.solver_time_limit = 8

		base_overrides = dict(getattr(rs, "overrides", None) or {})
		rule_candidates = [
			r.rule_id for r in rs.effective()
			if r.kind == "hard" and r.rule_id not in _RELAXED_IN_DIAGNOSTIC
		]
		for rid in rule_candidates:
			if len(culprits) >= max_report:
				break
			ov = dict(base_overrides)
			ov[rid] = {**(ov.get(rid) or {}), "enabled": False}
			try:
				if _diag_feasible(inp, rs, overrides=ov):
					culprits.append(rid)
			except Exception:
				continue
		for fam in _SYSTEM_FAMILIES:
			if len(culprits) >= max_report:
				break
			try:
				if _diag_feasible(inp, rs, skip_system=frozenset({fam})):
					culprits.append(fam)
			except Exception:
				continue
	finally:
		if orig_limit is not None:
			inp.solver_time_limit = orig_limit

	if not culprits:
		return []
	out = []
	for rid in culprits:
		label = _FAMILY_LABELS.get(rid, rid)
		out.append({
			"rule_id": rid,
			"verb": "",
			"scope": {},
			"message": (
				f"Bỏ ràng buộc “{label}” thì xếp được → đây là nguồn gây vô nghiệm. "
				f"Rà lại cấu hình phần này."
			),
		})
	return out


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
