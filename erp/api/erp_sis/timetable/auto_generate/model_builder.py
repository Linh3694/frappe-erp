"""
Model Builder - Xây dựng mô hình CP-SAT từ TimetableInput.

Hard constraints được hardcode (không thay đổi).
Soft constraints được đọc từ session config.
"""

from typing import Any, Dict, List, Tuple, Optional
from dataclasses import dataclass, field

from .data_collector import TimetableInput, SubjectRequirement


DAY_ORDER = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


@dataclass
class SolverModel:
	"""Kết quả build: chứa model + biến + metadata để extract solution."""
	model: Any = None

	# x[(class_id, subject_id, day, period_idx)] = BoolVar
	x: Dict[Tuple[str, str, str, int], Any] = field(default_factory=dict)

	# room_assign[(class_id, day, period_idx)] = IntVar (domain = room indices)
	room_assign: Dict[Tuple[str, str, int], Any] = field(default_factory=dict)

	# Metadata
	input: Optional[TimetableInput] = None
	period_index_map: Dict[str, int] = field(default_factory=dict)
	room_index_map: Dict[str, int] = field(default_factory=dict)
	room_list: List[str] = field(default_factory=list)


class ModelBuilder:
	"""Xây dựng OR-Tools CP-SAT model từ TimetableInput."""

	def __init__(self, inp: TimetableInput):
		from ortools.sat.python import cp_model
		self.cp_model = cp_model
		self.inp = inp
		self.model = cp_model.CpModel()
		self.solver_model = SolverModel(model=self.model, input=inp)

		self._setup_indexes()

	def build(self) -> SolverModel:
		"""Build toàn bộ model."""
		self._create_variables()
		self._add_hard_constraints()
		self._add_soft_constraints()
		return self.solver_model

	# ── Setup ──────────────────────────────────────────

	def _setup_indexes(self):
		sm = self.solver_model

		# Period index: priority order
		for i, p in enumerate(sorted(self.inp.periods, key=lambda x: x.period_priority)):
			sm.period_index_map[p.name] = i

		# Room index
		for i, r in enumerate(self.inp.rooms):
			sm.room_index_map[r.name] = i
			sm.room_list.append(r.name)

	# ── Variables ──────────────────────────────────────

	def _create_variables(self):
		sm = self.solver_model
		inp = self.inp

		for c in inp.classes:
			grade = c.education_grade_id
			subjects = inp.grade_subjects.get(grade, [])

			for ts_id in subjects:
				for day in inp.working_days:
					for p_idx, period in enumerate(sorted(inp.periods, key=lambda x: x.period_priority)):
						key = (c.name, ts_id, day, p_idx)
						sm.x[key] = self.model.NewBoolVar(f"x_{c.name}_{ts_id}_{day}_{p_idx}")

	# ── Hard Constraints (HARDCODED) ──────────────────

	def _add_hard_constraints(self):
		self._constraint_one_subject_per_slot()
		self._constraint_required_periods()
		self._constraint_teacher_no_conflict()
		self._constraint_teacher_weekday_availability()
		self._constraint_max_periods_per_day_subject()
		self._constraint_max_periods_per_day_teacher()
		self._constraint_max_consecutive_teacher()

	def _constraint_one_subject_per_slot(self):
		"""HC1: Mỗi lớp chỉ học 1 môn mỗi tiết."""
		inp = self.inp
		sm = self.solver_model

		for c in inp.classes:
			grade = c.education_grade_id
			subjects = inp.grade_subjects.get(grade, [])
			for day in inp.working_days:
				for p_idx in range(len(inp.periods)):
					slot_vars = []
					for ts_id in subjects:
						key = (c.name, ts_id, day, p_idx)
						if key in sm.x:
							slot_vars.append(sm.x[key])
					if slot_vars:
						self.model.Add(sum(slot_vars) <= 1)

	def _constraint_required_periods(self):
		"""HC2: Số tiết/tuần theo requirement. Dùng == nếu khả thi, fallback <= nếu tổng vượt capacity."""
		inp = self.inp
		sm = self.solver_model

		req_map: Dict[Tuple[str, str], SubjectRequirement] = {}
		for req in inp.requirements:
			req_map[(req.education_grade_id, req.timetable_subject_id)] = req

		num_slots = len(inp.periods) * len(inp.working_days)

		for c in inp.classes:
			grade = c.education_grade_id
			subjects = inp.grade_subjects.get(grade, [])

			# Tính tổng tiết yêu cầu cho lớp này
			total_required = sum(
				(req_map.get((grade, ts_id)) or SubjectRequirement(
					timetable_subject_id=ts_id, timetable_subject_title="", education_grade_id=grade,
					periods_per_week=0)).periods_per_week
				for ts_id in subjects
			)
			# Nếu tổng vượt capacity → dùng <= (best effort)
			use_exact = total_required <= num_slots

			for ts_id in subjects:
				req = req_map.get((grade, ts_id))
				if not req or req.periods_per_week == 0:
					continue

				week_vars = []
				for day in inp.working_days:
					for p_idx in range(len(inp.periods)):
						key = (c.name, ts_id, day, p_idx)
						if key in sm.x:
							week_vars.append(sm.x[key])

				if week_vars:
					if use_exact:
						self.model.Add(sum(week_vars) == req.periods_per_week)
					else:
						self.model.Add(sum(week_vars) <= req.periods_per_week)

	def _constraint_teacher_no_conflict(self):
		"""HC3: Mỗi GV chỉ dạy 1 lớp mỗi tiết."""
		inp = self.inp
		sm = self.solver_model

		# Build: teacher -> [(class, subject, day, p_idx)]
		teacher_slots: Dict[str, List[Tuple[str, str, str, int]]] = {}
		for c in inp.classes:
			grade = c.education_grade_id
			subjects = inp.grade_subjects.get(grade, [])
			for ts_id in subjects:
				key_assign = f"{c.name}|{ts_id}"
				teachers = inp.class_subject_teachers.get(key_assign, [])
				for t_id in teachers:
					teacher_slots.setdefault(t_id, []).append((c.name, ts_id))

		for t_id, class_subjects in teacher_slots.items():
			for day in inp.working_days:
				for p_idx in range(len(inp.periods)):
					slot_vars = []
					for (c_id, ts_id) in class_subjects:
						key = (c_id, ts_id, day, p_idx)
						if key in sm.x:
							slot_vars.append(sm.x[key])
					if len(slot_vars) > 1:
						self.model.Add(sum(slot_vars) <= 1)

	def _constraint_teacher_weekday_availability(self):
		"""HC4: GV chỉ dạy những ngày có trong weekdays. Chỉ áp dụng khi lớp+môn CHỈ có 1 GV duy nhất."""
		inp = self.inp
		sm = self.solver_model

		# Chỉ block ngày nếu TẤT CẢ GV của (class, subject) đều không dạy ngày đó
		# Nếu có nhiều GV, chỉ cần 1 GV dạy ngày đó là được
		class_subject_weekdays: Dict[Tuple[str, str], set] = {}
		for a in inp.assignments:
			key = (a.class_id, a.timetable_subject_id)
			allowed = set(a.weekdays) if a.weekdays else set(inp.working_days)
			if key not in class_subject_weekdays:
				class_subject_weekdays[key] = set()
			class_subject_weekdays[key].update(allowed)

		for (c_id, ts_id), allowed_days in class_subject_weekdays.items():
			for day in inp.working_days:
				if day not in allowed_days:
					for p_idx in range(len(inp.periods)):
						key = (c_id, ts_id, day, p_idx)
						if key in sm.x:
							self.model.Add(sm.x[key] == 0)

	def _constraint_max_periods_per_day_subject(self):
		"""HC7: Max tiết/ngày cho 1 môn với 1 lớp."""
		inp = self.inp
		sm = self.solver_model

		req_map = {(r.education_grade_id, r.timetable_subject_id): r for r in inp.requirements}

		for c in inp.classes:
			grade = c.education_grade_id
			subjects = inp.grade_subjects.get(grade, [])
			for ts_id in subjects:
				req = req_map.get((grade, ts_id))
				max_per_day = req.max_periods_per_day if req else 2

				for day in inp.working_days:
					day_vars = []
					for p_idx in range(len(inp.periods)):
						key = (c.name, ts_id, day, p_idx)
						if key in sm.x:
							day_vars.append(sm.x[key])
					if day_vars:
						self.model.Add(sum(day_vars) <= max_per_day)

	def _constraint_max_periods_per_day_teacher(self):
		"""HC8: Max tiết/ngày cho GV (từ SIS Teacher.max_periods_per_day)."""
		inp = self.inp
		sm = self.solver_model

		# Build teacher -> all their (class, subject) combos
		teacher_class_subjects: Dict[str, List[Tuple[str, str]]] = {}
		for c in inp.classes:
			grade = c.education_grade_id
			for ts_id in inp.grade_subjects.get(grade, []):
				key_a = f"{c.name}|{ts_id}"
				for t_id in inp.class_subject_teachers.get(key_a, []):
					teacher_class_subjects.setdefault(t_id, []).append((c.name, ts_id))

		for t_id, cs_list in teacher_class_subjects.items():
			teacher_info = inp.teachers.get(t_id)
			if not teacher_info:
				continue
			max_per_day = teacher_info.max_periods_per_day

			for day in inp.working_days:
				day_vars = []
				for (c_id, ts_id) in cs_list:
					for p_idx in range(len(inp.periods)):
						key = (c_id, ts_id, day, p_idx)
						if key in sm.x:
							day_vars.append(sm.x[key])
				if day_vars:
					self.model.Add(sum(day_vars) <= max_per_day)

	def _constraint_max_consecutive_teacher(self):
		"""HC9: Max tiết liên tiếp cho GV (sliding window)."""
		inp = self.inp
		sm = self.solver_model

		teacher_class_subjects: Dict[str, List[Tuple[str, str]]] = {}
		for c in inp.classes:
			grade = c.education_grade_id
			for ts_id in inp.grade_subjects.get(grade, []):
				key_a = f"{c.name}|{ts_id}"
				for t_id in inp.class_subject_teachers.get(key_a, []):
					teacher_class_subjects.setdefault(t_id, []).append((c.name, ts_id))

		num_periods = len(inp.periods)
		for t_id, cs_list in teacher_class_subjects.items():
			teacher_info = inp.teachers.get(t_id)
			if not teacher_info:
				continue
			max_consec = teacher_info.max_consecutive_periods
			if max_consec >= num_periods:
				continue

			for day in inp.working_days:
				# Sliding window: bất kỳ cửa sổ (max_consec + 1) tiết liên tiếp nào
				# phải có tổng <= max_consec
				for start in range(num_periods - max_consec):
					window_vars = []
					for p_idx in range(start, start + max_consec + 1):
						for (c_id, ts_id) in cs_list:
							key = (c_id, ts_id, day, p_idx)
							if key in sm.x:
								window_vars.append(sm.x[key])
					if window_vars:
						self.model.Add(sum(window_vars) <= max_consec)

	# ── Soft Constraints ──────────────────────────────

	def _add_soft_constraints(self):
		"""Soft constraints: ảnh hưởng hàm mục tiêu, không bắt buộc."""
		soft = self.inp.soft_rules
		objectives = []

		if soft.consecutive_bonus > 0:
			objectives.extend(self._soft_consecutive_bonus(soft.consecutive_bonus))

		if soft.teacher_gap_minimization > 0:
			objectives.extend(self._soft_teacher_gap_minimization(soft.teacher_gap_minimization))

		if soft.workload_balance > 0:
			objectives.extend(self._soft_workload_balance(soft.workload_balance))

		if soft.subject_time_preferences:
			objectives.extend(self._soft_subject_time_preferences(soft.subject_time_preferences))

		if soft.subject_pair_exclusions:
			objectives.extend(self._soft_subject_pair_exclusions(soft.subject_pair_exclusions))

		if objectives:
			self.model.Maximize(sum(objectives))

	def _soft_consecutive_bonus(self, weight: int) -> List:
		"""Ưu tiên xếp tiết đôi cho môn có prefer_consecutive."""
		inp = self.inp
		sm = self.solver_model
		bonuses = []

		req_map = {(r.education_grade_id, r.timetable_subject_id): r for r in inp.requirements}
		num_periods = len(inp.periods)

		for c in inp.classes:
			grade = c.education_grade_id
			for ts_id in inp.grade_subjects.get(grade, []):
				req = req_map.get((grade, ts_id))
				if not req or not req.prefer_consecutive:
					continue

				for day in inp.working_days:
					for p_idx in range(num_periods - 1):
						key1 = (c.name, ts_id, day, p_idx)
						key2 = (c.name, ts_id, day, p_idx + 1)
						if key1 in sm.x and key2 in sm.x:
							# Bonus khi cả 2 tiết liên tiếp cùng môn
							both = self.model.NewBoolVar(f"consec_{c.name}_{ts_id}_{day}_{p_idx}")
							self.model.AddBoolAnd([sm.x[key1], sm.x[key2]]).OnlyEnforceIf(both)
							self.model.AddBoolOr([sm.x[key1].Not(), sm.x[key2].Not()]).OnlyEnforceIf(both.Not())
							bonuses.append(both * weight)

		return bonuses

	def _soft_teacher_gap_minimization(self, weight: int) -> List:
		"""Giảm 'tiết trống' cho GV (khoảng trống giữa tiết đầu và cuối)."""
		inp = self.inp
		sm = self.solver_model
		penalties = []

		teacher_class_subjects: Dict[str, List[Tuple[str, str]]] = {}
		for c in inp.classes:
			grade = c.education_grade_id
			for ts_id in inp.grade_subjects.get(grade, []):
				key_a = f"{c.name}|{ts_id}"
				for t_id in inp.class_subject_teachers.get(key_a, []):
					teacher_class_subjects.setdefault(t_id, []).append((c.name, ts_id))

		num_periods = len(inp.periods)
		for t_id, cs_list in teacher_class_subjects.items():
			for day in inp.working_days:
				# Tạo biến: GV có dạy tiết p_idx không
				teaching_at = []
				for p_idx in range(num_periods):
					t_vars = []
					for (c_id, ts_id) in cs_list:
						key = (c_id, ts_id, day, p_idx)
						if key in sm.x:
							t_vars.append(sm.x[key])
					if t_vars:
						is_teaching = self.model.NewBoolVar(f"teach_{t_id}_{day}_{p_idx}")
						self.model.AddMaxEquality(is_teaching, t_vars)
						teaching_at.append((p_idx, is_teaching))

				# Penalty cho mỗi cặp (dạy, trống, dạy)
				for i in range(len(teaching_at)):
					for j in range(i + 2, len(teaching_at)):
						p_i, var_i = teaching_at[i]
						p_j, var_j = teaching_at[j]
						# Các tiết ở giữa
						for k in range(i + 1, j):
							p_k, var_k = teaching_at[k]
							# Nếu dạy ở i và j nhưng không dạy ở k -> gap
							gap = self.model.NewBoolVar(f"gap_{t_id}_{day}_{p_i}_{p_k}_{p_j}")
							self.model.AddBoolAnd([var_i, var_j, var_k.Not()]).OnlyEnforceIf(gap)
							self.model.AddBoolOr([var_i.Not(), var_j.Not(), var_k]).OnlyEnforceIf(gap.Not())
							penalties.append(gap * (-weight))

		return penalties

	def _soft_workload_balance(self, weight: int) -> List:
		"""Cân bằng số tiết/ngày cho GV (minimize variance)."""
		# Đơn giản hóa: minimize max - min tiết/ngày cho mỗi GV
		inp = self.inp
		sm = self.solver_model
		objectives = []

		teacher_class_subjects: Dict[str, List[Tuple[str, str]]] = {}
		for c in inp.classes:
			grade = c.education_grade_id
			for ts_id in inp.grade_subjects.get(grade, []):
				key_a = f"{c.name}|{ts_id}"
				for t_id in inp.class_subject_teachers.get(key_a, []):
					teacher_class_subjects.setdefault(t_id, []).append((c.name, ts_id))

		num_periods = len(inp.periods)
		num_days = len(inp.working_days)

		for t_id, cs_list in teacher_class_subjects.items():
			day_loads = []
			for day in inp.working_days:
				day_vars = []
				for (c_id, ts_id) in cs_list:
					for p_idx in range(num_periods):
						key = (c_id, ts_id, day, p_idx)
						if key in sm.x:
							day_vars.append(sm.x[key])
				if day_vars:
					load = self.model.NewIntVar(0, num_periods, f"load_{t_id}_{day}")
					self.model.Add(load == sum(day_vars))
					day_loads.append(load)

			if len(day_loads) >= 2:
				max_load = self.model.NewIntVar(0, num_periods, f"max_load_{t_id}")
				min_load = self.model.NewIntVar(0, num_periods, f"min_load_{t_id}")
				self.model.AddMaxEquality(max_load, day_loads)
				self.model.AddMinEquality(min_load, day_loads)
				diff = self.model.NewIntVar(0, num_periods, f"diff_load_{t_id}")
				self.model.Add(diff == max_load - min_load)
				objectives.append(diff * (-weight))

		return objectives

	def _soft_subject_time_preferences(self, preferences: List[Dict]) -> List:
		"""Ưu tiên xếp môn vào khung giờ nhất định."""
		inp = self.inp
		sm = self.solver_model
		bonuses = []

		for pref in preferences:
			ts_id = pref.get("subject")
			preferred_periods = pref.get("preferred_periods", [])
			pref_weight = pref.get("weight", 50)
			if not ts_id or not preferred_periods:
				continue

			# Tìm index các tiết preferred
			preferred_indices = set()
			for i, p in enumerate(sorted(inp.periods, key=lambda x: x.period_priority)):
				if p.name in preferred_periods or p.period_name in preferred_periods:
					preferred_indices.add(i)

			for c in inp.classes:
				grade = c.education_grade_id
				if ts_id not in inp.grade_subjects.get(grade, []):
					continue
				for day in inp.working_days:
					for p_idx in range(len(inp.periods)):
						key = (c.name, ts_id, day, p_idx)
						if key in sm.x:
							if p_idx in preferred_indices:
								bonuses.append(sm.x[key] * pref_weight)
							else:
								bonuses.append(sm.x[key] * (-pref_weight // 4))

		return bonuses

	def _soft_subject_pair_exclusions(self, exclusions: List[Dict]) -> List:
		"""2 môn không nên xếp cùng buổi (sáng/chiều)."""
		inp = self.inp
		sm = self.solver_model
		penalties = []

		num_periods = len(inp.periods)
		half = num_periods // 2

		for excl in exclusions:
			s1 = excl.get("subject_1")
			s2 = excl.get("subject_2")
			excl_weight = excl.get("weight", 50)
			if not s1 or not s2:
				continue

			for c in inp.classes:
				grade = c.education_grade_id
				grade_subs = inp.grade_subjects.get(grade, [])
				if s1 not in grade_subs or s2 not in grade_subs:
					continue

				for day in inp.working_days:
					# Buổi sáng: p_idx < half, buổi chiều: p_idx >= half
					for half_start, half_end in [(0, half), (half, num_periods)]:
						vars_s1 = []
						vars_s2 = []
						for p_idx in range(half_start, half_end):
							k1 = (c.name, s1, day, p_idx)
							k2 = (c.name, s2, day, p_idx)
							if k1 in sm.x:
								vars_s1.append(sm.x[k1])
							if k2 in sm.x:
								vars_s2.append(sm.x[k2])

						if vars_s1 and vars_s2:
							has_s1 = self.model.NewBoolVar(f"has_{s1}_{c.name}_{day}_{half_start}")
							has_s2 = self.model.NewBoolVar(f"has_{s2}_{c.name}_{day}_{half_start}")
							self.model.AddMaxEquality(has_s1, vars_s1)
							self.model.AddMaxEquality(has_s2, vars_s2)

							both = self.model.NewBoolVar(f"both_{s1}_{s2}_{c.name}_{day}_{half_start}")
							self.model.AddBoolAnd([has_s1, has_s2]).OnlyEnforceIf(both)
							self.model.AddBoolOr([has_s1.Not(), has_s2.Not()]).OnlyEnforceIf(both.Not())
							penalties.append(both * (-excl_weight))

		return penalties

	def extract_solution(self, solver) -> List[Dict]:
		"""Trích xuất solution thành danh sách slot."""
		inp = self.inp
		sm = self.solver_model
		sorted_periods = sorted(inp.periods, key=lambda x: x.period_priority)
		results = []

		for c in inp.classes:
			grade = c.education_grade_id
			for ts_id in inp.grade_subjects.get(grade, []):
				for day in inp.working_days:
					for p_idx, period in enumerate(sorted_periods):
						key = (c.name, ts_id, day, p_idx)
						if key in sm.x and solver.Value(sm.x[key]) == 1:
							# Tìm teachers cho (class, subject)
							key_a = f"{c.name}|{ts_id}"
							teacher_ids = inp.class_subject_teachers.get(key_a, [])

							results.append({
								"class_id": c.name,
								"day_of_week": day,
								"timetable_column_id": period.name,
								"timetable_subject_id": ts_id,
								"teacher_ids": teacher_ids,
								"room_id": c.room_id,
								"period_priority": period.period_priority,
							})

		return results
