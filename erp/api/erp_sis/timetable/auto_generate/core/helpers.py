"""Helper dùng chung cho verbs — không import frappe."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .tiers import RELAX_FORBIDDEN_PENALTY, RELAXABLE, STRONG, normalize_enforcement


def req_map(inp: Any) -> Dict[Tuple[str, str], Any]:
	return {(r.class_id, r.timetable_subject_id): r for r in inp.requirements}


def teacher_class_subjects(inp: Any) -> Dict[str, List[Tuple[str, str]]]:
	out: Dict[str, List[Tuple[str, str]]] = {}
	for c in inp.classes:
		for ts_id in inp.class_subjects.get(c.name, []):
			key_a = f"{c.name}|{ts_id}"
			for t_id in inp.class_subject_teachers.get(key_a, []):
				out.setdefault(t_id, []).append((c.name, ts_id))
	return out


def class_subject_weekdays(inp: Any) -> Dict[Tuple[str, str], set]:
	out: Dict[Tuple[str, str], set] = {}
	for a in inp.assignments:
		key = (a.class_id, a.timetable_subject_id)
		allowed = set(a.weekdays) if a.weekdays else set(inp.working_days)
		if key not in out:
			out[key] = set()
		out[key].update(allowed)
	return out


def num_periods(inp: Any) -> int:
	return len(inp.periods)


def sorted_periods(inp: Any):
	return sorted(inp.periods, key=lambda x: x.period_priority)


def instances(params: dict) -> list:
	return params.get("instances") or []


def resolve_target_class_ids(inp: Any, obj: dict) -> set[str]:
	"""Lọc lớp áp dụng theo class_ids/grade_ids; rỗng = áp dụng mọi lớp có môn."""
	class_ids = obj.get("class_ids") or []
	if not isinstance(class_ids, list):
		class_ids = []
	target_class_ids = {str(c).strip() for c in class_ids if c}

	grade_ids = obj.get("grade_ids") or []
	if not isinstance(grade_ids, list):
		grade_ids = []
	target_grade_ids = {str(g).strip() for g in grade_ids if g}

	if target_grade_ids:
		for c in inp.classes:
			class_id = c.name if hasattr(c, "name") else c
			grade_id = getattr(c, "education_grade_id", None)
			if grade_id in target_grade_ids:
				target_class_ids.add(class_id)

	return target_class_ids


def inst_object_int(inst: dict, field: str, default: int) -> int:
	"""Đọc số từ instances[].object[field]; fallback legacy object.value."""
	obj = inst.get("object") or {}
	if field in obj and obj[field] is not None:
		return int(obj[field])
	if "value" in obj and obj["value"] is not None:
		return int(obj["value"])
	return int(default)


def resolve_room_id(inp: Any, class_info, ts_id: str, rmap) -> str:
	"""Fallback phòng khi không dùng room_var — trả phòng chủ nhiệm của lớp.

	Ràng buộc phòng theo môn nay do rule room_eligibility xử lý qua room_var.
	"""
	return class_info.room_id or ""


def forbid_var(ctx, v, *, enforcement: str, weight: int, rule_id: str, scope: dict) -> None:
	"""Cấm 1 biến xếp tại slot (v == 0) với per-instance enforcement.

	mandatory -> ràng buộc cứng. relaxable -> phạt nếu vẫn buộc xếp (tầng strong),
	ghi ctx.slacks (kind='forbidden') để báo cáo "vô nghiệm ở đâu".
	"""
	if v is None:
		return
	if normalize_enforcement(enforcement) == "relaxable":
		ctx.add_soft(STRONG, v * (-weight))
		ctx.add_violation(rule_id or ctx.cur_rule_id, "forbidden", scope, v)
	else:
		ctx.add_hard(ctx.model.Add(v == 0))


def pin_var(ctx, v, *, enforcement: str, weight: int, rule_id: str, scope: dict, tag: str) -> bool:
	"""Pin 1 biến vào slot (v == 1) với per-instance enforcement.

	mandatory -> cứng, trả True (caller ép các môn khác rời slot).
	relaxable (pin mềm) -> thưởng nếu đặt đúng; ghi 'pin_missed' khi trượt; trả False.
	"""
	if v is None:
		return False
	if normalize_enforcement(enforcement) == "relaxable":
		missed = ctx.model.NewBoolVar(f"pin_miss_{tag}")
		ctx.model.Add(v + missed == 1)
		ctx.add_soft(STRONG, missed * (-weight))
		ctx.add_violation(rule_id or ctx.cur_rule_id, "pin_missed", scope, missed)
		return False
	ctx.add_hard(ctx.model.Add(v == 1))
	return True


def le_limit(
	ctx, vars_, limit: int, *, kind: str, weight: int, tag: str,
	rule_id: str = "", relaxable: bool = False, tier: str = "",
	scope: dict | None = None,
) -> None:
	"""Ràng buộc sum(vars_) <= limit.

	- hard          -> constraint cứng.
	- soft          -> phạt phần vượt theo weight (Maximize, tầng flat như cũ).
	- hard + relaxable + ctx.diagnostic -> nới thành slack phần vượt ở tầng RELAXABLE,
	  ghi vào ctx.slacks để báo cáo. Dùng cho limit chính sách (teacher/subject/consecutive);
	  KHÔNG truyền relaxable cho limit vật lý (room capacity).
	- scope: định danh có cấu trúc (class_id/subject_id/teacher_id/room_id/day...) để
	  báo cáo hiện tên thay vì bắt UI parse tag kỹ thuật.
	"""
	if not vars_:
		return
	relax = relaxable and getattr(ctx, "diagnostic", False)
	if kind == "hard" and not relax:
		ctx.add_hard(ctx.model.Add(sum(vars_) <= limit))
		return
	over = ctx.model.NewIntVar(0, len(vars_), f"over_{tag}")
	ctx.model.Add(over >= sum(vars_) - limit)
	if kind == "hard":
		# Hard policy đang nới (diagnostic): tầng relaxable, phạt nặng, ghi báo cáo.
		ctx.add_soft(RELAXABLE, over * (-RELAX_FORBIDDEN_PENALTY))
		ctx.add_violation(
			rule_id or ctx.cur_rule_id, "limit",
			{**(scope or {}), "tag": tag, "limit": limit}, over,
		)
	elif tier:
		# Soft có tier per-entity (vd max liên tiếp theo từng GV).
		ctx.add_soft(tier, over * (-weight))
	else:
		ctx.objectives.append(over * (-weight))
