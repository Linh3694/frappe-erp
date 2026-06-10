"""Test rule class_group_simultaneous_subject với mode sync/desync."""

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


def test_sync_group_same_subject_same_slot():
	"""Mode sync: Dance Sport của C1,C2 phải cùng slot."""
	inp = TimetableInput(
		classes=[
			ClassInfo("C1", "Lớp 1A", "G1", "R1"),
			ClassInfo("C2", "Lớp 2A", "G2", "R2"),
		],
		periods=[PeriodInfo(f"P{i}", f"Tiết {i}", i) for i in range(1, 5)],
		teachers={"T1": TeacherInfo("T1"), "T2": TeacherInfo("T2")},
		requirements=[
			SubjectRequirement("DS", "Dance Sport", "C1", 1, max_periods_per_day=1),
			SubjectRequirement("DS", "Dance Sport", "C2", 1, max_periods_per_day=1),
		],
		working_days=["mon"],
	)
	inp.class_subjects = {"C1": ["DS"], "C2": ["DS"]}
	inp.class_subject_teachers = {"C1|DS": ["T1"], "C2|DS": ["T2"]}
	inp.column_period_index = {f"P{i}": i - 1 for i in range(1, 5)}

	rule = Rule(
		rule_id="class_group_simultaneous_subject",
		kind="hard",
		verb="sync_class_group",
		subject_type="class",
		params={
			"instances": [{
				"subject": "C1",
				"object": {
					"mode": "sync",
					"timetable_subject_id": "DS",
					"class_ids": ["C1", "C2"],
				},
			}],
		},
	)

	rs = _minimal_rules(rule)
	solver, builder, status, _ctx = build_and_solve(inp, rs)
	assert status in ("OPTIMAL", "FEASIBLE"), f"unexpected status {status}"
	solution = builder.extract_solution(solver)

	ds_slots = {
		row["class_id"]: (row["day_of_week"], row.get("timetable_column_id"))
		for row in solution
		if row["timetable_subject_id"] == "DS"
	}
	assert ds_slots.get("C1") is not None and ds_slots.get("C2") is not None
	assert ds_slots["C1"] == ds_slots["C2"], f"DS phải cùng slot, nhận: {ds_slots}"


def test_desync_group_subjects_never_overlap():
	"""Mode desync: Dance Sport và Âm nhạc không trùng slot trên nhóm lớp đã chọn."""
	inp = TimetableInput(
		classes=[
			ClassInfo("C1", "Lớp 1A", "G1", "R1"),
			ClassInfo("C2", "Lớp 2A", "G2", "R2"),
		],
		periods=[PeriodInfo(f"P{i}", f"Tiết {i}", i) for i in range(1, 5)],
		teachers={
			"T1": TeacherInfo("T1"),
			"T2": TeacherInfo("T2"),
			"T3": TeacherInfo("T3"),
			"T4": TeacherInfo("T4"),
		},
		requirements=[
			SubjectRequirement("DS", "Dance Sport", "C1", 1, max_periods_per_day=1),
			SubjectRequirement("MU", "Âm nhạc", "C1", 1, max_periods_per_day=1),
			SubjectRequirement("DS", "Dance Sport", "C2", 1, max_periods_per_day=1),
			SubjectRequirement("MU", "Âm nhạc", "C2", 1, max_periods_per_day=1),
		],
		working_days=["mon"],
	)
	inp.class_subjects = {"C1": ["DS", "MU"], "C2": ["DS", "MU"]}
	inp.class_subject_teachers = {
		"C1|DS": ["T1"],
		"C1|MU": ["T2"],
		"C2|DS": ["T3"],
		"C2|MU": ["T4"],
	}
	inp.column_period_index = {f"P{i}": i - 1 for i in range(1, 5)}

	rule = Rule(
		rule_id="class_group_simultaneous_subject",
		kind="hard",
		verb="sync_class_group",
		subject_type="class",
		params={
			"instances": [{
				"subject": "C1",
				"object": {
					"mode": "desync",
					"timetable_subject_id": "DS",
					"target_timetable_subject_id": "MU",
					"class_ids": ["C1", "C2"],
				},
			}],
		},
	)

	rs = _minimal_rules(rule)
	solver, builder, status, _ctx = build_and_solve(inp, rs)
	assert status in ("OPTIMAL", "FEASIBLE"), f"unexpected status {status}"
	solution = builder.extract_solution(solver)

	ds_slots = {
		(row["day_of_week"], row.get("timetable_column_id"))
		for row in solution
		if row["class_id"] in {"C1", "C2"} and row["timetable_subject_id"] == "DS"
	}
	music_slots = {
		(row["day_of_week"], row.get("timetable_column_id"))
		for row in solution
		if row["class_id"] in {"C1", "C2"} and row["timetable_subject_id"] == "MU"
	}
	assert ds_slots, "DS phải được xếp ít nhất 1 slot"
	assert music_slots, "Âm nhạc phải được xếp ít nhất 1 slot"
	assert ds_slots.isdisjoint(music_slots), f"DS và Âm nhạc không được trùng slot: DS={ds_slots}, MU={music_slots}"
