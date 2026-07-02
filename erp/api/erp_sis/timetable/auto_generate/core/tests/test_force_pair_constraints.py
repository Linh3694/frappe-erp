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


def _pair_rs() -> RuleSet:
	return RuleSet(name="test", rules=[
		Rule("curriculum_exact_periods", "hard", "exact_count_per_week", "assignment", {}, {}, 5),
	])


def _fp_slacks(ctx):
	return [s for s in ctx.slacks if s.get("kind") == "force_pair_broken"]


def test_relaxable_pair_feasible_when_hard_would_break():
	"""4 tiết + chỉ 1 slot/buổi khả dụng mỗi ngày là không ghép nổi cặp; hard vô
	nghiệm nhưng relaxable phải ra nghiệm + slack force_pair_broken > 0."""
	inp = tiny_input()
	# 2 tiết/khung → mỗi buổi (nửa khung) chỉ 1 slot → không tồn tại cặp trong buổi.
	from core.tests.fixtures import PeriodInfo
	inp.periods = [PeriodInfo("P1", "Tiết 1", 1), PeriodInfo("P2", "Tiết 2", 2)]
	inp.column_period_index = {"P1": 0, "P2": 1}
	inp.requirements = [
		SubjectRequirement("M1", "Toán", "C1", 4, force_pair="hard"),
	]
	inp.class_subjects = {"C1": ["M1"]}
	inp.class_subject_teachers = {"C1|M1": ["T1"]}
	_s, _b, status_hard, _c = build_and_solve(inp, _pair_rs())
	assert status_hard == "INFEASIBLE"

	inp.requirements = [
		SubjectRequirement("M1", "Toán", "C1", 4, force_pair="relaxable"),
	]
	solver, _b2, status_relax, ctx = build_and_solve(inp, _pair_rs())
	assert status_relax in ("OPTIMAL", "FEASIBLE")
	slacks = _fp_slacks(ctx)
	assert slacks, "relaxable phải ghi violation force_pair_broken"
	assert sum(int(solver.Value(s["var"])) for s in slacks) > 0


def test_relaxable_pair_prefers_pairing_when_possible():
	"""Đủ chỗ ghép cặp → excess = 0 (không phá cặp vô cớ)."""
	inp = tiny_input()
	inp.requirements = [
		SubjectRequirement("M1", "Toán", "C1", 4, force_pair="relaxable"),
	]
	inp.class_subjects = {"C1": ["M1"]}
	inp.class_subject_teachers = {"C1|M1": ["T1"]}
	solver, _b, status, ctx = build_and_solve(inp, _pair_rs())
	assert status in ("OPTIMAL", "FEASIBLE")
	assert sum(int(solver.Value(s["var"])) for s in _fp_slacks(ctx)) == 0


def test_soft_pair_no_violation_entries():
	"""Cặp mềm là preference — ra nghiệm và KHÔNG ghi violation."""
	inp = tiny_input()
	inp.requirements = [
		SubjectRequirement("M1", "Toán", "C1", 4, force_pair="soft"),
	]
	inp.class_subjects = {"C1": ["M1"]}
	inp.class_subject_teachers = {"C1|M1": ["T1"]}
	_solver, _b, status, ctx = build_and_solve(inp, _pair_rs())
	assert status in ("OPTIMAL", "FEASIBLE")
	assert not _fp_slacks(ctx)


def test_legacy_bool_still_hard():
	"""force_pair=True (bool cũ) phải giữ nguyên hành vi cứng."""
	from core.tiers import normalize_fp_mode
	assert normalize_fp_mode(True) == "hard"
	assert normalize_fp_mode(False) == ""
	assert normalize_fp_mode("relaxable") == "relaxable"
	assert normalize_fp_mode("SOFT") == "soft"
	assert normalize_fp_mode("junk") == ""
