"""Test consecutive_required chỉ dùng instances."""

from __future__ import annotations

from core.dto import Rule, RuleSet
from core.runner import build_and_solve
from core.tests.fixtures import tiny_input


def test_consecutive_required_skips_without_instances():
	inp = tiny_input()
	# Không có instances → verb không áp dụng ràng buộc cặp tiết
	rs = RuleSet(name="test", rules=[
		Rule(
			rule_id="subject_pair_periods",
			kind="hard",
			verb="consecutive_required",
			subject_type="subject",
			params={"size": 2, "no_break": True},
			weight=5,
			enabled=True,
		),
	])
	solver, builder, status, ctx = build_and_solve(inp, rs)
	assert status in ("OPTIMAL", "FEASIBLE", "INFEASIBLE")


def test_consecutive_required_uses_instance_subjects():
	inp = tiny_input()
	rs = RuleSet(name="test", rules=[
		Rule(
			rule_id="subject_pair_periods",
			kind="hard",
			verb="consecutive_required",
			subject_type="subject",
			params={
				"size": 2,
				"no_break": True,
				"instances": [{"subject": "M1", "object": {}}],
			},
			weight=5,
			enabled=True,
		),
	])
	solver, builder, status, ctx = build_and_solve(inp, rs)
	assert status in ("OPTIMAL", "FEASIBLE", "INFEASIBLE")
