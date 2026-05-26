"""Verb registry — plugin S+V+O."""

from __future__ import annotations

from typing import Callable, Dict, List, Set, Type

_VERBS: Dict[str, type] = {}
_VERB_COMPAT: Dict[str, Set[str]] = {}
_VERB_META: Dict[str, dict] = {}


def register_verb(verb_id: str, supports: List[str], *, kind: str = "hard", description: str = ""):
	def deco(cls: type) -> type:
		_VERBS[verb_id] = cls
		_VERB_COMPAT[verb_id] = set(supports)
		_VERB_META[verb_id] = {"kind": kind, "supports": supports, "description": description}
		cls.verb_id = verb_id
		return cls
	return deco


def get_verb(verb_id: str) -> type:
	if verb_id not in _VERBS:
		raise KeyError(f"Verb '{verb_id}' chưa đăng ký")
	return _VERBS[verb_id]


def list_verbs() -> List[dict]:
	from .verb_schemas import get_verb_schema

	out = []
	for verb_id in sorted(_VERBS):
		row = {"verb_id": verb_id, **_VERB_META[verb_id]}
		row.update(get_verb_schema(verb_id))
		out.append(row)
	return out


def assert_compatible(verb_id: str, subject_type: str) -> None:
	allowed = _VERB_COMPAT.get(verb_id, set())
	if subject_type not in allowed:
		raise ValueError(f"Verb '{verb_id}' không hỗ trợ subject_type '{subject_type}'")


class Verb:
	verb_id: str = ""
	kind: str = "hard"

	def apply_hard(self, ctx, subject_set, params):  # noqa: ANN001
		pass

	def build_soft(self, ctx, subject_set, params, weight: int):  # noqa: ANN001
		return []
