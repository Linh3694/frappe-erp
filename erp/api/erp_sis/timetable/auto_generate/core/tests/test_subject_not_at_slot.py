"""Test subject_not_at_slot — môn không xếp tại slot cấm."""

from core.dto import Rule, RuleSet
from core.runner import build_and_solve
from core.tests.fixtures import ClassInfo, PeriodInfo, SubjectRequirement, TeacherInfo, TimetableInput


def _minimal_rules(extra: Rule) -> RuleSet:
	return RuleSet(
		name="test",
		rules=[
			Rule("class_no_overlap", "hard", "no_overlap", "class", {}, {}, 5),
			Rule("teacher_no_overlap", "hard", "no_overlap", "teacher", {}, {}, 5),
			Rule("curriculum_exact_periods", "hard", "exact_count_per_week", "assignment", {}, {}, 5),
			extra,
		],
	)


def test_subject_forbidden_slot_not_scheduled():
	"""M1 cấm slot mon tiết 0 — solution không có M1 tại slot đó."""
	inp = TimetableInput(
		classes=[ClassInfo("C1", "Lớp 1", "G1", "R1")],
		periods=[PeriodInfo(f"P{i}", f"Tiết {i}", i) for i in range(1, 5)],
		teachers={"T1": TeacherInfo("T1")},
		requirements=[
			SubjectRequirement("M1", "Toán", "C1", 3, max_periods_per_day=3),
			SubjectRequirement("M2", "Văn", "C1", 3, max_periods_per_day=3),
		],
		working_days=["mon", "tue", "wed"],
	)
	inp.class_subjects = {"C1": ["M1", "M2"]}
	inp.class_subject_teachers = {"C1|M1": ["T1"], "C1|M2": ["T1"]}
	inp.column_period_index = {f"P{i}": i - 1 for i in range(1, 5)}

	rule = Rule(
		rule_id="subject_not_at_slot",
		kind="hard",
		verb="forbidden_at_slots",
		subject_type="subject",
		params={
			"source": "instances",
			"instances": [{
				"subject": "M1",
				"object": {"slots": [{"day": "mon", "period_idx": 0}]},
			}],
		},
	)
	rs = _minimal_rules(rule)
	solver, builder, status, _ctx = build_and_solve(inp, rs)
	assert status in ("OPTIMAL", "FEASIBLE"), f"unexpected status {status}"
	solution = builder.extract_solution(solver)
	for row in solution:
		if row["class_id"] == "C1" and row["timetable_subject_id"] == "M1":
			assert not (row["day_of_week"] == "mon" and row.get("timetable_column_id") == "P1"), (
				f"M1 không được xếp mon tiết 1 (P1): {row}"
			)
