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
	# Biến phòng quyết định (class, day, period_idx) -> IntVar; chỉ tạo khi bật rule room
	room: Dict[Tuple[str, str, int], Any] = field(default_factory=dict)
	use_room_vars: bool = False
	objectives: List[Any] = field(default_factory=list)
	cur_subject_type: str = ""
	cur_rule_id: str = ""
	# rule_id -> assumption lit (diagnostics)
	assumptions: Dict[str, Any] = field(default_factory=dict)
	# Phân tầng objective: relaxable (pha 1) + strong/weak (pha 2). Xem core/tiers.py.
	objectives_by_tier: Dict[str, List[Any]] = field(
		default_factory=lambda: {"relaxable": [], "strong": [], "weak": []}
	)
	# Registry vi phạm để báo cáo "vô nghiệm ở đâu / bao nhiêu %".
	slacks: List[dict] = field(default_factory=list)
	# Bật chế độ chẩn đoán (nới relaxable thành slack thay vì cứng).
	diagnostic: bool = False
	# Bật gắn assumption literal cho ràng buộc cứng (UNSAT core). Xem runner assume pass.
	assume_mode: bool = False
	# Kết quả UNSAT core: danh sách rule_id cứng mâu thuẫn tối thiểu.
	conflict_core: List[str] = field(default_factory=list)

	def assumption_lit(self, rule_id: str = ""):
		"""Get-or-create assumption literal cho 1 rule_id (dùng cho UNSAT core)."""
		rid = rule_id or self.cur_rule_id or "unknown"
		lit = self.assumptions.get(rid)
		if lit is None:
			lit = self.model.NewBoolVar(f"assume_{rid}")
			self.assumptions[rid] = lit
		return lit

	def add_hard(self, constraint):
		"""Đăng ký 1 ràng buộc cứng. Ở assume_mode, gắn assumption lit theo rule hiện tại
		để SufficientAssumptionsForInfeasibility lần ra tập rule cứng mâu thuẫn.

		Dùng: ctx.add_hard(ctx.model.Add(...)). Ở chế độ thường = passthrough, không đổi hành vi.
		"""
		if self.assume_mode and self.cur_rule_id and constraint is not None:
			try:
				constraint.OnlyEnforceIf(self.assumption_lit(self.cur_rule_id))
			except (AttributeError, TypeError):
				pass
		return constraint

	def add_soft(self, tier: str, term: Any) -> None:
		"""Đẩy 1 term (đã mang dấu theo quy ước Maximize) vào tầng tương ứng.

		tier ∈ {relaxable, strong, weak}; giá trị lạ rơi về 'weak'.
		"""
		bucket = self.objectives_by_tier.get(tier)
		if bucket is None:
			bucket = self.objectives_by_tier["weak"]
		bucket.append(term)

	def add_violation(self, rule_id: str, kind: str, scope: dict, slack_var: Any) -> None:
		"""Ghi 1 vi phạm relaxable vào registry để dựng báo cáo sau khi solve.

		kind: 'short' | 'over' | 'forbidden' | 'limit'.
		scope: định danh chỗ vi phạm (class/subject/teacher/day/period...).
		slack_var: biến đo độ vi phạm (đọc value sau solve).
		"""
		self.slacks.append({
			"rule_id": rule_id or self.cur_rule_id,
			"kind": kind,
			"scope": scope,
			"var": slack_var,
		})

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
		out = []
		for ts_id in self.inp.class_subjects.get(c_id, []):
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
