"""
Data Collector - Thu thập toàn bộ dữ liệu cần cho solver từ 1 session.

Chỉ ĐỌC dữ liệu từ các doctype hiện có, KHÔNG sửa gì.
"""

import json
from typing import Dict, List, Optional, NamedTuple
from dataclasses import dataclass, field

import frappe


@dataclass
class ClassInfo:
	name: str
	title: str
	education_grade_id: str
	room_id: Optional[str] = None  # phòng chủ nhiệm


@dataclass
class PeriodInfo:
	name: str
	period_name: str
	period_priority: int
	period_type: str  # study / non-study
	start_time: str
	end_time: str


@dataclass
class TeacherInfo:
	name: str
	user_id: str
	max_periods_per_day: int = 8
	max_consecutive_periods: int = 4


@dataclass
class RoomInfo:
	name: str
	title: str
	room_type: str
	capacity: int = 0


@dataclass
class SubjectRequirement:
	timetable_subject_id: str
	timetable_subject_title: str
	education_grade_id: str
	periods_per_week: int
	max_periods_per_day: int = 2
	prefer_consecutive: bool = False
	room_type_required: Optional[str] = None


@dataclass
class TeacherAssignment:
	"""Mapping: (class, timetable_subject) -> teacher + weekdays"""
	teacher_id: str
	class_id: str
	timetable_subject_id: str
	weekdays: List[str]  # ["mon","tue",...] hoặc [] = tất cả


@dataclass
class SoftRules:
	subject_pair_exclusions: List[Dict] = field(default_factory=list)
	subject_time_preferences: List[Dict] = field(default_factory=list)
	teacher_gap_minimization: int = 50
	workload_balance: int = 50
	consecutive_bonus: int = 80
	homeroom_preference: int = 60


@dataclass
class TimetableInput:
	"""Toàn bộ input cho solver"""
	classes: List[ClassInfo] = field(default_factory=list)
	periods: List[PeriodInfo] = field(default_factory=list)
	teachers: Dict[str, TeacherInfo] = field(default_factory=dict)
	rooms: List[RoomInfo] = field(default_factory=list)
	requirements: List[SubjectRequirement] = field(default_factory=list)
	assignments: List[TeacherAssignment] = field(default_factory=list)
	soft_rules: SoftRules = field(default_factory=SoftRules)
	working_days: List[str] = field(default_factory=lambda: ["mon", "tue", "wed", "thu", "fri"])
	solver_time_limit: int = 120

	# Derived indexes (sẽ được build sau collect)
	class_grade_map: Dict[str, str] = field(default_factory=dict)
	grade_subjects: Dict[str, List[str]] = field(default_factory=dict)
	class_subject_teachers: Dict[str, List[str]] = field(default_factory=dict)


