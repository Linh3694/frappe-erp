"""pytest — helper primitive le_limit."""

from ortools.sat.python import cp_model

from core.context import SolverContext
from core.helpers import le_limit
from core.tests.fixtures import tiny_input


def test_le_limit_hard_adds_constraint():
	inp = tiny_input()
	cp = cp_model.CpModel()
	ctx = SolverContext(model=cp, x={}, inp=inp)
	a = cp.NewBoolVar("a")
	b = cp.NewBoolVar("b")
	le_limit(ctx, [a, b], 1, kind="hard", weight=5, tag="t1")
	solver = cp_model.CpSolver()
	cp.Add(a + b >= 1)
	status = solver.Solve(cp)
	assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
	assert solver.Value(a) + solver.Value(b) <= 1


def test_le_limit_soft_penalizes_overflow():
	inp = tiny_input()
	cp = cp_model.CpModel()
	ctx = SolverContext(model=cp, x={}, inp=inp, objectives=[])
	a = cp.NewBoolVar("a")
	b = cp.NewBoolVar("b")
	le_limit(ctx, [a, b], 1, kind="soft", weight=10, tag="t2")
	cp.Maximize(sum(ctx.objectives))
	cp.Add(a == 1)
	cp.Add(b == 1)
	solver = cp_model.CpSolver()
	solver.Solve(cp)
	assert len(ctx.objectives) == 1
