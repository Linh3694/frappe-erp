"""Runner S+V+O — build model qua verb registry."""

from __future__ import annotations

import math
from typing import Any, List, Optional, Tuple

from .context import SolverContext
from .default_rules import build_default_rule_set
from .dto import RuleSet
from .extract import extract_solution
from .registry import assert_compatible, get_verb
from .subject_resolver import SubjectResolver
from .tiers import STRONG_FACTOR, WEAK_FACTOR
from .variables import create_variables

# Import verbs để đăng ký registry
from . import verbs  # noqa: F401

AssignmentKey = Tuple[str, str, str, int]


class RuleSolverBuilder:
	"""Builder dựng model CP-SAT + trích lời giải cho solver."""

	def __init__(self, ctx: SolverContext, inp: Any):
		self.ctx = ctx
		self.inp = inp
		self.solver_model = _CompatModel(ctx, inp)

	def extract_solution(self, solver) -> List[dict]:
		return extract_solution(solver, self.ctx)


class _CompatModel:
	def __init__(self, ctx: SolverContext, inp: Any):
		self.model = ctx.model
		self.input = inp
		self.x = ctx.x


def _needs_room_vars(rule_set: RuleSet) -> bool:
	for rule in rule_set.effective():
		if rule.verb == "room_max_simultaneous" and rule.subject_type == "room":
			return True
		if rule.verb == "room_eligibility" and rule.subject_type == "assignment":
			return True
	return False


def _apply_forbid_solutions(ctx: SolverContext, forbid_solutions: List[List[AssignmentKey]], min_diff: int) -> None:
	if not forbid_solutions or min_diff <= 0:
		return
	for sol in forbid_solutions:
		same_vars = [ctx.x[k] for k in sol if k in ctx.x]
		if same_vars:
			ctx.model.Add(sum(same_vars) <= len(same_vars) - min_diff)


def _configure_and_solve(cp, inp):
	"""Cấu hình CpSolver theo input và chạy 1 pha. Trả về (solver, status)."""
	from ortools.sat.python import cp_model

	solver = cp_model.CpSolver()
	solver.parameters.max_time_in_seconds = inp.solver_time_limit
	solver.parameters.num_workers = 4
	solver.parameters.log_search_progress = False
	status = solver.Solve(cp)
	return solver, status


