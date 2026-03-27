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


@dataclass
class SolverResult:
	success: bool = False
	status: str = ""  # OPTIMAL, FEASIBLE, INFEASIBLE, etc.
	num_variables: int = 0
	num_constraints: int = 0
	solve_time_ms: float = 0
	total_slots: int = 0
	total_classes: int = 0
	warnings: List[str] = field(default_factory=list)
	errors: List[str] = field(default_factory=list)


class TimetableSolver:
	"""Chạy solver cho 1 session."""

	def __init__(self, session_id: str):
		self.session_id = session_id

	def solve(self) -> SolverResult:
		result = SolverResult()

		try:
			# Thu thập dữ liệu
			collector = TimetableDataCollector(self.session_id)
			inp = collector.collect()

			# Validate input
			warnings = self._validate_input(inp)
			result.warnings = warnings

			if not inp.classes:
				result.errors.append("Không tìm thấy lớp nào trong phạm vi đã chọn")
				return result

			if not inp.periods:
				result.errors.append("Không tìm thấy tiết học nào trong schedule đã chọn")
				return result

			if not inp.requirements:
				result.errors.append("Chưa có yêu cầu số tiết/tuần nào (Requirements matrix trống)")
				return result

			# Lazy import ortools (chỉ cần khi thực sự chạy solver)
			from ortools.sat.python import cp_model
			from .model_builder import ModelBuilder

			# Build model
			builder = ModelBuilder(inp)
			solver_model = builder.build()

			# Solve
			solver = cp_model.CpSolver()
			solver.parameters.max_time_in_seconds = inp.solver_time_limit
			solver.parameters.num_workers = 4
			solver.parameters.log_search_progress = False

			status = solver.Solve(solver_model.model)

			result.num_variables = solver_model.model.Proto().variables.__len__()
			result.num_constraints = solver_model.model.Proto().constraints.__len__()
			result.solve_time_ms = solver.WallTime() * 1000

			status_name = solver.StatusName(status)
			result.status = status_name

			if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
				result.success = True
				solution = builder.extract_solution(solver)
				result.total_slots = len(solution)
				result.total_classes = len(set(s["class_id"] for s in solution))

				# Lưu vào draft table
				self._save_results(solution)

				if status == cp_model.FEASIBLE:
					result.warnings.append(
						"Solver tìm được lời giải khả thi nhưng chưa tối ưu "
						"(hết thời gian trước khi tìm được lời giải tốt nhất)"
					)
			else:
				result.errors.append(f"Solver không tìm được lời giải: {status_name}")
				if status == cp_model.INFEASIBLE:
					result.errors.append(
						"Các ràng buộc mâu thuẫn nhau. Kiểm tra: "
						"(1) Tổng số tiết yêu cầu có vượt số slot/tuần? "
						"(2) Có đủ GV cho tất cả lớp-môn? "
						"(3) GV có bị giới hạn quá chặt (max_periods_per_day)?"
					)

		except Exception as e:
			result.errors.append(f"Lỗi hệ thống: {str(e)}")
			frappe.log_error(f"Timetable solver error for session {self.session_id}: {str(e)}")

		return result

	def _validate_input(self, inp: TimetableInput) -> List[str]:
		"""Kiểm tra dữ liệu đầu vào, trả về danh sách cảnh báo."""
		warnings = []

		# Kiểm tra assignment cho mỗi (class, subject)
		for c in inp.classes:
			grade = c.education_grade_id
			for ts_id in inp.grade_subjects.get(grade, []):
				key_a = f"{c.name}|{ts_id}"
				teachers = inp.class_subject_teachers.get(key_a, [])
				if not teachers:
					# Tìm tên cho warning
					req = next((r for r in inp.requirements
								if r.education_grade_id == grade and r.timetable_subject_id == ts_id), None)
					subject_name = req.timetable_subject_title if req else ts_id
					warnings.append(f"Lớp {c.title} chưa có GV phân công cho môn {subject_name}")

		# Kiểm tra tổng số tiết
		num_periods = len(inp.periods)
		num_days = len(inp.working_days)
		max_slots_per_week = num_periods * num_days

		for c in inp.classes:
			grade = c.education_grade_id
			total_required = sum(
				r.periods_per_week for r in inp.requirements
				if r.education_grade_id == grade
			)
			if total_required > max_slots_per_week:
				warnings.append(
					f"Lớp {c.title}: tổng yêu cầu {total_required} tiết/tuần "
					f"vượt khả năng {max_slots_per_week} slot ({num_periods} tiết x {num_days} ngày)"
				)

		return warnings

	def _save_results(self, solution: List[Dict]):
		"""Lưu kết quả vào tabSIS_TKB_Gen_Result (raw SQL)."""
		# Xóa kết quả cũ của session
		frappe.db.sql(
			"DELETE FROM `tabSIS_TKB_Gen_Result` WHERE session_id = %s",
			self.session_id
		)

		if not solution:
			return

		# Bulk insert
		batch_size = 500
		for i in range(0, len(solution), batch_size):
			batch = solution[i:i + batch_size]
			values = []
			for slot in batch:
				name = frappe.generate_hash(length=10)
				teacher_ids_json = json.dumps(slot.get("teacher_ids", []))
				values.append(
					f"('{name}', '{self.session_id}', '{slot['class_id']}', "
					f"'{slot['day_of_week']}', '{slot['timetable_column_id']}', "
					f"'{slot.get('timetable_subject_id', '')}', "
					f"'{teacher_ids_json}', "
					f"'{slot.get('room_id', '')}', "
					f"{slot.get('period_priority', 0)}, "
					f"NOW())"
				)

			if values:
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
		"warnings": result.warnings,
	})
	session.total_classes = result.total_classes
	session.total_slots_generated = result.total_slots

	if result.success:
		session.status = "Completed"
	else:
		session.status = "Failed"
		session.error_log = "\n".join(result.errors + result.warnings)

	session.save(ignore_permissions=True)
	frappe.db.commit()
