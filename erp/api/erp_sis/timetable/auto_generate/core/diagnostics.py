"""Phân tích INFEASIBLE — thử bỏ từng hard rule (không cần bench)."""

from __future__ import annotations

from typing import Any, List

from .dto import Rule, RuleSet
from .runner import build_and_solve


def diagnose_infeasibility(inp: Any, rule_set: RuleSet | None = None) -> List[dict]:
	from .default_rules import build_default_rule_set

	rs = rule_set or build_default_rule_set()
	hard = [r for r in rs.effective() if r.kind == "hard"]

	_, _, status_all, _ = build_and_solve(inp, rs)
	if status_all in ("OPTIMAL", "FEASIBLE"):
		return []

	suspects: List[dict] = []
	for skip in hard:
		remaining = [
			r for r in rs.rules
			if not (r.rule_id == skip.rule_id and r.kind == "hard")
		]
		# Giữ soft rules
		sub = RuleSet(name=rs.name, rules=remaining, overrides=rs.overrides)
		_, _, status, _ = build_and_solve(inp, sub)
		if status in ("OPTIMAL", "FEASIBLE"):
			suspects.append({
				"rule_id": skip.rule_id,
				"verb": skip.verb,
				"subject_type": skip.subject_type,
				"message": f"Bỏ rule '{skip.rule_id}' thì feasible — rule này có thể gây mâu thuẫn",
			})
	return suspects
