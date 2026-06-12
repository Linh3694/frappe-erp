"""Test phân tầng tier + coverage slack + per-slot enforcement (chạy dưới bench)."""

from core.coverage import build_coverage_report
from core.default_rules import STRONG_PREFERENCE_RULE_IDS, build_default_rule_set
from core.diagnostics import diagnose_infeasibility
from core.dto import RuleSet
from core.runner import build_and_solve
from core.tiers import STRONG_FACTOR, WEAK_FACTOR
from core.tests.fixtures import (
	ClassInfo, PeriodInfo, SubjectRequirement, TeacherInfo, TimetableInput, tiny_input,
)


def _oversub(enforcement="mandatory"):
	"""1 lớp, 2 tiết/ngày × 5 ngày = 10 slot; cần 8+8=16 -> thiếu 6 (coverage 62.5%)."""
	inp = TimetableInput(
		classes=[ClassInfo("C1", "Lớp 1", "G1", "R1")],
		periods=[PeriodInfo("P1", "Tiết 1", 1), PeriodInfo("P2", "Tiết 2", 2)],
		teachers={"T1": TeacherInfo("T1")},
		requirements=[
			SubjectRequirement("M1", "Toán", "C1", 8, max_periods_per_day=2, enforcement=enforcement),
			SubjectRequirement("M2", "Văn", "C1", 8, max_periods_per_day=2, enforcement=enforcement),
		],
		working_days=["mon", "tue", "wed", "thu", "fri"],
	)
	inp.class_subjects = {"C1": ["M1", "M2"]}
	inp.class_subject_teachers = {"C1|M1": ["T1"], "C1|M2": ["T1"]}
	inp.column_period_index = {"P1": 0, "P2": 1}
	return inp


def _tight(unavail):
	"""1 lớp, 1 tiết/ngày × 2 ngày = 2 slot; M1 cần 2 -> buộc dùng cả 2 slot."""
	inp = TimetableInput(
		classes=[ClassInfo("C1", "Lớp 1", "G1", "R1")],
		periods=[PeriodInfo("P1", "Tiết 1", 1)],
		teachers={"T1": TeacherInfo("T1", unavailable_slots=unavail)},
		requirements=[SubjectRequirement("M1", "Toán", "C1", 2, max_periods_per_day=1)],
		working_days=["mon", "tue"],
	)
	inp.class_subjects = {"C1": ["M1"]}
	inp.class_subject_teachers = {"C1|M1": ["T1"]}
	inp.column_period_index = {"P1": 0}
	return inp


def test_regression_mandatory_unchanged():
	"""Default mandatory = không sinh slack, hành vi cũ (8 slot, OPTIMAL)."""
	solver, builder, status, ctx = build_and_solve(tiny_input(), build_default_rule_set())
	assert status == "OPTIMAL"
	assert len(builder.extract_solution(solver)) == 8
	assert ctx.slacks == []
	assert ctx.objectives_by_tier["relaxable"] == []


def test_oversub_mandatory_infeasible():
	_, _, status, _ = build_and_solve(_oversub("mandatory"), build_default_rule_set())
	assert status == "INFEASIBLE"


def test_diagnostic_coverage_report():
	solver, builder, status, ctx = build_and_solve(
		_oversub("mandatory"), build_default_rule_set(), diagnostic=True
	)
	assert status in ("OPTIMAL", "FEASIBLE")
	rep = build_coverage_report(solver, ctx)
	assert rep["total_required"] == 16
	assert rep["total_short"] == 6
	assert rep["coverage_pct"] == 62.5
	assert len(rep["shortfalls"]) == 2


def test_per_cell_relaxable_no_diagnostic():
	solver, builder, status, ctx = build_and_solve(_oversub("relaxable"), build_default_rule_set())
	assert status in ("OPTIMAL", "FEASIBLE")
	rep = build_coverage_report(solver, ctx)
	assert rep["coverage_pct"] == 62.5


