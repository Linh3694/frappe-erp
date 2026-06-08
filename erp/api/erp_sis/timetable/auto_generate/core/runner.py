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
from .variables import create_variables

# Import verbs để đăng ký registry
from . import verbs  # noqa: F401

AssignmentKey = Tuple[str, str, str, int]


class RuleSolverBuilder:
	"""Kết quả build tương thích ModelBuilder.extract_solution."""

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
		if rule.verb == "no_overlap" and rule.subject_type == "room":
			return True
		if rule.verb == "attribute_match" and (rule.params or {}).get("require") == "room_type==required":
			return True
	return False


def _apply_forbid_solutions(ctx: SolverContext, forbid_solutions: List[List[AssignmentKey]], min_diff: int) -> None:
	if not forbid_solutions or min_diff <= 0:
		return
	for sol in forbid_solutions:
		same_vars = [ctx.x[k] for k in sol if k in ctx.x]
		if same_vars:
			ctx.model.Add(sum(same_vars) <= len(same_vars) - min_diff)


def _apply_legacy_session_soft(ctx: SolverContext) -> None:
	"""Soft rules JSON cũ từ session (consecutive_bonus, pair exclusions...)."""
	inp = ctx.inp
	soft = inp.soft_rules
	req_map = {(r.class_id, r.timetable_subject_id): r for r in inp.requirements}

	if soft.consecutive_bonus > 0:
		for c in inp.classes:
			for ts_id in inp.class_subjects.get(c.name, []):
				req = req_map.get((c.name, ts_id))
				if not req or not req.prefer_consecutive:
					continue
				for day in inp.working_days:
					for p_idx in range(ctx.num_periods - 1):
						k1 = (c.name, ts_id, day, p_idx)
						k2 = (c.name, ts_id, day, p_idx + 1)
						if k1 in ctx.x and k2 in ctx.x:
							both = ctx.model.NewBoolVar(f"leg_consec_{c.name}_{ts_id}_{day}_{p_idx}")
							ctx.model.AddBoolAnd([ctx.x[k1], ctx.x[k2]]).OnlyEnforceIf(both)
							ctx.model.AddBoolOr([ctx.x[k1].Not(), ctx.x[k2].Not()]).OnlyEnforceIf(both.Not())
							ctx.objectives.append(both * soft.consecutive_bonus)


def build_and_solve(
	inp: Any,
	rule_set: Optional[RuleSet] = None,
	*,
	forbid_solutions: Optional[List[List[AssignmentKey]]] = None,
	min_diff: int = 0,
	objective_pin: Optional[int] = None,
):
	"""Trả về (cp_solver, RuleSolverBuilder, status_name, ctx)."""
	from ortools.sat.python import cp_model

	rs = rule_set or build_default_rule_set()
	cp = cp_model.CpModel()
	ctx = SolverContext(model=cp, x={}, inp=inp, use_room_vars=_needs_room_vars(rs))
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
		verb = verb_cls()

		if rule.kind == "hard":
			verb.apply_hard(ctx, subject_set, rule.params)
		else:
			ctx.objectives.extend(verb.build_soft(ctx, subject_set, rule.params, rule.weight))

	# HC9 legacy: max tiết liên tiếp GV (hard) — chưa tách rule_id riêng trong default set
	from .verbs.max_consecutive import MaxConsecutive
	MaxConsecutive().apply_hard(ctx, list(inp.teachers.keys()), {"use_teacher_field": True})

	_apply_legacy_session_soft(ctx)
	_apply_forbid_solutions(ctx, forbid_solutions or [], min_diff)

	if ctx.objectives:
		obj_expr = sum(ctx.objectives)
		if objective_pin is not None:
			cp.Add(obj_expr == objective_pin)
		cp.Maximize(obj_expr)

	solver = cp_model.CpSolver()
	solver.parameters.max_time_in_seconds = inp.solver_time_limit
	solver.parameters.num_workers = 4
	solver.parameters.log_search_progress = False
	status = solver.Solve(cp)
	builder = RuleSolverBuilder(ctx, inp)
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
