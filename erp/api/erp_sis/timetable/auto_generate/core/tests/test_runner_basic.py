"""pytest core — chạy từ thư mục auto_generate: python3 -m pytest -q"""

from core.default_rules import build_default_rule_set
from core.registry import list_verbs
from core.runner import build_and_solve
from core.tests.fixtures import tiny_input


def test_registry_has_19_verbs():
	verbs = list_verbs()
	assert len(verbs) >= 19


def test_default_rule_set_rules():
	rs = build_default_rule_set()
	ids = {r.rule_id for r in rs.rules}
	# Rule phòng đã bỏ
	assert "room_no_overlap" not in ids
	assert "room_type_match" not in ids
	assert "prefer_home_room" not in ids
	# Rule phòng còn lại (luôn bật)
	assert "room_max_simultaneous" in ids
	assert "room_eligibility" in ids
	assert len(rs.rules) == 23


def test_solve_tiny_input():
	inp = tiny_input()
	solver, builder, status, ctx = build_and_solve(inp, build_default_rule_set())
	assert status in ("OPTIMAL", "FEASIBLE", "INFEASIBLE")
	if status in ("OPTIMAL", "FEASIBLE"):
		solution = builder.extract_solution(solver)
		assert len(solution) == 8  # 4+4 tiết/tuần