class TimetableDataCollector:
	"""Thu thập toàn bộ dữ liệu từ session + existing doctypes."""

	def __init__(self, session_id: str):
		self.session = frappe.get_doc("SIS Timetable Generation Session", session_id)

	def collect(self) -> TimetableInput:
		inp = TimetableInput()

		inp.classes = self._get_classes()
		inp.periods = self._get_periods()
		inp.teachers = self._get_teachers()
		inp.rooms = self._get_rooms()
		inp.requirements = self._get_requirements()
		inp.assignments = self._get_assignments()
		inp.soft_rules = self._parse_soft_rules()
		inp.working_days = self._get_working_days()
		inp.solver_time_limit = self.session.solver_time_limit or 120

		self._build_indexes(inp)
		return inp

	def _get_classes(self) -> List[ClassInfo]:
		"""Lấy danh sách lớp theo scope của session."""
		filters = {
			"campus_id": self.session.campus_id,
			"school_year_id": self.session.school_year_id,
		}

		# Lọc theo education_stage thông qua education_grade
		grades = frappe.get_all(
			"SIS Education Grade",
			filters={"education_stage_id": self.session.education_stage_id},
			pluck="name"
		)
		if not grades:
			return []

		class_ids = None
		if self.session.class_ids:
			try:
				class_ids = json.loads(self.session.class_ids)
			except (json.JSONDecodeError, TypeError):
				pass

		sql = """
			SELECT c.name, c.title, c.education_grade as education_grade_id, c.room as room_id
			FROM `tabSIS Class` c
			WHERE c.campus_id = %(campus_id)s
			  AND c.school_year_id = %(school_year_id)s
			  AND c.education_grade IN %(grades)s
		"""
		params = {
			"campus_id": self.session.campus_id,
			"school_year_id": self.session.school_year_id,
			"grades": grades,
		}

		if class_ids:
			sql += " AND c.name IN %(class_ids)s"
			params["class_ids"] = class_ids

		sql += " ORDER BY c.education_grade, c.title"

		rows = frappe.db.sql(sql, params, as_dict=True)
		return [ClassInfo(**r) for r in rows]

	def _get_periods(self) -> List[PeriodInfo]:
		"""Lấy tiết học (study only) theo schedule của session."""
		rows = frappe.db.sql("""
			SELECT name, period_name, period_priority, period_type, start_time, end_time
			FROM `tabSIS Timetable Column`
			WHERE schedule_id = %(schedule_id)s
			  AND period_type = 'study'
			ORDER BY period_priority
		""", {"schedule_id": self.session.schedule_id}, as_dict=True)

		if not rows:
			# Fallback: lấy theo campus + education_stage (legacy)
			rows = frappe.db.sql("""
				SELECT name, period_name, period_priority, period_type, start_time, end_time
				FROM `tabSIS Timetable Column`
				WHERE campus_id = %(campus_id)s
				  AND education_stage_id = %(education_stage_id)s
				  AND period_type = 'study'
				  AND (schedule_id IS NULL OR schedule_id = '')
				ORDER BY period_priority
			""", {
				"campus_id": self.session.campus_id,
				"education_stage_id": self.session.education_stage_id,
			}, as_dict=True)

		return [PeriodInfo(**r) for r in rows]

	def _get_teachers(self) -> Dict[str, TeacherInfo]:
		"""Lấy GV theo campus, kèm scheduling config."""
		rows = frappe.db.sql("""
			SELECT name, user_id,
				   COALESCE(max_periods_per_day, 8) as max_periods_per_day,
				   COALESCE(max_consecutive_periods, 4) as max_consecutive_periods
			FROM `tabSIS Teacher`
			WHERE campus_id = %(campus_id)s
		""", {"campus_id": self.session.campus_id}, as_dict=True)
		return {r["name"]: TeacherInfo(**r) for r in rows}

	def _get_rooms(self) -> List[RoomInfo]:
		"""Lấy phòng theo campus."""
		rows = frappe.db.sql("""
			SELECT name, title_vn as title, room_type, COALESCE(capacity, 0) as capacity
			FROM `tabERP Administrative Room`
			WHERE campus_id = %(campus_id)s
		""", {"campus_id": self.session.campus_id}, as_dict=True)
		return [RoomInfo(**r) for r in rows]

	def _get_requirements(self) -> List[SubjectRequirement]:
		"""Lấy requirements từ session (grade x timetable_subject -> periods_per_week)."""
		rows = frappe.db.sql("""
			SELECT
				r.timetable_subject_id,
				ts.title_vn as timetable_subject_title,
				r.education_grade_id,
				r.periods_per_week,
				r.max_periods_per_day,
				r.prefer_consecutive,
				r.room_type_required
			FROM `tabSIS Timetable Generation Requirement` r
			JOIN `tabSIS Timetable Subject` ts ON ts.name = r.timetable_subject_id
			WHERE r.session_id = %(session_id)s
			  AND r.periods_per_week > 0
		""", {"session_id": self.session.name}, as_dict=True)

		return [SubjectRequirement(
			timetable_subject_id=r["timetable_subject_id"],
			timetable_subject_title=r["timetable_subject_title"],
			education_grade_id=r["education_grade_id"],
			periods_per_week=r["periods_per_week"],
			max_periods_per_day=r["max_periods_per_day"] or 2,
			prefer_consecutive=bool(r["prefer_consecutive"]),
			room_type_required=r["room_type_required"] or None,
		) for r in rows]

	def _get_assignments(self) -> List[TeacherAssignment]:
		"""
		Mapping Subject Assignment sang Timetable Subject.

		Flow: SIS Subject Assignment (teacher + class + actual_subject)
		      -> SIS Subject (timetable_subject_id) theo education_stage
		      -> Timetable Subject (đơn vị gen TKB)
		"""
		rows = frappe.db.sql("""
			SELECT
				sa.teacher_id,
				sa.class_id,
				s.timetable_subject_id,
				sa.weekdays
			FROM `tabSIS Subject Assignment` sa
			JOIN `tabSIS Subject` s
				ON s.actual_subject_id = sa.actual_subject_id
				AND s.education_stage = %(education_stage_id)s
				AND s.campus_id = %(campus_id)s
			WHERE sa.campus_id = %(campus_id)s
			  AND sa.class_id IS NOT NULL
			  AND sa.class_id != ''
			  AND s.timetable_subject_id IS NOT NULL
			  AND s.timetable_subject_id != ''
		""", {
			"campus_id": self.session.campus_id,
			"education_stage_id": self.session.education_stage_id,
		}, as_dict=True)

		assignments = []
		for r in rows:
			weekdays = []
			if r.get("weekdays"):
				try:
					weekdays = json.loads(r["weekdays"]) if isinstance(r["weekdays"], str) else r["weekdays"]
				except (json.JSONDecodeError, TypeError):
					weekdays = []

			assignments.append(TeacherAssignment(
				teacher_id=r["teacher_id"],
				class_id=r["class_id"],
				timetable_subject_id=r["timetable_subject_id"],
				weekdays=weekdays if weekdays else [],
			))

		return assignments

	def _parse_soft_rules(self) -> SoftRules:
		"""Parse soft rules JSON từ session."""
		if not self.session.soft_rules:
			return SoftRules()

		try:
			data = json.loads(self.session.soft_rules) if isinstance(self.session.soft_rules, str) else self.session.soft_rules
		except (json.JSONDecodeError, TypeError):
			return SoftRules()

		return SoftRules(
			subject_pair_exclusions=data.get("subject_pair_exclusions", []),
			subject_time_preferences=data.get("subject_time_preferences", []),
			teacher_gap_minimization=data.get("teacher_gap_minimization", 50),
			workload_balance=data.get("workload_balance", 50),
			consecutive_bonus=data.get("consecutive_bonus", 80),
			homeroom_preference=data.get("homeroom_preference", 60),
		)

	def _get_working_days(self) -> List[str]:
		"""Lấy ngày làm việc từ soft rules hoặc default."""
		if self.session.soft_rules:
			try:
				data = json.loads(self.session.soft_rules) if isinstance(self.session.soft_rules, str) else self.session.soft_rules
				if "working_days" in data:
					return data["working_days"]
			except (json.JSONDecodeError, TypeError):
				pass
		return ["mon", "tue", "wed", "thu", "fri"]

	def _build_indexes(self, inp: TimetableInput):
		"""Build derived indexes cho solver truy xuất nhanh."""
		# class -> grade
		inp.class_grade_map = {c.name: c.education_grade_id for c in inp.classes}

		# grade -> [timetable_subject_ids] (từ requirements)
		grade_subjects: Dict[str, List[str]] = {}
		for req in inp.requirements:
			grade_subjects.setdefault(req.education_grade_id, []).append(req.timetable_subject_id)
		inp.grade_subjects = grade_subjects

		# (class_id, timetable_subject_id) -> [teacher_ids]
		class_subject_teachers: Dict[str, List[str]] = {}
		for a in inp.assignments:
			key = f"{a.class_id}|{a.timetable_subject_id}"
			if key not in class_subject_teachers:
				class_subject_teachers[key] = []
			if a.teacher_id not in class_subject_teachers[key]:
				class_subject_teachers[key].append(a.teacher_id)
		inp.class_subject_teachers = class_subject_teachers
