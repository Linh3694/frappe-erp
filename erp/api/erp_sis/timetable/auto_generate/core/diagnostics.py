"""Chẩn đoán INFEASIBLE bằng 1 lần chạy — nới relaxable, trả % đáp ứng + chỗ thiếu.

Thay cho cách leave-one-out cũ (N+1 lần solve, chỉ ra "rule nào"): chạy 1 lần ở
chế độ diagnostic (mọi ràng buộc đếm/giới hạn chính sách nới thành slack), solver
luôn ra lời giải tốt nhất có thể, rồi đọc ctx.slacks để biết:
  - coverage_pct: đáp ứng bao nhiêu %.
  - shortfalls: lớp–môn nào thiếu mấy tiết (vô nghiệm ở đâu).
  - limit_violations: limit GV/môn nào bị vượt.
"""

from __future__ import annotations

import time
from typing import Any

from .coverage import build_coverage_report
from .default_rules import build_default_rule_set
from .dto import RuleSet
from .runner import build_and_solve


def diagnose_infeasibility(inp: Any, rule_set: RuleSet | None = None) -> dict:
	"""Trả dict báo cáo chẩn đoán (1 lần solve, diagnostic mode)."""
	rs = rule_set or build_default_rule_set()
	solver, builder, status, ctx = build_and_solve(inp, rs, diagnostic=True)

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
		# 2) UNSAT core: chỉ có nghĩa khi status là INFEASIBLE thật. UNKNOWN = hết giờ
		# chưa kết luận — chạy assume pass chỉ tốn thêm 1 lượt giải vô ích.
		core = []
		if status == "INFEASIBLE":
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
	_enrich_labels(report, inp)
	report["status"] = status
	report["feasible_relaxed"] = True
	report["conflict_core"] = []
	report["suspects"] = _summarize_suspects(report)
	# Lời giải nới lỏng chính là bản TKB nháp "tốt nhất có thể" — trả kèm để caller
	# lưu cho user xem trước (thay vì vứt đi rồi chỉ báo con số %).
	try:
		report["draft_slots"] = builder.extract_solution(solver)
	except Exception:
		pass
	return report


def _label_maps(inp) -> tuple:
	"""(class, subject, teacher, room) id -> tên hiển thị, từ input đã nạp sẵn."""
	class_map = {c.name: (c.title or c.name) for c in (getattr(inp, "classes", None) or [])}
	subject_map = {}
	for r in (getattr(inp, "requirements", None) or []):
		if r.timetable_subject_id and r.timetable_subject_title:
			subject_map[r.timetable_subject_id] = r.timetable_subject_title
	teacher_map = {
		t_id: (getattr(t, "full_name", "") or t_id)
		for t_id, t in (getattr(inp, "teachers", {}) or {}).items()
	}
	room_map = {r.name: (r.title or r.name) for r in (getattr(inp, "rooms", None) or [])}
	return class_map, subject_map, teacher_map, room_map


def _enrich_labels(report: dict, inp) -> None:
	"""Gắn *_label (tên lớp/môn/GV/phòng) vào từng entry để UI hiện tên thay vì ID."""
	cmap, smap, tmap, rmap = _label_maps(inp)
	for key in ("shortfalls", "limit_violations", "forbidden_used", "pins_missed",
	            "room_ineligible", "force_pair_broken"):
		for row in report.get(key, []) or []:
			if row.get("class_id"):
				row["class_label"] = cmap.get(row["class_id"], row["class_id"])
			if row.get("subject_id"):
				row["subject_label"] = smap.get(row["subject_id"], row["subject_id"])
			if row.get("teacher_id"):
				row["teacher_label"] = tmap.get(row["teacher_id"], row["teacher_id"])
			if row.get("room_id"):
				row["room_label"] = rmap.get(row["room_id"], row["room_id"])


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


# Ngân sách wall-clock cho toàn bộ ablation (giây) — job nền, giữ dưới "vài phút".
_ABLATION_BUDGET_S = 240
_ABLATION_SOLVE_CAP_S = 12


