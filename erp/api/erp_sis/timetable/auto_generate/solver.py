"""
Solver - Chạy CP-SAT solver và xử lý kết quả.

Lưu kết quả vào tabSIS_TKB_Gen_Result (raw SQL, cách ly hoàn toàn).
"""

import json
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime

import frappe

from .data_collector import TimetableDataCollector, TimetableInput
from .validation import validate_timetable_input


@dataclass
class SolverResult:
	success: bool = False
	status: str = ""  # OPTIMAL, FEASIBLE, INFEASIBLE, etc.
	num_variables: int = 0
	num_constraints: int = 0
	solve_time_ms: float = 0
	total_slots: int = 0
	total_classes: int = 0
	variant_count: int = 0
	warnings: List[str] = field(default_factory=list)
	errors: List[str] = field(default_factory=list)
	suspects: List[Dict] = field(default_factory=list)


class TimetableSolver:
	"""Chạy solver cho 1 session."""

	def __init__(self, session_id: str):
		self.session_id = session_id

	def _load_rule_set(self):
		from .rule_loader import load_rule_set
		from .core.default_rules import build_default_rule_set

		session = frappe.get_doc("SIS Timetable Generation Session", self.session_id)
		rule_set = None
		if getattr(session, "rule_set_id", None):
			try:
				rule_set = load_rule_set(session.rule_set_id, session.rule_overrides)
			except Exception:
				rule_set = None
		if rule_set is None:
			rule_set = build_default_rule_set("default")
		return rule_set, session

	def _prepare_input(self) -> tuple:
		collector = TimetableDataCollector(self.session_id)
		inp = collector.collect()
		val_errors, val_warnings = validate_timetable_input(inp)
		return inp, val_errors, val_warnings

	def solve(self) -> SolverResult:
		result = SolverResult()

		try:
			inp, val_errors, val_warnings = self._prepare_input()
			result.warnings = val_warnings
			if val_errors:
				result.errors.extend(val_errors)
				return result

			if not inp.classes:
				result.errors.append("Không tìm thấy lớp nào trong phạm vi đã chọn")
				return result

			if not inp.periods:
				result.errors.append("Không tìm thấy tiết học nào trong schedule đã chọn")
				return result

			if not inp.requirements:
				result.errors.append("Chưa có yêu cầu số tiết/tuần nào (Requirements matrix trống)")
				return result

			from .core.runner import solve_with_rules

			rule_set, session = self._load_rule_set()
			solver, builder, status_name, solver_model = solve_with_rules(inp, rule_set)

			frappe.logger().info(
				f"[Solver] {len(inp.classes)} lớp, {len(inp.periods)} tiết/ngày, "
				f"{len(inp.working_days)} ngày, rule_set={getattr(session, 'rule_set_id', None)}"
			)

			result.num_variables = solver_model.model.Proto().variables.__len__() if hasattr(solver_model, "model") else 0
			result.num_constraints = solver_model.model.Proto().constraints.__len__() if hasattr(solver_model, "model") else 0
			result.solve_time_ms = solver.WallTime() * 1000
			result.status = status_name

			if status_name in ("OPTIMAL", "FEASIBLE"):
				result.success = True
				solution = builder.extract_solution(solver)
				result.total_slots = len(solution)
				result.total_classes = len(set(s["class_id"] for s in solution))
				result.variant_count = 1
				self._save_results([(0, solution)])

				if status_name == "FEASIBLE":
					result.warnings.append(
						"Solver tìm được lời giải khả thi nhưng chưa tối ưu "
						"(hết thời gian trước khi tìm được lời giải tốt nhất)"
					)
			else:
				result.errors.append(f"Solver không tìm được lời giải: {status_name}")
				if status_name == "INFEASIBLE":
					result.errors.append(
						"Các ràng buộc mâu thuẫn nhau. Kiểm tra: "
						"(1) Tổng số tiết yêu cầu có vượt số slot/tuần? "
						"(2) Có đủ GV cho tất cả lớp-môn? "
						"(3) GV có bị giới hạn quá chặt (max_periods_per_day)?"
					)
					try:
						from .core.diagnostics import diagnose_infeasibility

						result.suspects = diagnose_infeasibility(inp, rule_set)
						if result.suspects:
							ids = [s["rule_id"] for s in result.suspects[:5]]
							result.errors.append(f"Nghi phạm: {', '.join(ids)}")
					except Exception as diag_err:
						frappe.logger().warning(
							f"[Solver] diagnose_infeasibility failed for {self.session_id}: {diag_err}"
						)

		except Exception as e:
			result.errors.append(f"Lỗi hệ thống: {str(e)}")
			frappe.log_error(f"Timetable solver error for session {self.session_id}: {str(e)}")

		return result

	def solve_variants(self, k: int = 3, min_diff_ratio: float = 0.10) -> SolverResult:
		"""Sinh tối đa k biến thể cùng objective (draft sandbox, chưa publish)."""
		result = SolverResult()

		try:
			inp, val_errors, val_warnings = self._prepare_input()
			result.warnings = val_warnings
			if val_errors:
				result.errors.extend(val_errors)
				return result

			from .core.runner import build_and_solve_variants

			rule_set, _session = self._load_rule_set()
			variants = build_and_solve_variants(inp, rule_set, k=k, min_diff_ratio=min_diff_ratio)

			if not variants:
				result.errors.append("Không sinh được biến thể nào")
				result.status = "INFEASIBLE"
				return result

			pairs = [(i, v["solution"]) for i, v in enumerate(variants)]
			self._save_results(pairs)
			result.success = True
			result.status = variants[0]["status"]
			result.variant_count = len(variants)
			result.total_slots = len(variants[0]["solution"])
			result.total_classes = len(set(s["class_id"] for s in variants[0]["solution"]))

		except Exception as e:
			result.errors.append(f"Lỗi hệ thống: {str(e)}")
			frappe.log_error(f"Timetable variant solver error for session {self.session_id}: {str(e)}")

		return result

	def _has_variant_index_column(self) -> bool:
		try:
			cols = frappe.db.sql("SHOW COLUMNS FROM `tabSIS_TKB_Gen_Result` LIKE 'variant_index'")
			return bool(cols)
		except Exception:
			return False

	def _save_results(self, variants: List[tuple]):
		"""Lưu kết quả draft — variants: [(variant_index, solution), ...]."""
		frappe.db.sql(
			"DELETE FROM `tabSIS_TKB_Gen_Result` WHERE session_id = %s",
			self.session_id,
		)

		has_variant_col = self._has_variant_index_column()
		batch_size = 500
		all_rows = []
		for variant_index, solution in variants:
			for slot in solution:
				all_rows.append((variant_index, slot))

		for i in range(0, len(all_rows), batch_size):
			batch = all_rows[i:i + batch_size]
			values = []
			for variant_index, slot in batch:
				name = frappe.generate_hash(length=10)
				teacher_ids_json = json.dumps(slot.get("teacher_ids", []))
				if has_variant_col:
					values.append(
						f"('{name}', '{self.session_id}', '{slot['class_id']}', "
						f"'{slot['day_of_week']}', '{slot['timetable_column_id']}', "
						f"'{slot.get('timetable_subject_id', '')}', "
						f"'{teacher_ids_json}', "
						f"'{slot.get('room_id', '')}', "
						f"{slot.get('period_priority', 0)}, {variant_index}, NOW())"
					)
				else:
					if variant_index != 0:
						continue
					values.append(
						f"('{name}', '{self.session_id}', '{slot['class_id']}', "
						f"'{slot['day_of_week']}', '{slot['timetable_column_id']}', "
						f"'{slot.get('timetable_subject_id', '')}', "
						f"'{teacher_ids_json}', "
						f"'{slot.get('room_id', '')}', "
						f"{slot.get('period_priority', 0)}, NOW())"
					)

			if not values:
				continue

			if has_variant_col:
				frappe.db.sql(f"""
					INSERT INTO `tabSIS_TKB_Gen_Result`
					(name, session_id, class_id, day_of_week, timetable_column_id,
					 timetable_subject_id, teacher_ids, room_id, period_priority, variant_index, creation)
					VALUES {','.join(values)}
				""")
			else:
				frappe.db.sql(f"""
					INSERT INTO `tabSIS_TKB_Gen_Result`
					(name, session_id, class_id, day_of_week, timetable_column_id,
					 timetable_subject_id, teacher_ids, room_id, period_priority, creation)
					VALUES {','.join(values)}
				""")

		frappe.db.commit()


