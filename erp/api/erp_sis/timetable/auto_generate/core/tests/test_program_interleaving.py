"""Test rule mềm xen kẽ chương trình theo curriculum_id."""

from __future__ import annotations

from core.dto import Rule, RuleSet
from core.runner import build_and_solve
from core.tests.fixtures import SubjectRequirement, tiny_input


def _rules_with_program_soft() -> RuleSet:
	return RuleSet(
		name="test",
		rules=[
			Rule("curriculum_exact_periods", "hard", "exact_count_per_week", "assignment", {}, {}, 5),
			Rule("interleave_programs_within_day", "soft", "program_interleaving", "assignment", {}, {}, 8),
		],
	)


def test_program_interleaving_prefers_alternating_sequence():
	"""2 chương trình, 1 ngày 4 tiết: solver nên tránh xếp AA/BB liền kề."""
	inp = tiny_input()
	inp.working_days = ["mon"]
	inp.class_subjects = {"C1": ["M1", "M2"]}
	inp.class_subject_teachers = {"C1|M1": ["T1"], "C1|M2": ["T1"]}
	inp.requirements = [
		SubjectRequirement("M1", "Toán", "C1", 2, max_periods_per_day=2, program_id="P_VN"),
		SubjectRequirement("M2", "Science", "C1", 2, max_periods_per_day=2, program_id="P_INT"),
	]
	rs = _rules_with_program_soft()

	solver, builder, status, _ctx = build_and_solve(inp, rs)
	assert status in ("OPTIMAL", "FEASIBLE"), f"unexpected status {status}"
	solution = builder.extract_solution(solver)

	subject_program = {r.timetable_subject_id: r.program_id for r in inp.requirements}
	by_period = sorted(
		[
			(int(str(row["timetable_column_id"]).replace("P", "")), subject_program.get(row["timetable_subject_id"]))
			for row in solution
			if row["class_id"] == "C1" and row["day_of_week"] == "mon"
		],
		key=lambda x: x[0],
	)
	programs = [p for _, p in by_period if p]
	assert len(programs) == 4
	for i in range(len(programs) - 1):
		assert programs[i] != programs[i + 1], f"expected alternating programs, got {programs}"


def test_program_interleaving_no_effect_with_single_program():
	"""Nếu lớp chỉ có 1 chương trình thì rule mềm không làm bài toán infeasible."""
	inp = tiny_input()
	inp.working_days = ["mon"]
	inp.class_subjects = {"C1": ["M1"]}
	inp.class_subject_teachers = {"C1|M1": ["T1"]}
	inp.requirements = [
		SubjectRequirement("M1", "Toán", "C1", 4, max_periods_per_day=4, program_id="P_VN"),
	]
	rs = _rules_with_program_soft()

	_solver, _builder, status, _ctx = build_and_solve(inp, rs)
	assert status in ("OPTIMAL", "FEASIBLE")


def test_program_interleaving_compatible_with_force_pair():
	"""force_pair vẫn là hard, rule xen kẽ chỉ tối ưu trong phần tự do."""
	inp = tiny_input()
	inp.working_days = ["mon", "tue"]
	inp.class_subjects = {"C1": ["M1", "M2"]}
	inp.class_subject_teachers = {"C1|M1": ["T1"], "C1|M2": ["T1"]}
	inp.requirements = [
		SubjectRequirement("M1", "Toán", "C1", 4, max_periods_per_day=4, force_pair=True, program_id="P_VN"),
		SubjectRequirement("M2", "Science", "C1", 2, max_periods_per_day=2, program_id="P_INT"),
	]
	rs = _rules_with_program_soft()

	_solver, _builder, status, _ctx = build_and_solve(inp, rs)
	assert status in ("OPTIMAL", "FEASIBLE")