def _family_skippable(rule, inp, n_forbidden_rules: int) -> bool:
	"""True nếu tắt rule này chắc chắn không đổi model (không có dữ liệu) → khỏi thử.

	Lưu ý: verb forbidden_at_slots còn áp weekday-availability bất kể instances,
	nên rule forbidden cuối cùng còn bật KHÔNG được cắt dù rỗng instance.
	"""
	from .helpers import instances as _instances

	rid = rule.rule_id
	if rid == "pin_class_subject_slot":
		has_pins = any(
			not getattr(p, "is_blocking", False)
			for p in (getattr(inp, "pinned_slots", None) or [])
		)
		return not (has_pins or _instances(rule.params or {}))
	if rule.verb == "forbidden_at_slots":
		if n_forbidden_rules <= 1:
			return False  # còn mang weekday-availability
		if rid == "teacher_unavailable":
			has_unavail = any(
				getattr(t, "unavailable_slots", None)
				for t in (getattr(inp, "teachers", {}) or {}).values()
			)
			return not (has_unavail or _instances(rule.params or {}))
		return not _instances(rule.params or {})
	if rule.verb == "allow_only_at_slots":
		has_blocking = any(
			getattr(p, "is_blocking", False)
			for p in (getattr(inp, "pinned_slots", None) or [])
		)
		return not (has_blocking or _instances(rule.params or {}))
	if rule.verb in ("forbidden_on_day", "order_before_same_day", "at_most_simultaneous", "pinned_to_slot"):
		return not _instances(rule.params or {})
	return False


def _ablation_culprits(inp, rs, *, max_report: int = 4) -> tuple:
	"""Tắt lần lượt từng họ ràng buộc cứng rồi giải lại (feasibility-only, KHÔNG build
	biến phòng). Họ nào bỏ đi thì xếp được chính là nguồn gây vô nghiệm → (suspects, trace).

	- Cắt trước các họ không có dữ liệu (tắt cũng như không) để đỡ tốn lượt giải.
	- Ngân sách wall-clock tổng ~4 phút; hết giờ thì báo trung thực họ nào chưa thử.
	- UNKNOWN (hết giờ 1 lượt) ghi riêng, KHÔNG coi là "không phải thủ phạm".
	"""
	orig_limit = getattr(inp, "solver_time_limit", None)
	deadline = time.monotonic() + _ABLATION_BUDGET_S
	culprits: list = []
	trace: dict = {}
	untested: list = []
	try:
		if isinstance(orig_limit, (int, float)) and orig_limit > _ABLATION_SOLVE_CAP_S:
			inp.solver_time_limit = _ABLATION_SOLVE_CAP_S

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

		eff_rules = {
			r.rule_id: r for r in rs.effective()
			if r.kind == "hard" and r.rule_id not in _RELAXED_IN_DIAGNOSTIC
		}
		n_forbidden = sum(1 for r in eff_rules.values() if r.verb == "forbidden_at_slots")
		ordered = [rid for rid in _ABLATION_PRIORITY if rid in eff_rules]
		ordered += [rid for rid in eff_rules if rid not in ordered and rid not in _PHYSICAL_LAST]
		ordered += [rid for rid in _PHYSICAL_LAST if rid in eff_rules]

		families = []
		for rid in ordered:
			if _family_skippable(eff_rules[rid], inp, n_forbidden):
				trace[rid] = "SKIP (không có dữ liệu)"
				continue
			families.append(("rule", rid))
		families += [("system", f) for f in _SYSTEM_FAMILIES]

		# Vòng 1: tắt từng họ đơn lẻ.
		for kind, fam in families:
			if len(culprits) >= max_report:
				break
			if time.monotonic() > deadline:
				untested = [f for _, f in families if f not in trace]
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
		if not culprits and not untested:
			disabled_rules: set = set()
			skip_sys: set = set()
			for kind, fam in families:
				if time.monotonic() > deadline:
					break
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
		pending = sorted(set(untested) | set(unknown))
		if pending:
			labels = ", ".join(_FAMILY_LABELS.get(f, f) for f in pending[:5])
			suspects.append({
				"rule_id": "", "verb": "", "scope": {"inconclusive": pending},
				"message": (
					f"Chưa kết luận được cho các họ ràng buộc: {labels} "
					f"(hết ngân sách thời gian phân tích). Tăng thời gian solver rồi phân tích lại."
				),
			})
	return suspects, trace


