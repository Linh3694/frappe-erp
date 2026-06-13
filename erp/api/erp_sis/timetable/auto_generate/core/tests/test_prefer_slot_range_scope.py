"""Test prefer_slot_range theo slot và phạm vi lớp/khối."""

from core.dto import Rule, RuleSet
from core.runner import build_and_solve
from core.tests.fixtures import ClassInfo, PeriodInfo, SubjectRequirement, TeacherInfo, TimetableInput


def _minimal_rules(extra_rules: list[Rule]) -> RuleSet:
	return RuleSet(
		name="test",
		rules=[
			Rule("class_no_overlap", "hard", "no_overlap", "class", {}, {}, 5),
			Rule("teacher_no_overlap", "hard", "no_overlap", "teacher", {}, {}, 5),
			Rule("curriculum_exact_periods", "hard", "exact_count_per_week", "assignment", {}, {}, 5),
			*extra_rules,
		],
	)


def test_preferred_slots_choose_specific_slot():
	"""Rule mềm theo slot: ưu tiên đúng slot được tick."""
	inp = TimetableInput(
		classes=[ClassInfo("C1", "Lớp 1A", "G1", "R1")],
		periods=[PeriodInfo("P1", "Tiết 1", 1), PeriodInfo("P2", "Tiết 2", 2)],
		teachers={"T1": TeacherInfo("T1")},
		requirements=[SubjectRequirement("M1", "Toán", "C1", 1, max_periods_per_day=1)],
		working_days=["mon"],
	)
	inp.class_subjects = {"C1": ["M1"]}
	inp.class_subject_teachers = {"C1|M1": ["T1"]}
	inp.column_period_index = {"P1": 0, "P2": 1}

	prefer_rule = Rule(
		rule_id="subject_preferred_periods",
		kind="soft",
		verb="prefer_slot_range",
		subject_type="subject",
		params={
			"source": "instances",
			"instances": [{
				"subject": "M1",
				"object": {"slots": [{"day": "mon", "period_idx": 1}]},
			}],
		},
		weight=8,
	)
	rs = _minimal_rules([prefer_rule])
	solver, builder, status, _ctx = build_and_solve(inp, rs)
	assert status in ("OPTIMAL", "FEASIBLE"), f"unexpected status {status}"
	solution = builder.extract_solution(solver)
	row = next(r for r in solution if r["class_id"] == "C1" and r["timetable_subject_id"] == "M1")
	assert row["day_of_week"] == "mon" and row.get("timetable_column_id") == "P2"


def test_preferred_slots_scope_only_target_class():
	"""Phạm vi class_ids: chỉ lớp mục tiêu bị ưu tiên slot."""
	inp = TimetableInput(
		classes=[
			ClassInfo("C1", "Lớp 1A", "G1", "R1"),
			ClassInfo("C2", "Lớp 2A", "G2", "R2"),
		],
		periods=[PeriodInfo("P1", "Tiết 1", 1), PeriodInfo("P2", "Tiết 2", 2)],
		teachers={"T1": TeacherInfo("T1"), "T2": TeacherInfo("T2")},
		requirements=[
			SubjectRequirement("M1", "Toán", "C1", 1, max_periods_per_day=1),
			SubjectRequirement("M1", "Toán", "C2", 1, max_periods_per_day=1),
		],
		working_days=["mon"],
	)
	inp.class_subjects = {"C1": ["M1"], "C2": ["M1"]}
	inp.class_subject_teachers = {"C1|M1": ["T1"], "C2|M1": ["T2"]}
	inp.column_period_index = {"P1": 0, "P2": 1}

	prefer_rule = Rule(
		rule_id="subject_preferred_periods",
		kind="soft",
		verb="prefer_slot_range",
		subject_type="subject",
		params={
			"source": "instances",
			"instances": [{
				"subject": "M1",
				"object": {
					"class_ids": ["C1"],
					"slots": [{"day": "mon", "period_idx": 1}],
				},
			}],
		},
		weight=8,
	)
	rs = _minimal_rules([prefer_rule])
	solver, builder, status, _ctx = build_and_solve(inp, rs)
	assert status in ("OPTIMAL", "FEASIBLE"), f"unexpected status {status}"
	solution = builder.extract_solution(solver)
	c1 = next(r for r in solution if r["class_id"] == "C1" and r["timetable_subject_id"] == "M1")
	assert c1["day_of_week"] == "mon" and c1.get("timetable_column_id") == "P2"


def test_legacy_periods_migrate_to_all_working_days_slots():
	"""Legacy periods được hiểu là slot của tất cả ngày làm việc."""
	inp = TimetableInput(
		classes=[ClassInfo("C1", "Lớp 1A", "G1", "R1")],
		periods=[PeriodInfo("P1", "Tiết 1", 1), PeriodInfo("P2", "Tiết 2", 2)],
		teachers={"T1": TeacherInfo("T1")},
		requirements=[SubjectRequirement("M1", "Toán", "C1", 1, max_periods_per_day=1)],
		working_days=["mon", "tue"],
	)
	inp.class_subjects = {"C1": ["M1"]}
	inp.class_subject_teachers = {"C1|M1": ["T1"]}
	inp.column_period_index = {"P1": 0, "P2": 1}

	prefer_rule = Rule(
		rule_id="subject_preferred_periods",
		kind="soft",
		verb="prefer_slot_range",
		subject_type="subject",
		params={
			"source": "instances",
			"instances": [{
				"subject": "M1",
				"object": {"periods": [0]},
			}],
		},
		weight=8,
	)
	forbid_rule = Rule(
		rule_id="subject_not_at_slot",
		kind="hard",
		verb="forbidden_at_slots",
		subject_type="subject",
		params={
			"source": "instances",
			"instances": [{
				"subject": "M1",
				"object": {
					"class_ids": ["C1"],
					"slots": [{"day": "mon", "period_idx": 0}],
				},
			}],
		},
	)

	rs = _minimal_rules([forbid_rule, prefer_rule])
	solver, builder, status, _ctx = build_and_solve(inp, rs)
	assert status in ("OPTIMAL", "FEASIBLE"), f"unexpected status {status}"
	solution = builder.extract_solution(solver)
	row = next(r for r in solution if r["class_id"] == "C1" and r["timetable_subject_id"] == "M1")
	assert row["day_of_week"] == "tue" and row.get("timetable_column_id") == "P1"
