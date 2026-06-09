"""Test assignment_not_at_slot — cấm lớp+môn tại slot (theo lớp, không toàn trường)."""

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


def test_assignment_forbidden_slot_only_target_class():
	"""C1 cấm mon tiết 0 — C2 cùng môn vẫn xếp được tại slot đó."""
	inp = TimetableInput(
		classes=[
			ClassInfo("C1", "Lớp 1", "G1", "R1"),
			ClassInfo("C2", "Lớp 2", "G2", "R2"),
		],
		periods=[PeriodInfo(f"P{i}", f"Tiết {i}", i) for i in range(1, 5)],
		teachers={"T1": TeacherInfo("T1")},
		requirements=[
			SubjectRequirement("M1", "WB", "C1", 2, max_periods_per_day=2),
			SubjectRequirement("M1", "WB", "C2", 2, max_periods_per_day=2),
		],
		working_days=["mon", "tue", "wed"],
	)
	inp.class_subjects = {"C1": ["M1"], "C2": ["M1"]}
	inp.class_subject_teachers = {"C1|M1": ["T1"], "C2|M1": ["T1"]}
	inp.column_period_index = {f"P{i}": i - 1 for i in range(1, 5)}

	rule = Rule(
		rule_id="assignment_not_at_slot",
		kind="hard",
		verb="forbidden_at_slots",
		subject_type="assignment",
		params={
			"source": "instances",
			"instances": [{
				"subject": "C1",
				"object": {
					"subject_id": "M1",
					"slots": [{"day": "mon", "period_idx": 0}],
				},
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
				f"C1+M1 không được xếp mon tiết 1: {row}"
			)

	# C2 vẫn có thể xếp mon P1 nếu solver chọn
	c2_mon_p1 = any(
		row["class_id"] == "C2"
		and row["timetable_subject_id"] == "M1"
		and row["day_of_week"] == "mon"
		and row.get("timetable_column_id") == "P1"
		for row in solution
	)
	assert c2_mon_p1, "C2+M1 phải có thể xếp mon tiết 1 khi chỉ cấm C1"
