"""DTO cho solver core — không import frappe."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional


@dataclass
class Rule:
	rule_id: str
	kind: Literal["hard", "soft"]
	verb: str
	subject_type: str
	subject_filter: dict = field(default_factory=dict)
	params: dict = field(default_factory=dict)
	weight: int = 5
	# Tầng mềm khi kind == 'soft': 'strong' (khó thương lượng) | 'weak' (dễ). Xem core/tiers.py.
	tier: str = "weak"
	enabled: bool = True
	allow_kind_override: bool = False
	description: str = ""


@dataclass
class RuleSet:
	name: str
	rules: List[Rule] = field(default_factory=list)
	overrides: Dict[str, dict] = field(default_factory=dict)

	def effective(self) -> List[Rule]:
		"""Áp override session, lọc enabled."""
		out: List[Rule] = []
		for rule in self.rules:
			if not rule.enabled:
				continue
			ov = self.overrides.get(rule.rule_id) or {}
			if ov.get("enabled") is False:
				continue
			kind = rule.kind
			if ov.get("kind") in ("hard", "soft") and rule.allow_kind_override:
				kind = ov["kind"]
			weight = int(ov.get("weight", rule.weight))
			tier = ov.get("tier") if ov.get("tier") in ("strong", "weak") else rule.tier
			out.append(Rule(
				rule_id=rule.rule_id,
				kind=kind,
				verb=rule.verb,
				subject_type=rule.subject_type,
				subject_filter=dict(rule.subject_filter),
				params=dict(rule.params),
				weight=weight,
				tier=tier,
				enabled=True,
				allow_kind_override=rule.allow_kind_override,
				description=rule.description,
			))
		return out


@dataclass
class SolverOutputMeta:
	status: str = ""
	num_variables: int = 0
	num_constraints: int = 0
	solve_time_ms: float = 0