def test_diagnose_infeasibility_returns_report():
	rep = diagnose_infeasibility(_oversub("mandatory"), build_default_rule_set())
	assert rep["feasible_relaxed"] is True
	assert rep["coverage_pct"] == 62.5
	assert len(rep["suspects"]) >= 1
	# feasible input -> 100%, không suspects
	rep2 = diagnose_infeasibility(tiny_input(), build_default_rule_set())
	assert rep2["coverage_pct"] == 100.0
	assert rep2["suspects"] == []


def test_unavailability_relaxable_used_when_forced():
	solver, builder, status, ctx = build_and_solve(
		_tight([("mon", 0, "relaxable", 5)]), build_default_rule_set()
	)
	assert status in ("OPTIMAL", "FEASIBLE")
	assert len(builder.extract_solution(solver)) == 2
	rep = build_coverage_report(solver, ctx)
	assert any(f["day"] == "mon" for f in rep["forbidden_used"])


def test_unavailability_mandatory_blocks_hard():
	_, _, status, _ = build_and_solve(_tight([("mon", 0, "mandatory", 5)]), build_default_rule_set())
	assert status == "INFEASIBLE"
	# Legacy 2-tuple xử như mandatory
	_, _, status2, _ = build_and_solve(_tight([("mon", 0)]), build_default_rule_set())
	assert status2 == "INFEASIBLE"


def test_mandatory_slot_never_used_even_in_diagnostic():
	solver, builder, status, ctx = build_and_solve(
		_tight([("mon", 0, "mandatory", 5)]), build_default_rule_set(), diagnostic=True
	)
	assert status in ("OPTIMAL", "FEASIBLE")
	sol = builder.extract_solution(solver)
	assert all(s["day_of_week"] != "mon" for s in sol)
	rep = build_coverage_report(solver, ctx)
	assert rep["coverage_pct"] == 50.0


def test_default_preference_tiers():
	by_id = {r.rule_id: r for r in build_default_rule_set().rules}
	assert by_id["spread_subject_across_week"].tier == "strong"
	assert by_id["subject_preferred_periods"].tier == "strong"
	assert by_id["balance_workload_across_week"].tier == "weak"
	assert by_id["teacher_max_consecutive"].tier == "weak"
	assert STRONG_PREFERENCE_RULE_IDS  # không rỗng


def test_tier_override_via_session():
	rule = next(r for r in build_default_rule_set().rules if r.rule_id == "balance_workload_across_week")
	rs = RuleSet(name="t", rules=[rule], overrides={"balance_workload_across_week": {"tier": "strong"}})
	assert rs.effective()[0].tier == "strong"


def test_group_a_stays_hard_despite_override():
	rule = next(r for r in build_default_rule_set().rules if r.rule_id == "class_no_overlap")
	assert rule.kind == "hard" and rule.allow_kind_override is False
	rs = RuleSet(name="a", rules=[rule], overrides={"class_no_overlap": {"kind": "soft"}})
	assert rs.effective()[0].kind == "hard"


def test_strong_band_dominates_weak():
	from ortools.sat.python import cp_model
	m = cp_model.CpModel()
	a = m.NewBoolVar("a")
	bs = [m.NewBoolVar(f"b{i}") for i in range(2000)]
	for b in bs:
		m.Add(a + b <= 1)
	m.Maximize(STRONG_FACTOR * a + sum(WEAK_FACTOR * b for b in bs))
	solver = cp_model.CpSolver()
	solver.Solve(m)
	assert solver.Value(a) == 1


# ---- Phase 2 mở rộng: forbidden_on_day / pinned_to_slot / allow_only_at_slots ----

def _base(unavail=None, ppw=1):
	inp = TimetableInput(
		classes=[ClassInfo("C1", "Lớp 1", "G1", "R1")],
		periods=[PeriodInfo("P1", "Tiết 1", 1)],
		teachers={"T1": TeacherInfo("T1", unavailable_slots=unavail or [])},
		requirements=[SubjectRequirement("M1", "Toán", "C1", ppw, max_periods_per_day=1)],
		working_days=["mon", "tue"],
	)
	inp.class_subjects = {"C1": ["M1"]}
	inp.class_subject_teachers = {"C1|M1": ["T1"]}
	inp.column_period_index = {"P1": 0}
	return inp


