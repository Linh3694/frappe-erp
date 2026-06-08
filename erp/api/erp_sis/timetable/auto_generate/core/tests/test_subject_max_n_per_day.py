"""Test mẫu S+O: Môn A max X tiết/ngày qua instances."""

from collections import defaultdict

from core.dto import Rule, RuleSet
from core.runner import build_and_solve
from core.tests.fixtures import ClassInfo, PeriodInfo, SubjectRequirement, TeacherInfo, TimetableInput


def _minimal_rules(extra: Rule) -> RuleSet:
	"""Rule set tối thiểu để solve tiny input + rule bổ sung."""
	return RuleSet(
		name="test",
		rules=[
			Rule("class_no_overlap", "hard", "no_overlap", "class", {}, {}, 5),
			Rule("teacher_no_overlap", "hard", "no_overlap", "teacher", {}, {}, 5),
			Rule("curriculum_exact_periods", "hard", "exact_count_per_week", "assignment", {}, {}, 5),
			extra,
		],
	)


def _count_per_day(solution, class_id: str, subject_id: str) -> dict:
	counts = defaultdict(int)
	for row in solution:
		if row["class_id"] == class_id and row["timetable_subject_id"] == subject_id:
			counts[row["day_of_week"]] += 1
	return dict(counts)


def test_subject_instance_max_per_day_enforced():
	"""Instance Toán max 1 tiết/ngày — không ngày nào vượt 1."""
	inp = TimetableInput(
		classes=[ClassInfo("C1", "Lớp 1", "G1", "R1")],
		periods=[PeriodInfo(f"P{i}", f"Tiết {i}", i) for i in range(1, 5)],
		teachers={"T1": TeacherInfo("T1")},
		requirements=[
			SubjectRequirement("M1", "Toán", "C1", 5, max_periods_per_day=3),
			SubjectRequirement("M2", "Văn", "C1", 3, max_periods_per_day=3),
		],
		working_days=["mon", "tue", "wed", "thu", "fri"],
	)
	inp.class_subjects = {"C1": ["M1", "M2"]}
	inp.class_subject_teachers = {"C1|M1": ["T1"], "C1|M2": ["T1"]}
	inp.column_period_index = {f"P{i}": i - 1 for i in range(1, 5)}

	rule = Rule(
		rule_id="subject_max_n_per_day",
		kind="hard",
		verb="at_most_per_scope",
		subject_type="subject",
		params={
			"scope": "day",
			"instances": [{"subject": "M1", "object": {"max": 1}}],
		},
	)
	rs = _minimal_rules(rule)
	solver, builder, status, _ctx = build_and_solve(inp, rs)
	assert status in ("OPTIMAL", "FEASIBLE"), f"unexpected status {status}"
	solution = builder.extract_solution(solver)
	counts = _count_per_day(solution, "C1", "M1")
	assert counts, "cần có slot Toán"
	assert all(v <= 1 for v in counts.values()), f"M1 vượt 1 tiết/ngày: {counts}"


def test_inst_object_int_reads_named_field():
	from core.helpers import inst_object_int

	assert inst_object_int({"object": {"max": 2}}, "max", 5) == 2
	assert inst_object_int({"object": {"value": 3}}, "max", 5) == 3  # legacy
	assert inst_object_int({"object": {}}, "max", 5) == 5
