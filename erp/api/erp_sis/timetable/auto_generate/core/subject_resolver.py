"""Subject resolver — filter Simple (equality + IN)."""

from __future__ import annotations

from typing import Any, Dict, List


class SubjectResolver:
	def resolve(self, subject_type: str, filt: dict, inp) -> list:  # noqa: ANN001
		match subject_type:
			case "class":
				return [c for c in inp.classes if self._match_entity(c, filt, id_attr="name")]
			case "teacher":
				return [t for t in inp.teachers.values() if self._match_entity(t, filt, id_attr="name")]
			case "room":
				return [r for r in inp.rooms if self._match_entity(r, filt, id_attr="name")]
			case "subject":
				ids = set()
				for req in inp.requirements:
					if self._match_entity(req, filt, id_attr="timetable_subject_id"):
						ids.add(req.timetable_subject_id)
				return list(ids)
			case "assignment":
				return self._resolve_assignments(filt, inp)
			case "session_scope":
				return ["session"]
			case _:
				return []

	def _match_entity(self, entity: Any, filt: dict, id_attr: str) -> bool:
		if not filt:
			return True
		for key, val in filt.items():
			if key.endswith("_ids"):
				attr = key.replace("_ids", "_id")
				entity_val = getattr(entity, attr, None) or getattr(entity, key, None)
				if entity_val not in val:
					return False
			elif key == "force_pair":
				if bool(getattr(entity, "force_pair", False)) != bool(val):
					return False
			elif getattr(entity, key, None) != val:
				return False
		return True

	def _resolve_assignments(self, filt: dict, inp) -> List[tuple]:
		out = []
		for c in inp.classes:
			for ts_id in inp.class_subjects.get(c.name, []):
				item = (c.name, ts_id)
				if self._match_assignment(item, filt, inp):
					out.append(item)
		return out

	def _match_assignment(self, item: tuple, filt: dict, inp) -> bool:
		c_id, ts_id = item
		if "class_ids" in filt and c_id not in filt["class_ids"]:
			return False
		if "subject_ids" in filt and ts_id not in filt["subject_ids"]:
			return False
		return True
