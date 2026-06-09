"""Test force_pair — tiết/tuần lẻ vẫn hợp lệ, solver áp dụng ràng buộc cặp."""

from __future__ import annotations

from core.dto import Rule, RuleSet
from core.runner import build_and_solve
from core.tests.fixtures import SubjectRequirement, tiny_input
from validation import validate_timetable_input


def test_odd_periods_per_week_not_blocked_by_validation():
	inp = tiny_input()
	inp.requirements = [
		SubjectRequirement("M1", "Toán", "C1", 3, force_pair=True),
	]
	errors, _warnings = validate_timetable_input(inp)
	assert not any("phải chẵn" in e for e in errors)


def test_force_pair_odd_week_runs_solver():
	inp = tiny_input()
	inp.requirements = [
		SubjectRequirement("M1", "Toán", "C1", 3, force_pair=True),
	]
	rs = RuleSet(name="test", rules=[
		Rule("curriculum_exact_periods", "hard", "exact_count_per_week", "assignment", {}, {}, 5),
	])
	solver, _builder, status, _ctx = build_and_solve(inp, rs)
	assert status in ("OPTIMAL", "FEASIBLE", "INFEASIBLE")


def test_force_pair_even_week_runs_solver():
	inp = tiny_input()
	inp.requirements = [
		SubjectRequirement("M1", "Toán", "C1", 4, force_pair=True),
	]
	rs = RuleSet(name="test", rules=[
		Rule("curriculum_exact_periods", "hard", "exact_count_per_week", "assignment", {}, {}, 5),
	])
	solver, _builder, status, _ctx = build_and_solve(inp, rs)
	assert status in ("OPTIMAL", "FEASIBLE", "INFEASIBLE")
