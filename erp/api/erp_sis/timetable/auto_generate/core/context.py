"""SolverContext — CP-SAT model + biến x + helper."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple


@dataclass
class SolverContext:
	model: Any
	x: Dict[Tuple[str, str, str, int], Any]
	inp: Any
	period_index_map: Dict[str, int] = field(default_factory=dict)
	room_index_map: Dict[str, int] = field(default_factory=dict)
	room_list: List[str] = field(default_factory=list)
	cur_subject_type: str = ""
	# rule_id -> assumption lit (diagnostics)
	assumptions: Dict[str, Any] = field(default_factory=dict)

	@property
	def num_periods(self) -> int:
		return len(self.inp.periods)

	@property
	def working_days(self) -> List[str]:
		return self.inp.working_days

	def vars_for_class_subject(self, c_id: str, ts_id: str) -> List[Any]:
		out = []
		for day in self.working_days:
			for p_idx in range(self.num_periods):
				v = self.x.get((c_id, ts_id, day, p_idx))
				if v is not None:
					out.append(v)
		return out

	def vars_for_class_slot(self, c_id: str, day: str, p_idx: int) -> List[Any]:
		grade = next((c.education_grade_id for c in self.inp.classes if c.name == c_id), None)
		if grade is None:
			return []
		out = []
		for ts_id in self.inp.grade_subjects.get(grade, []):
			v = self.x.get((c_id, ts_id, day, p_idx))
			if v is not None:
				out.append(v)
		return out

	def vars_for_teacher_slot(self, t_id: str, day: str, p_idx: int) -> List[Any]:
		from .helpers import teacher_class_subjects
		out = []
		for (c_id, ts_id) in teacher_class_subjects(self.inp).get(t_id, []):
			v = self.x.get((c_id, ts_id, day, p_idx))
			if v is not None:
				out.append(v)
		return out