def run_solver(session_id: str):
	"""Entry point cho background job (frappe.enqueue)."""
	session = frappe.get_doc("SIS Timetable Generation Session", session_id)
	session.status = "Running"
	session.started_at = datetime.now()
	session.save(ignore_permissions=True)
	frappe.db.commit()

	solver = TimetableSolver(session_id)
	result = solver.solve()

	session.reload()
	session.completed_at = datetime.now()
	session.solver_stats = json.dumps({
		"status": result.status,
		"num_variables": result.num_variables,
		"num_constraints": result.num_constraints,
		"solve_time_ms": result.solve_time_ms,
		"total_slots": result.total_slots,
		"variant_count": result.variant_count,
		"warnings": result.warnings,
		"suspects": result.suspects,
	})
	session.total_classes = result.total_classes
	session.total_slots_generated = result.total_slots

	if result.success:
		session.status = "Completed"
	else:
		session.status = "Failed"
		session.error_log = "\n".join(result.errors)

	session.save(ignore_permissions=True)
	frappe.db.commit()


def run_solver_variants(session_id: str, k: int = 3, min_diff_ratio: float = 0.10):
	"""Background job sinh biến thể draft."""
	session = frappe.get_doc("SIS Timetable Generation Session", session_id)
	session.status = "Running"
	session.started_at = datetime.now()
	session.save(ignore_permissions=True)
	frappe.db.commit()

	solver = TimetableSolver(session_id)
	result = solver.solve_variants(k=k, min_diff_ratio=min_diff_ratio)

	session.reload()
	session.completed_at = datetime.now()
	session.solver_stats = json.dumps({
		"status": result.status,
		"variant_count": result.variant_count,
		"total_slots": result.total_slots,
		"warnings": result.warnings,
	})
	session.total_classes = result.total_classes
	session.total_slots_generated = result.total_slots

	if result.success:
		session.status = "Completed"
	else:
		session.status = "Failed"
		session.error_log = "\n".join(result.errors)

	session.save(ignore_permissions=True)
	frappe.db.commit()
