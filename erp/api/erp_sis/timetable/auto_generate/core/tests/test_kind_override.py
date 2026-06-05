"""pytest — flip hard/soft qua le_limit và allow_kind_override."""

from core.default_rules import build_default_rule_set
from core.dto import Rule, RuleSet
from core.runner import build_and_solve
from core.tests.fixtures import ClassInfo, PeriodInfo, SubjectRequirement, TeacherInfo, TimetableInput


def _two_period_input():
	"""Input nhỏ: 1 lớp, 2 tiết/ngày, GV max 1 tiết/ngày — hard vs soft khác hành vi."""
	inp = TimetableInput(
		classes=[ClassInfo("C1", "Lớp 1", "G1")],
		periods=[PeriodInfo("P1", "Tiết 1", 1), PeriodInfo("P2", "Tiết 2", 2)],
		teachers={"T1": TeacherInfo("T1", max_periods_per_day=1)},
		requirements=[SubjectRequirement("M1", "Toán", "G1", 2), SubjectRequirement("M2", "Văn", "G1", 1)],
		working_days=["mon", "tue", "wed"],
		solver_time_limit=10,
	)
	inp.grade_subjects = {"G1": ["M1", "M2"]}
	inp.class_subject_teachers = {"C1|M1": ["T1"], "C1|M2": ["T1"]}
	inp.column_period_index = {"P1": 0, "P2": 1}
	return inp


def _minimal_rule_set(kind: str) -> RuleSet:
	return RuleSet(name="test", rules=[
		Rule(
			rule_id="curriculum_exact_periods",
			kind="hard",
			verb="exact_count_per_week",
			subject_type="assignment",
			enabled=True,
		),
		Rule(
			rule_id="class_no_overlap",
			kind="hard",
			verb="no_overlap",
			subject_type="class",
			enabled=True,
		),
		Rule(
			rule_id="teacher_max_periods_per_day",
			kind=kind,
			verb="at_most_per_scope",
			subject_type="teacher",
			params={"scope": "day", "source": "teacher.max_periods_per_day"},
			weight=10,
			allow_kind_override=True,
			enabled=True,
		),
	])


def test_teacher_max_hard_is_feasible_with_limit():
	inp = _two_period_input()
	solver, builder, status, _ = build_and_solve(inp, _minimal_rule_set("hard"))
	assert status in ("OPTIMAL", "FEASIBLE")
	sol = builder.extract_solution(solver)
	# Mỗi ngày GV tối đa 1 tiết
	by_day = {}
	for s in sol:
		by_day[s["day_of_week"]] = by_day.get(s["day_of_week"], 0) + 1
	assert all(v <= 1 for v in by_day.values())


def test_effective_respects_allow_kind_override_false():
	rs = RuleSet(
		name="t",
		rules=[Rule(
			rule_id="teacher_max_periods_per_day",
			kind="hard",
			verb="at_most_per_scope",
			subject_type="teacher",
			allow_kind_override=False,
			enabled=True,
		)],
		overrides={"teacher_max_periods_per_day": {"kind": "soft"}},
	)
	effective = rs.effective()
	assert effective[0].kind == "hard"