def _rs_with(rule_id, params):
	rs = build_default_rule_set()
	for r in rs.rules:
		if r.rule_id == rule_id:
			r.params = params
	return rs


def test_forbidden_on_day_enforcement():
	inp = _base(ppw=2)
	rs = _rs_with("teacher_not_on_day", {"source": "instances", "instances": [
		{"subject": "T1", "object": {"day": "mon", "enforcement": "relaxable", "weight": 5}}]})
	solver, builder, status, ctx = build_and_solve(inp, rs)
	assert status in ("OPTIMAL", "FEASIBLE")
	assert any(f["day"] == "mon" for f in build_coverage_report(solver, ctx)["forbidden_used"])
	rs2 = _rs_with("teacher_not_on_day", {"source": "instances", "instances": [
		{"subject": "T1", "object": {"day": "mon", "enforcement": "mandatory"}}]})
	_, _, status2, _ = build_and_solve(inp, rs2)
	assert status2 == "INFEASIBLE"


def test_pinned_soft_vs_hard():
	inp = _base(unavail=[("mon", 0, "mandatory", 5)])
	rs = _rs_with("pin_class_subject_slot", {"instances": [
		{"subject": "C1", "object": {"subject_id": "M1", "day": "mon", "period_idx": 0,
		                             "enforcement": "relaxable", "weight": 5}}]})
	solver, builder, status, ctx = build_and_solve(inp, rs)
	assert status in ("OPTIMAL", "FEASIBLE")
	assert builder.extract_solution(solver)[0]["day_of_week"] == "tue"
	assert build_coverage_report(solver, ctx)["pins_missed"]
	rs2 = _rs_with("pin_class_subject_slot", {"instances": [
		{"subject": "C1", "object": {"subject_id": "M1", "day": "mon", "period_idx": 0,
		                             "enforcement": "mandatory"}}]})
	_, _, status2, _ = build_and_solve(inp, rs2)
	assert status2 == "INFEASIBLE"


def test_unsat_core_minimal():
	"""Pin mandatory ⟂ unavailability mandatory cùng slot -> core tối thiểu đúng 2 rule."""
	inp = _tight([("mon", 0, "mandatory", 5)])
	rs = build_default_rule_set()
	for r in rs.rules:
		if r.rule_id == "pin_class_subject_slot":
			r.params = {"instances": [
				{"subject": "C1", "object": {"subject_id": "M1", "day": "mon", "period_idx": 0,
				                             "enforcement": "mandatory"}}]}
	rep = diagnose_infeasibility(inp, rs)
	assert rep["feasible_relaxed"] is False
	core = set(rep["conflict_core"])
	assert "pin_class_subject_slot" in core
	assert "teacher_unavailable" in core
	assert "class_no_overlap" not in core  # tối thiểu


def test_allow_only_enforcement():
	from core.dto import Rule
	inp = _base(unavail=[("tue", 0, "mandatory", 5)])
	rs = build_default_rule_set()
	rs.rules.append(Rule(rule_id="allow_only_test", kind="hard", verb="allow_only_at_slots",
		subject_type="subject", params={"instances": [
			{"subject": "M1", "object": {"slots": [{"day": "tue", "period_idx": 0}],
			                             "enforcement": "relaxable", "weight": 5}}]}))
	solver, builder, status, ctx = build_and_solve(inp, rs)
	assert status in ("OPTIMAL", "FEASIBLE")
	assert builder.extract_solution(solver)[0]["day_of_week"] == "mon"
	assert build_coverage_report(solver, ctx)["forbidden_used"]
	for r in rs.rules:
		if r.rule_id == "allow_only_test":
			r.params["instances"][0]["object"]["enforcement"] = "mandatory"
	_, _, status2, _ = build_and_solve(inp, rs)
	assert status2 == "INFEASIBLE"
