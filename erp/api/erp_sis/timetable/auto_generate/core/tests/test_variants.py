"""pytest — đa nghiệm build_and_solve_variants."""

from core.default_rules import build_default_rule_set
from core.runner import build_and_solve_variants, solution_to_keys
from core.tests.fixtures import tiny_input


def test_build_and_solve_variants_returns_at_least_one():
	inp = tiny_input()
	variants = build_and_solve_variants(inp, build_default_rule_set(), k=2, min_diff_ratio=0.1)
	assert len(variants) >= 1
	assert len(variants[0]["solution"]) == 8


def test_variants_differ_when_multiple_found():
	inp = tiny_input()
	variants = build_and_solve_variants(inp, build_default_rule_set(), k=3, min_diff_ratio=0.1)
	if len(variants) < 2:
		return
	keys0 = set(solution_to_keys(variants[0]["solution"], inp))
	keys1 = set(solution_to_keys(variants[1]["solution"], inp))
	assert keys0 != keys1