def _data_contradictions(inp) -> list:
	"""Tiền-quét dữ liệu P0 (0 lần giải): pin bắt buộc đụng pin chặn / ngày cấm môn /
	GV bận / pin khác cùng slot. Trả list nghi phạm chỉ đích danh lớp/môn/slot."""
	from .helpers import class_subject_weekdays, teacher_class_subjects

	out = []
	cmap, smap, tmap, _rmap = _label_maps(inp)
	_c = lambda cid: cmap.get(cid, cid)  # noqa: E731
	_s = lambda sid: smap.get(sid, sid)  # noqa: E731
	_t = lambda tid: tmap.get(tid, tid)  # noqa: E731
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
					f"Pin bắt buộc lớp {_c(c_id)} môn {_s(ts_id)} vào {day}/tiết {p + 1} "
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
					f"Pin bắt buộc lớp {_c(c_id)} môn {_s(ts_id)} vào {day} nhưng môn này "
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
							f"Pin bắt buộc lớp {_c(c_id)} môn {_s(ts_id)} vào {day}/tiết {p + 1} "
							f"nhưng GV {_t(t_id)} bận (bắt buộc) đúng slot này."
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
					f"Hai pin bắt buộc đụng nhau: lớp {_c(c_id)} tại {day}/tiết {p + 1} "
					f"vừa pin môn {_s(seen[key])} vừa pin môn {_s(ts_id)}."
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


def _lb(row: dict, kind: str) -> str:
	"""Tên hiển thị của lớp/môn/GV/phòng trong 1 entry — rơi về ID nếu chưa gắn label."""
	return row.get(f"{kind}_label") or row.get(f"{kind}_id") or ""


def _summarize_suspects(report: dict) -> list:
	"""Nghi phạm cho khung "Điểm vướng" — CHỈ những loại DiagnoseCoverageCard không vẽ
	(shortfall/limit/force_pair/forbidden/pin đã có bảng cấu trúc riêng trong card,
	liệt kê lại ở đây chỉ gây trùng lặp)."""
	out = []
	# Thiếu phòng hợp lệ — gộp theo (lớp, môn) đếm số slot để báo cáo gọn.
	room_inelig_agg: dict = {}
	for ri in report.get("room_ineligible", []):
		key = (ri.get("class_id"), ri.get("subject_id"))
		room_inelig_agg[key] = room_inelig_agg.get(key, 0) + 1
	# Nhóm shortfall theo (lớp, môn) đã gộp ở trên; giữ label đầu tiên gặp được.
	inelig_labels: dict = {}
	for ri in report.get("room_ineligible", []):
		key = (ri.get("class_id"), ri.get("subject_id"))
		if key not in inelig_labels:
			inelig_labels[key] = (_lb(ri, "class"), _lb(ri, "subject"))
	for (class_id, subject_id), cnt in room_inelig_agg.items():
		c_lb, s_lb = inelig_labels.get((class_id, subject_id), (class_id, subject_id))
		out.append({
			"rule_id": "room_eligibility",
			"verb": "room_eligibility",
			"scope": {"class_id": class_id, "subject_id": subject_id},
			"message": (
				f"Lớp {c_lb} môn {s_lb}: không còn phòng hợp lệ trống ở {cnt} slot "
				f"(thiếu phòng hoặc đụng giới hạn room_max)"
			),
		})
	return out
