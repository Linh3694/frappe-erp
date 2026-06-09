"""Test ràng buộc hệ thống: không môn nào quá 3 tiết liền."""

from __future__ import annotations

from core.dto import Rule, RuleSet
from core.runner import build_and_solve
from core.tests.fixtures import SubjectRequirement, tiny_input


def _rules_exact_only() -> RuleSet:
	return RuleSet(
		name="test",
		rules=[
			Rule("curriculum_exact_periods", "hard", "exact_count_per_week", "assignment", {}, {}, 5),
		],
	)


def test_system_cap_blocks_four_consecutive_when_forced_same_day():
	"""Một môn 4 tiết/tuần trên 1 ngày duy nhất phải bị chặn bởi hard-cap 3 tiết liền."""
	inp = tiny_input()
	inp.working_days = ["mon"]
	inp.class_subjects = {"C1": ["M1"]}
	inp.class_subject_teachers = {"C1|M1": ["T1"]}
	inp.requirements = [
		SubjectRequirement("M1", "Toán", "C1", 4, max_periods_per_day=4),
	]
	rs = _rules_exact_only()

	_solver, _builder, status, _ctx = build_and_solve(inp, rs)
	assert status == "INFEASIBLE"


def test_system_cap_keeps_pair_rule_feasible():
	"""Giữ Cặp là hard: 4 tiết/tuần có thể tách thành 2 cặp trên 2 ngày, không vi phạm cap."""
	inp = tiny_input()
	inp.working_days = ["mon", "tue"]
	inp.class_subjects = {"C1": ["M1"]}
	inp.class_subject_teachers = {"C1|M1": ["T1"]}
	inp.requirements = [
		SubjectRequirement("M1", "Toán", "C1", 4, max_periods_per_day=4, force_pair=True),
	]
	rs = _rules_exact_only()

	_solver, _builder, status, _ctx = build_and_solve(inp, rs)
	assert status in ("OPTIMAL", "FEASIBLE")
