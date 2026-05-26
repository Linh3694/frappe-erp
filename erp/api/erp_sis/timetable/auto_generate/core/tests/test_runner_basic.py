"""pytest core — chạy từ thư mục auto_generate: python3 -m pytest -q"""

from core.default_rules import build_default_rule_set
from core.registry import list_verbs
from core.runner import build_and_solve
from core.tests.fixtures import tiny_input


def test_registry_has_19_verbs():
	verbs = list_verbs()
	assert len(verbs) >= 19


def test_default_rule_set_has_27_rules():
	rs = build_default_rule_set()
	assert len(rs.rules) == 27


def test_solve_tiny_input():
	inp = tiny_input()
	solver, builder, status, ctx = build_and_solve(inp, build_default_rule_set())
	assert status in ("OPTIMAL", "FEASIBLE", "INFEASIBLE")
	if status in ("OPTIMAL", "FEASIBLE"):
		solution = builder.extract_solution(solver)
		assert len(solution) == 8  # 4+4 tiết/tuần