def build_and_solve(
	inp: Any,
	rule_set: Optional[RuleSet] = None,
	*,
	forbid_solutions: Optional[List[List[AssignmentKey]]] = None,
	min_diff: int = 0,
	objective_pin: Optional[int] = None,
	diagnostic: bool = False,
	assume_mode: bool = False,
	skip_system: Optional[frozenset] = None,
):
	"""Trả về (cp_solver, RuleSolverBuilder, status_name, ctx).

	diagnostic=True bật chế độ nới relaxable thành slack → solver luôn ra lời giải
	tốt nhất có thể; đọc ctx.slacks để dựng báo cáo "% đáp ứng / vô nghiệm ở đâu".

	assume_mode=True gắn assumption literal cho mỗi rule cứng còn lại rồi giải
	feasibility-only; nếu INFEASIBLE -> ctx.conflict_core = tập rule_id mâu thuẫn tối thiểu
	(UNSAT core). Thường đi kèm diagnostic=True để coverage không nằm trong core.
	"""
	from ortools.sat.python import cp_model

	rs = rule_set or build_default_rule_set()
	cp = cp_model.CpModel()
	ctx = SolverContext(
		model=cp, x={}, inp=inp, use_room_vars=_needs_room_vars(rs),
		diagnostic=diagnostic, assume_mode=assume_mode,
	)
	create_variables(ctx)

	resolver = SubjectResolver()

	for rule in rs.effective():
		try:
			assert_compatible(rule.verb, rule.subject_type)
			verb_cls = get_verb(rule.verb)
		except (KeyError, ValueError):
			continue

		subject_set = resolver.resolve(rule.subject_type, rule.subject_filter, inp)
		ctx.cur_subject_type = rule.subject_type
		ctx.cur_rule_id = rule.rule_id
		verb = verb_cls()

		if rule.kind == "hard":
			verb.apply_hard(ctx, subject_set, rule.params)
		else:
			# Soft route vào tầng strong/weak theo rule.tier (band áp dụng ở pha 2).
			for term in verb.build_soft(ctx, subject_set, rule.params, rule.weight):
				ctx.add_soft(rule.tier, term)

	# Các ràng buộc hệ thống (không có rule_id trong default set). skip_system cho phép
	# chẩn đoán ablation tắt riêng từng họ để khoanh nguồn gây vô nghiệm.
	skip = skip_system or frozenset()

	# HC9 legacy: max tiết liên tiếp GV (hard) — chưa tách rule_id riêng trong default set
	if "system_teacher_max_consecutive" not in skip:
		from .verbs.max_consecutive import MaxConsecutive
		ctx.cur_rule_id = "system_teacher_max_consecutive"
		MaxConsecutive().apply_hard(ctx, list(inp.teachers.keys()), {"use_teacher_field": True})

	# HC13: force_pair từ ma trận requirement (checkbox Cặp)
	if "system_force_pair" not in skip:
		from .force_pair_constraints import apply_requirement_force_pairs
		ctx.cur_rule_id = "system_force_pair"
		apply_requirement_force_pairs(ctx)

	# HC14: ràng buộc hệ thống — không môn nào quá 3 tiết liền trong ngày
	if "system_subject_consecutive_cap" not in skip:
		from .subject_consecutive_cap import apply_subject_max_consecutive_system_cap
		ctx.cur_rule_id = "system_subject_consecutive_cap"
		apply_subject_max_consecutive_system_cap(ctx, max_consecutive=3)
	ctx.cur_rule_id = ""

	_apply_forbid_solutions(ctx, forbid_solutions or [], min_diff)

	builder = RuleSolverBuilder(ctx, inp)

	# Assume pass (UNSAT core): giải feasibility-only với assumption literal trên rule cứng.
	if assume_mode:
		if ctx.assumptions:
			cp.AddAssumptions(list(ctx.assumptions.values()))
		solver, status = _configure_and_solve(cp, inp)
		if status == cp_model.INFEASIBLE:
			try:
				core_idx = set(solver.SufficientAssumptionsForInfeasibility())
				ctx.conflict_core = [
					rid for rid, lit in ctx.assumptions.items() if lit.Index() in core_idx
				]
			except Exception:
				ctx.conflict_core = []
		return solver, builder, solver.StatusName(status), ctx

	# Gom objective theo tầng. Flat ctx.objectives = soft "trung tính" (verb append
	# nội bộ); strong/weak nhân band ở pha 2; relaxable giải tách ở pha 1.
	relax_terms = ctx.objectives_by_tier["relaxable"]
	soft_terms = (
		list(ctx.objectives)
		+ [STRONG_FACTOR * t for t in ctx.objectives_by_tier["strong"]]
		+ [WEAK_FACTOR * t for t in ctx.objectives_by_tier["weak"]]
	)

	if relax_terms:
		# Hybrid 2 pha: pha 1 tối đa coverage/relaxable rồi pin, pha 2 tối ưu sở thích.
		relax_obj = sum(relax_terms)
		cp.Maximize(relax_obj)
		solver1, status1 = _configure_and_solve(cp, inp)
		if status1 not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
			# Vô nghiệm ngay cả khi đã nới relaxable — không cứu được.
			return solver1, builder, solver1.StatusName(status1), ctx
		cp.Add(relax_obj == int(round(solver1.ObjectiveValue())))
		if soft_terms:
			cp.Maximize(sum(soft_terms))
		solver, status = _configure_and_solve(cp, inp)
		return solver, builder, solver.StatusName(status), ctx

	# Đường thường: 1 pha như trước.
	if soft_terms:
		obj_expr = sum(soft_terms)
		if objective_pin is not None:
			cp.Add(obj_expr == objective_pin)
		cp.Maximize(obj_expr)
	solver, status = _configure_and_solve(cp, inp)
	return solver, builder, solver.StatusName(status), ctx


def solution_to_keys(solution: List[dict], inp: Any) -> List[AssignmentKey]:
	"""Chuyển solution dict -> keys (class, subject, day, period_idx) cho forbid constraint."""
	period_map = {}
	for i, p in enumerate(sorted(inp.periods, key=lambda x: x.period_priority)):
		period_map[p.name] = i
	keys = []
	for slot in solution:
		p_idx = period_map.get(slot["timetable_column_id"])
		if p_idx is None:
			continue
		keys.append((slot["class_id"], slot["timetable_subject_id"], slot["day_of_week"], p_idx))
	return keys


def build_and_solve_variants(
	inp: Any,
	rule_set: Optional[RuleSet] = None,
	k: int = 3,
	min_diff_ratio: float = 0.10,
) -> List[dict]:
	"""Sinh tối đa k nghiệm cùng objective, khác nhau >= min_diff_ratio * T tiết."""
	rs = rule_set or build_default_rule_set()
	found: List[dict] = []
	forbid: List[List[AssignmentKey]] = []
	objective_pin: Optional[int] = None
	min_diff = 0

	for _ in range(max(1, k)):
		solver, builder, status, _ctx = build_and_solve(
			inp,
			rs,
			forbid_solutions=forbid if forbid else None,
			min_diff=min_diff,
			objective_pin=objective_pin,
		)
		if status not in ("OPTIMAL", "FEASIBLE"):
			break
		solution = builder.extract_solution(solver)
		if not solution:
			break
		found.append({
			"solution": solution,
			"status": status,
			"objective_value": int(round(solver.ObjectiveValue())) if _ctx.objectives else 0,
		})
		if objective_pin is None and _ctx.objectives:
			objective_pin = int(round(solver.ObjectiveValue()))
		T = len(solution)
		min_diff = max(1, math.ceil(min_diff_ratio * T))
		forbid.append(solution_to_keys(solution, inp))
		if len(found) >= k:
			break

	return found


def solve_with_rules(inp: Any, rule_set: Optional[RuleSet] = None):
	"""API tương thích solver.py cũ."""
	solver, builder, status_name, ctx = build_and_solve(inp, rule_set)
	_compat = _CompatModel(ctx, inp)
	return solver, builder, status_name, _compat
