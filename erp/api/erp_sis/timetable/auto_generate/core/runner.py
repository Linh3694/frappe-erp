"""Runner S+V+O — build model qua verb registry."""

from __future__ import annotations

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


def _apply_legacy_session_soft(ctx: SolverContext, objectives: list) -> None:
	"""Soft rules JSON cũ từ session (consecutive_bonus, pair exclusions...)."""
	inp = ctx.inp
	soft = inp.soft_rules
	req_map = {(r.education_grade_id, r.timetable_subject_id): r for r in inp.requirements}

	if soft.consecutive_bonus > 0:
		for c in inp.classes:
			g = c.education_grade_id
			for ts_id in inp.grade_subjects.get(g, []):
				req = req_map.get((g, ts_id))
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
							objectives.append(both * soft.consecutive_bonus)


def build_and_solve(inp: Any, rule_set: Optional[RuleSet] = None):
	"""Trả về (cp_solver, RuleSolverBuilder, status_name, ctx)."""
	from ortools.sat.python import cp_model

	rs = rule_set or build_default_rule_set()
	cp = cp_model.CpModel()
	ctx = SolverContext(model=cp, x={}, inp=inp)
	create_variables(ctx)

	resolver = SubjectResolver()
	objectives: list = []

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
			objectives.extend(verb.build_soft(ctx, subject_set, rule.params, rule.weight))

	# HC9 legacy: max tiết liên tiếp GV (hard) — chưa tách rule_id riêng trong default set
	from .verbs.max_consecutive import MaxConsecutive
	MaxConsecutive().apply_hard(ctx, list(inp.teachers.keys()), {"use_teacher_field": True})

	_apply_legacy_session_soft(ctx, objectives)

	if objectives:
		cp.Maximize(sum(objectives))

	solver = cp_model.CpSolver()
	solver.parameters.max_time_in_seconds = inp.solver_time_limit
	solver.parameters.num_workers = 4
	solver.parameters.log_search_progress = False
	status = solver.Solve(cp)
	builder = RuleSolverBuilder(ctx, inp)
	return solver, builder, solver.StatusName(status), ctx


def solve_with_rules(inp: Any, rule_set: Optional[RuleSet] = None):
	"""API tương thích solver.py cũ."""
	solver, builder, status_name, ctx = build_and_solve(inp, rule_set)
	_compat = _CompatModel(ctx, inp)
	return solver, builder, status_name, _compat
