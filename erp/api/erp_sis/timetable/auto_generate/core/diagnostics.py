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
		# 1) Tiền-quét dữ liệu (0 lần giải): pin đụng pin chặn / ngày cấm môn / GV bận.
		# Bắt được thì chỉ đích danh lớp/môn/slot, khỏi cần ablation.
		prescan = []
		try:
			prescan = _data_contradictions(inp)
		except Exception:
			prescan = []
		# 2) UNSAT core: chỉ bắt được rule cứng nào có gắn assumption literal.
		core = []
		try:
			_s, _b, _st, ctx2 = build_and_solve(inp, rs, diagnostic=True, assume_mode=True)
			core = ctx2.conflict_core
		except Exception:
			core = []
		# 3) Ablation: tắt lần lượt từng họ ràng buộc cứng rồi giải lại (feasibility-only);
		# họ nào bỏ đi thì xếp được chính là nguồn gây vô nghiệm — báo có TÊN.
		suspects = list(prescan)
		ablation_trace: dict = {}
		if core:
			suspects.extend(_core_suspects(core))
		elif not suspects:
			try:
				ablation, ablation_trace = _ablation_culprits(inp, rs)
				suspects.extend(ablation)
			except Exception:
				pass
		if not suspects:
			suspects = _core_suspects([])
		return {
			"ablation_trace": ablation_trace,
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


# Thứ tự thử ablation: dữ liệu P0 hay sai trước (pin, slot cấm), vật lý sau cùng.
_ABLATION_PRIORITY = [
	"pin_class_subject_slot", "subject_not_at_slot", "teacher_not_at_slot",
	"teacher_not_on_day", "teacher_unavailable", "class_group_simultaneous_subject",
	"subject_before_subject", "subject_max_simultaneous_classes",
]
_PHYSICAL_LAST = ["class_no_overlap", "teacher_no_overlap"]


def _diag_status(inp, rs, *, disabled=frozenset(), skip_system=frozenset()) -> str:
	"""Giải feasibility-only ở diagnostic mode với 1 tập rule bị tắt. Trả status name."""
	rs_use = rs
	if disabled:
		ov = dict(getattr(rs, "overrides", None) or {})
		for rid in disabled:
			ov[rid] = {**(ov.get(rid) or {}), "enabled": False}
		rs_use = RuleSet(name=rs.name, rules=rs.rules, overrides=ov)
	_s, _b, st, _c = build_and_solve(
		inp, rs_use, diagnostic=True, skip_system=skip_system or None, feasibility_only=True,
	)
	return st


def _ablation_culprits(inp, rs, *, max_report: int = 4) -> tuple:
	"""Tắt lần lượt từng họ ràng buộc cứng rồi giải lại (feasibility-only). Họ nào bỏ
	đi thì xếp được chính là nguồn gây vô nghiệm → trả (suspects, trace).

	- Giải feasibility-only (không Maximize) nên mỗi lượt nhanh; UNKNOWN (hết giờ,
	  không kết luận được) được ghi riêng, KHÔNG coi là "không phải thủ phạm".
	- Nếu không họ đơn lẻ nào đủ, thử greedy tích luỹ (tắt dần nhiều họ).
	"""
	orig_limit = getattr(inp, "solver_time_limit", None)
	culprits: list = []
	trace: dict = {}
	try:
		if isinstance(orig_limit, (int, float)) and orig_limit > 15:
			inp.solver_time_limit = 15

		# Baseline: model gốc (chưa tắt gì) giải feasibility-only. Nếu ra nghiệm nghĩa là
		# lần chẩn đoán chính chỉ hết giờ ở pha Maximize chứ không hề vô nghiệm — báo
		# thẳng thay vì đổ oan cho một họ ràng buộc.
		try:
			base_st = _diag_status(inp, rs)
		except Exception:
			base_st = "ERROR"
		trace["baseline"] = base_st
		if base_st in ("OPTIMAL", "FEASIBLE"):
			return ([{
				"rule_id": "", "verb": "", "scope": {},
				"message": (
					"Model thực ra XẾP ĐƯỢC (kiểm tra nhanh ra nghiệm) — lần chẩn đoán chính "
					"chỉ hết thời gian ở bước tối ưu. Tăng thời gian solver rồi chạy lại."
				),
			}], trace)

		effective_ids = [
			r.rule_id for r in rs.effective()
			if r.kind == "hard" and r.rule_id not in _RELAXED_IN_DIAGNOSTIC
		]
		ordered = [rid for rid in _ABLATION_PRIORITY if rid in effective_ids]
		ordered += [rid for rid in effective_ids if rid not in ordered and rid not in _PHYSICAL_LAST]
		ordered += [rid for rid in _PHYSICAL_LAST if rid in effective_ids]
		families = [("rule", rid) for rid in ordered] + [("system", f) for f in _SYSTEM_FAMILIES]

		# Vòng 1: tắt từng họ đơn lẻ.
		for kind, fam in families:
			if len(culprits) >= max_report:
				break
			try:
				st = _diag_status(
					inp, rs,
					disabled=frozenset({fam}) if kind == "rule" else frozenset(),
					skip_system=frozenset({fam}) if kind == "system" else frozenset(),
				)
			except Exception:
				st = "ERROR"
			trace[fam] = st
			if st in ("OPTIMAL", "FEASIBLE"):
				culprits.append(fam)

		# Vòng 2: greedy tích luỹ khi không họ đơn lẻ nào đủ (mâu thuẫn đa-họ).
		if not culprits:
			disabled_rules: set = set()
			skip_sys: set = set()
			for kind, fam in families:
				if kind == "rule":
					disabled_rules.add(fam)
				else:
					skip_sys.add(fam)
				try:
					st = _diag_status(
						inp, rs, disabled=frozenset(disabled_rules), skip_system=frozenset(skip_sys),
					)
				except Exception:
					continue
				if st in ("OPTIMAL", "FEASIBLE"):
					culprits = sorted(disabled_rules | skip_sys)
					trace["cumulative"] = "+".join(culprits)
					break
	finally:
		if orig_limit is not None:
			inp.solver_time_limit = orig_limit

	suspects = []
	for rid in culprits[:max_report]:
		label = _FAMILY_LABELS.get(rid, rid)
		suspects.append({
			"rule_id": rid,
			"verb": "",
			"scope": {},
			"message": (
				f"Bỏ ràng buộc “{label}” thì xếp được → đây là nguồn gây vô nghiệm. "
				f"Rà lại cấu hình phần này."
			),
		})
	if not suspects:
		unknown = sorted(f for f, st in trace.items() if st == "UNKNOWN")
		if unknown:
			labels = ", ".join(_FAMILY_LABELS.get(f, f) for f in unknown[:5])
			suspects.append({
				"rule_id": "", "verb": "", "scope": {"inconclusive": unknown},
				"message": (
					f"Chưa đủ thời gian để kết luận cho các họ ràng buộc: {labels}. "
					f"Tăng thời gian solver rồi phân tích lại."
				),
			})
	return suspects, trace


def _data_contradictions(inp) -> list:
	"""Tiền-quét dữ liệu P0 (0 lần giải): pin bắt buộc đụng pin chặn / ngày cấm môn /
	GV bận / pin khác cùng slot. Trả list nghi phạm chỉ đích danh lớp/môn/slot."""
	from .helpers import class_subject_weekdays, teacher_class_subjects

	out = []
	pins = [p for p in (getattr(inp, "pinned_slots", None) or [])]

	def _mandatory(obj) -> bool:
		return str(getattr(obj, "enforcement", "mandatory") or "mandatory").lower() != "relaxable"

	def _p_idx(pin):
		return inp.column_period_index.get(pin.timetable_column_id)

	def _classes_of(pin):
		return [c.name for c in inp.classes if not pin.class_id or c.name == pin.class_id]

	hard_pins = []  # (class_id, ts_id, day, p_idx)
	for pin in pins:
		if pin.is_blocking or not _mandatory(pin) or not pin.timetable_subject_id:
			continue
		p = _p_idx(pin)
		if p is None:
			continue
		for c_id in _classes_of(pin):
			hard_pins.append((c_id, pin.timetable_subject_id, pin.day_of_week, p))

	if not hard_pins:
		return out

	# 1) Pin bắt buộc ↔ pin CHẶN bắt buộc cùng (lớp, slot).
	blocked = set()
	for pin in pins:
		if not pin.is_blocking or not _mandatory(pin):
			continue
		p = _p_idx(pin)
		if p is None:
			continue
		for c_id in _classes_of(pin):
			blocked.add((c_id, pin.day_of_week, p))
	for (c_id, ts_id, day, p) in hard_pins:
		if (c_id, day, p) in blocked:
			out.append({
				"rule_id": "pin_class_subject_slot", "verb": "pinned_to_slot",
				"scope": {"class_id": c_id, "subject_id": ts_id, "day": day, "period_idx": p},
				"message": (
					f"Pin bắt buộc lớp {c_id} môn {ts_id} vào {day}/tiết {p + 1} "
					f"nhưng slot này đang bị PIN CHẶN — bỏ một trong hai."
				),
			})

	# 2) Pin bắt buộc ↔ ngày không được phép của môn (weekday availability).
	try:
		csw = class_subject_weekdays(inp)
	except Exception:
		csw = {}
	for (c_id, ts_id, day, p) in hard_pins:
		allowed = csw.get((c_id, ts_id))
		if allowed is not None and day not in allowed:
			out.append({
				"rule_id": "pin_class_subject_slot", "verb": "pinned_to_slot",
				"scope": {"class_id": c_id, "subject_id": ts_id, "day": day, "period_idx": p},
				"message": (
					f"Pin bắt buộc lớp {c_id} môn {ts_id} vào {day} nhưng môn này "
					f"chỉ được học vào: {', '.join(sorted(allowed)) or '(không ngày nào)'} — sửa pin hoặc ngày học."
				),
			})

	# 3) Pin bắt buộc ↔ GV bận (mandatory unavailable) đúng slot đó.
	try:
		tcs = teacher_class_subjects(inp)
	except Exception:
		tcs = {}
	teachers_of: dict = {}
	for t_id, lst in tcs.items():
		for key in lst:
			teachers_of.setdefault(key, []).append(t_id)
	for (c_id, ts_id, day, p) in hard_pins:
		for t_id in teachers_of.get((c_id, ts_id), []):
			info = inp.teachers.get(t_id)
			for slot in (getattr(info, "unavailable_slots", None) or []):
				s_day = slot[0] if isinstance(slot, (list, tuple)) else getattr(slot, "day", None)
				s_p = slot[1] if isinstance(slot, (list, tuple)) else getattr(slot, "period_idx", None)
				s_enf = (
					(slot[2] if len(slot) > 2 else "mandatory")
					if isinstance(slot, (list, tuple))
					else getattr(slot, "enforcement", "mandatory")
				)
				if s_day == day and s_p == p and str(s_enf or "mandatory").lower() != "relaxable":
					out.append({
						"rule_id": "pin_class_subject_slot", "verb": "pinned_to_slot",
						"scope": {"class_id": c_id, "subject_id": ts_id, "teacher_id": t_id,
						          "day": day, "period_idx": p},
						"message": (
							f"Pin bắt buộc lớp {c_id} môn {ts_id} vào {day}/tiết {p + 1} "
							f"nhưng GV {t_id} bận (bắt buộc) đúng slot này."
						),
					})

	# 4) Hai pin bắt buộc khác môn đụng nhau cùng (lớp, slot).
	seen: dict = {}
	for (c_id, ts_id, day, p) in hard_pins:
		key = (c_id, day, p)
		if key in seen and seen[key] != ts_id:
			out.append({
				"rule_id": "pin_class_subject_slot", "verb": "pinned_to_slot",
				"scope": {"class_id": c_id, "day": day, "period_idx": p},
				"message": (
					f"Hai pin bắt buộc đụng nhau: lớp {c_id} tại {day}/tiết {p + 1} "
					f"vừa pin môn {seen[key]} vừa pin môn {ts_id}."
				),
			})
		else:
			seen[key] = ts_id

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
