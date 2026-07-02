"""
Data Collector - Thu thập toàn bộ dữ liệu cần cho solver từ 1 session.

Chỉ ĐỌC dữ liệu từ các doctype hiện có, KHÔNG sửa gì.
"""

import json
from typing import Dict, List, Optional, NamedTuple
from dataclasses import dataclass, field

import frappe

from .requirements_matrix import (
	LEGACY_DEFAULT_MAX_CONSECUTIVE,
	LEGACY_DEFAULT_MAX_PER_DAY,
	LEGACY_DEFAULT_MAX_PER_WEEK,
	compute_max_slots,
	resolve_teacher_period_limit,
)


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
	full_name: str = ""
	max_periods_per_day: int = 8
	max_periods_per_week: int = 24
	max_consecutive_periods: int = LEGACY_DEFAULT_MAX_CONSECUTIVE
	workload_spread_mode: str = "auto"  # auto | even | concentrated
	unavailable_slots: List[tuple] = field(default_factory=list)  # (day, period_idx, enforcement, weight)
	# Tier per-GV cho preference mềm của GV này (strong = khó thương lượng / weak = dễ).
	tier_max_consecutive: str = "weak"
	tier_avoid_gap: str = "weak"
	tier_balance: str = "weak"


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
	class_id: str
	periods_per_week: int
	max_periods_per_day: int = 2
	# Cặp tiết: '' | 'soft' | 'relaxable' | 'hard' (bool legacy vẫn nhận — True = hard).
	# Truthiness giữ nguyên cho consumer cũ: mode khác rỗng ~ "có cặp".
	force_pair: str | bool = False
	is_heavy: bool = False
	program_id: Optional[str] = None
	# Tier per-môn (từ SIS Timetable Subject) cho rải / tiết ưu tiên.
	tier_spread: str = "weak"
	tier_preferred: str = "weak"
	# Phân tầng per-cell: 'mandatory' (cứng = N) | 'relaxable' (cho thiếu, tính coverage).
	enforcement: str = "mandatory"
	enforcement_weight: int = 1


@dataclass
class TeacherAssignment:
	"""Mapping: (class, timetable_subject) -> teacher + weekdays"""
	teacher_id: str
	class_id: str
	timetable_subject_id: str
	weekdays: List[str]  # ["mon","tue",...] hoặc [] = tất cả


@dataclass
class PinnedSlotInfo:
	name: str = ""
	session_id: str = ""
	class_id: Optional[str] = None
	day_of_week: str = ""
	timetable_column_id: str = ""
	timetable_subject_id: Optional[str] = None
	teacher_id: Optional[str] = None
	room_id: Optional[str] = None
	is_blocking: bool = False
	note: str = ""
	# Per-pin enforcement: 'mandatory' (cứng) | 'relaxable' (pin mềm — ưu tiên, nới được).
	enforcement: str = "mandatory"
	weight: int = 5


@dataclass
class SoftRules:
	subject_pair_exclusions: List[Dict] = field(default_factory=list)
	subject_time_preferences: List[Dict] = field(default_factory=list)
	teacher_gap_minimization: int = 50
	workload_balance: int = 50
	homeroom_preference: int = 0


@dataclass
class TimetableInput:
	"""Toàn bộ input cho solver"""
	classes: List[ClassInfo] = field(default_factory=list)
	periods: List[PeriodInfo] = field(default_factory=list)
	teachers: Dict[str, TeacherInfo] = field(default_factory=dict)
	rooms: List[RoomInfo] = field(default_factory=list)
	requirements: List[SubjectRequirement] = field(default_factory=list)
	assignments: List[TeacherAssignment] = field(default_factory=list)
	pinned_slots: List[PinnedSlotInfo] = field(default_factory=list)
	soft_rules: SoftRules = field(default_factory=SoftRules)
	working_days: List[str] = field(default_factory=lambda: ["mon", "tue", "wed", "thu", "fri"])
	solver_time_limit: int = 120
	subject_is_homeroom: Dict[str, bool] = field(default_factory=dict)
	subject_allowed_room_ids: Dict[str, List[str]] = field(default_factory=dict)

	# Derived indexes (sẽ được build sau collect)
	class_grade_map: Dict[str, str] = field(default_factory=dict)
	class_subjects: Dict[str, List[str]] = field(default_factory=dict)
	class_subject_teachers: Dict[str, List[str]] = field(default_factory=dict)
	column_period_index: Dict[str, int] = field(default_factory=dict)
	subject_is_heavy: Dict[str, bool] = field(default_factory=dict)
	# Tier per-môn (ts_id -> 'strong'|'weak') cho rải / tiết ưu tiên.
	subject_tier_spread: Dict[str, str] = field(default_factory=dict)
	subject_tier_preferred: Dict[str, str] = field(default_factory=dict)


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
		inp.pinned_slots = self._get_pinned_slots()
		inp.soft_rules = self._parse_soft_rules()
		inp.working_days = self._get_working_days()
		inp.solver_time_limit = self.session.solver_time_limit or 120
		inp.subject_is_homeroom, inp.subject_allowed_room_ids = self._get_subject_room_config()

		self._build_indexes(inp)
		self._apply_schedule_teacher_limits(inp)
		return inp

	def _apply_schedule_teacher_limits(self, inp: TimetableInput) -> None:
		"""Mặc định max tiết GV theo khung giờ session (tiết/ngày × ngày/tuần)."""
		slot_meta = compute_max_slots(
			self.session.schedule_id,
			self.session.campus_id,
			self.session.education_stage_id,
		)
		per_day = len(inp.periods) or int(slot_meta.get("study_periods_per_day") or 10)
		per_week = per_day * len(inp.working_days)
		for teacher in inp.teachers.values():
			teacher.max_periods_per_day = resolve_teacher_period_limit(
				teacher.max_periods_per_day,
				per_day,
				legacy_default=LEGACY_DEFAULT_MAX_PER_DAY,
			)
			teacher.max_periods_per_week = resolve_teacher_period_limit(
				teacher.max_periods_per_week,
				per_week,
				legacy_default=LEGACY_DEFAULT_MAX_PER_WEEK,
			)

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
		"""Lấy GV theo campus, kèm config + slot bận theo rule set (single source)."""
		rows = frappe.db.sql(
			"""
			SELECT t.name, t.user_id,
			       COALESCE(NULLIF(u.full_name, ''), u.first_name, t.user_id, t.name) AS full_name
			FROM `tabSIS Teacher` t
			LEFT JOIN `tabUser` u ON u.name = t.user_id
			WHERE t.campus_id = %(campus_id)s
			""",
			{"campus_id": self.session.campus_id},
			as_dict=True,
		)

		teachers: Dict[str, TeacherInfo] = {
			r["name"]: TeacherInfo(
				name=r["name"],
				user_id=r.get("user_id") or r["name"],
				full_name=r.get("full_name") or r["name"],
				max_periods_per_day=0,
				max_periods_per_week=0,
				max_consecutive_periods=LEGACY_DEFAULT_MAX_CONSECUTIVE,
				workload_spread_mode="auto",
				tier_max_consecutive="weak",
				tier_avoid_gap="weak",
				tier_balance="weak",
			)
			for r in rows
		}

		rule_set_id = getattr(self.session, "rule_set_id", None) or None
		if (
			rule_set_id
			and teachers
			and frappe.db.table_exists("SIS Timetable Rule Set Teacher Config")
		):
			cfg_rows = frappe.db.sql(
				"""
				SELECT teacher_id, max_periods_per_day, max_periods_per_week,
				       max_consecutive_periods, workload_spread_mode,
				       tier_max_consecutive, tier_avoid_gap, tier_balance
				FROM `tabSIS Timetable Rule Set Teacher Config`
				WHERE rule_set_id = %(rule_set_id)s
				  AND teacher_id IN %(teacher_ids)s
				""",
				{"rule_set_id": rule_set_id, "teacher_ids": list(teachers.keys())},
				as_dict=True,
			)
			for row in cfg_rows:
				teacher = teachers.get(row.get("teacher_id"))
				if not teacher:
					continue
				teacher.max_periods_per_day = int(row.get("max_periods_per_day") or 0)
				teacher.max_periods_per_week = int(row.get("max_periods_per_week") or 0)
				teacher.max_consecutive_periods = int(row.get("max_consecutive_periods") or LEGACY_DEFAULT_MAX_CONSECUTIVE)
				teacher.workload_spread_mode = row.get("workload_spread_mode") or "auto"
				teacher.tier_max_consecutive = row.get("tier_max_consecutive") or "weak"
				teacher.tier_avoid_gap = row.get("tier_avoid_gap") or "weak"
				teacher.tier_balance = row.get("tier_balance") or "weak"

		if (
			rule_set_id
			and teachers
			and frappe.db.table_exists("SIS Teacher Unavailability")
			and frappe.db.has_column("SIS Teacher Unavailability", "rule_set_id")
			and frappe.db.has_column("SIS Teacher Unavailability", "teacher_id")
		):
			has_enf = frappe.db.has_column("SIS Teacher Unavailability", "enforcement")
			has_enf_w = frappe.db.has_column("SIS Teacher Unavailability", "weight")
			enf_sql = "COALESCE(enforcement, 'mandatory') as enforcement," if has_enf else "'mandatory' as enforcement,"
			enf_w_sql = "COALESCE(weight, 5) as weight," if has_enf_w else "5 as weight,"
			unavail_rows = frappe.db.sql(
				f"""
				SELECT teacher_id, day_of_week, timetable_column_id,
				       {enf_sql} {enf_w_sql} 1 as _ok
				FROM `tabSIS Teacher Unavailability`
				WHERE rule_set_id = %(rule_set_id)s
				  AND teacher_id IN %(ids)s
				""",
				{"rule_set_id": rule_set_id, "ids": list(teachers.keys())},
				as_dict=True,
			)

			period_map = {p.name: i for i, p in enumerate(
				sorted(self._get_periods(), key=lambda x: x.period_priority)
			)}
			for row in unavail_rows:
				teacher = teachers.get(row.get("teacher_id"))
				if not teacher:
					continue
				p_idx = period_map.get(row["timetable_column_id"])
				if p_idx is None:
					continue
				teacher.unavailable_slots.append((
					row["day_of_week"],
					p_idx,
					row.get("enforcement") or "mandatory",
					int(row.get("weight") or 5),
				))

		return teachers

	def _get_rooms(self) -> List[RoomInfo]:
		"""Lấy phòng theo campus."""
		rows = frappe.db.sql("""
			SELECT name, title_vn as title, room_type, COALESCE(capacity, 0) as capacity
			FROM `tabERP Administrative Room`
			WHERE campus_id = %(campus_id)s
		""", {"campus_id": self.session.campus_id}, as_dict=True)
		return [RoomInfo(**r) for r in rows]

	def _get_requirements(self) -> List[SubjectRequirement]:
		"""Lấy requirements từ session (class x timetable_subject -> periods_per_week)."""
		has_force_pair = frappe.db.has_column("SIS Timetable Generation Requirement", "force_pair")
		has_fp_mode = frappe.db.has_column("SIS Timetable Generation Requirement", "force_pair_mode")
		has_is_heavy = frappe.db.has_column("SIS Timetable Subject", "is_heavy")
		has_curriculum = frappe.db.has_column("SIS Timetable Subject", "curriculum_id")
		has_enforcement = frappe.db.has_column("SIS Timetable Generation Requirement", "enforcement")
		has_enf_weight = frappe.db.has_column("SIS Timetable Generation Requirement", "enforcement_weight")
		force_pair_sql = "COALESCE(r.force_pair, 0) as force_pair," if has_force_pair else "0 as force_pair,"
		force_pair_sql += (
			" COALESCE(r.force_pair_mode, '') as force_pair_mode,"
			if has_fp_mode else " '' as force_pair_mode,"
		)
		is_heavy_sql = "COALESCE(ts.is_heavy, 0) as is_heavy" if has_is_heavy else "0 as is_heavy"
		program_sql = "NULLIF(ts.curriculum_id, '') as program_id" if has_curriculum else "NULL as program_id"
		enforcement_sql = "COALESCE(r.enforcement, 'mandatory') as enforcement," if has_enforcement else "'mandatory' as enforcement,"
		enf_weight_sql = "COALESCE(r.enforcement_weight, 1) as enforcement_weight," if has_enf_weight else "1 as enforcement_weight,"
		has_t_spread = frappe.db.has_column("SIS Timetable Generation Requirement", "tier_spread")
		t_spread_sql = "COALESCE(NULLIF(r.tier_spread, ''), 'weak') as tier_spread," if has_t_spread else "'weak' as tier_spread,"

		rows = frappe.db.sql(f"""
			SELECT
				r.timetable_subject_id,
				ts.title_vn as timetable_subject_title,
				r.class_id,
				r.periods_per_week,
				r.max_periods_per_day,
				{t_spread_sql}
				{enforcement_sql}
				{enf_weight_sql}
				{force_pair_sql}
				{is_heavy_sql},
				{program_sql}
			FROM `tabSIS Timetable Generation Requirement` r
			JOIN `tabSIS Timetable Subject` ts ON ts.name = r.timetable_subject_id
			WHERE r.session_id = %(session_id)s
			  AND r.periods_per_week > 0
		""", {"session_id": self.session.name}, as_dict=True)

		return [SubjectRequirement(
			timetable_subject_id=r["timetable_subject_id"],
			timetable_subject_title=r["timetable_subject_title"],
			class_id=r["class_id"],
			periods_per_week=r["periods_per_week"],
			max_periods_per_day=r["max_periods_per_day"] or 2,
			# 3 nấc: '' | 'soft' | 'relaxable' | 'hard'; dữ liệu cũ chỉ có checkbox → hard.
			force_pair=(r.get("force_pair_mode") or ("hard" if r.get("force_pair") else "")),
			is_heavy=bool(r.get("is_heavy")),
			program_id=r.get("program_id") or None,
			tier_spread=r.get("tier_spread") or "weak",
			tier_preferred="weak",
			enforcement=r.get("enforcement") or "mandatory",
			enforcement_weight=int(r.get("enforcement_weight") or 1),
		) for r in rows]

	def _get_subject_room_config(self) -> tuple[Dict[str, bool], Dict[str, List[str]]]:
		"""Lấy cấu hình phòng theo môn TKB từ SIS Subject."""
		subject_is_homeroom: Dict[str, bool] = {}
		subject_allowed_room_ids: Dict[str, List[str]] = {}
		if not frappe.db.table_exists("SIS Subject"):
			return subject_is_homeroom, subject_allowed_room_ids
		has_is_homeroom = frappe.db.has_column("SIS Subject", "is_homeroom")
		is_homeroom_sql = "COALESCE(is_homeroom, 0)" if has_is_homeroom else "0"

		rows = frappe.db.sql("""
			SELECT name, timetable_subject_id, {is_homeroom_sql} AS is_homeroom, room_id
			FROM `tabSIS Subject`
			WHERE campus_id = %(campus_id)s
			  AND education_stage = %(education_stage_id)s
			  AND timetable_subject_id IS NOT NULL
			  AND timetable_subject_id != ''
		""".format(is_homeroom_sql=is_homeroom_sql), {
			"campus_id": self.session.campus_id,
			"education_stage_id": self.session.education_stage_id,
		}, as_dict=True)

		subject_doc_ids = [r["name"] for r in rows]
		allowed_map: Dict[str, List[str]] = {}
		if subject_doc_ids and frappe.db.table_exists("SIS Subject Room"):
			child_rows = frappe.db.sql("""
				SELECT parent, room_id
				FROM `tabSIS Subject Room`
				WHERE parent IN %(parents)s
				  AND room_id IS NOT NULL
				  AND room_id != ''
				ORDER BY idx ASC
			""", {"parents": subject_doc_ids}, as_dict=True)
			for row in child_rows:
				allowed_map.setdefault(row["parent"], []).append(row["room_id"])

		for row in rows:
			ts_id = row["timetable_subject_id"]
			subject_is_homeroom[ts_id] = bool(row.get("is_homeroom"))
			allowed = list(dict.fromkeys(allowed_map.get(row["name"], [])))
			if not allowed and row.get("room_id"):
				allowed = [row["room_id"]]
			if allowed:
				subject_allowed_room_ids[ts_id] = allowed

		return subject_is_homeroom, subject_allowed_room_ids

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
			  AND sa.school_year_id = %(school_year_id)s
			  AND sa.class_id IS NOT NULL
			  AND sa.class_id != ''
			  AND s.timetable_subject_id IS NOT NULL
			  AND s.timetable_subject_id != ''
		""", {
			"campus_id": self.session.campus_id,
			"education_stage_id": self.session.education_stage_id,
			"school_year_id": self.session.school_year_id,
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

	def _get_pinned_slots(self) -> List[PinnedSlotInfo]:
		"""Lấy tiết cố định của session (nếu DocType đã migrate)."""
		if not frappe.db.table_exists("SIS Timetable Pinned Slot"):
			return []

		has_enf = frappe.db.has_column("SIS Timetable Pinned Slot", "enforcement")
		has_w = frappe.db.has_column("SIS Timetable Pinned Slot", "weight")
		enf_sql = "COALESCE(enforcement, 'mandatory') as enforcement," if has_enf else "'mandatory' as enforcement,"
		w_sql = "COALESCE(weight, 5) as weight," if has_w else "5 as weight,"

		rows = frappe.db.sql(f"""
			SELECT name, session_id, class_id, day_of_week, timetable_column_id,
				   timetable_subject_id, teacher_id, room_id, is_blocking,
				   {enf_sql} {w_sql} note
			FROM `tabSIS Timetable Pinned Slot`
			WHERE session_id = %(session_id)s
		""", {"session_id": self.session.name}, as_dict=True)

		return [PinnedSlotInfo(**r) for r in rows]

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
			homeroom_preference=data.get("homeroom_preference", 0),
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

		# column -> period index
		for i, p in enumerate(sorted(inp.periods, key=lambda x: x.period_priority)):
			inp.column_period_index[p.name] = i

		# class -> [timetable_subject_ids] (từ requirements)
		class_subjects: Dict[str, List[str]] = {}
		inp.subject_is_heavy = {}
		for req in inp.requirements:
			class_subjects.setdefault(req.class_id, []).append(req.timetable_subject_id)
			inp.subject_is_heavy[req.timetable_subject_id] = req.is_heavy
			inp.subject_tier_spread[req.timetable_subject_id] = req.tier_spread
			inp.subject_tier_preferred[req.timetable_subject_id] = req.tier_preferred
		inp.class_subjects = class_subjects

		# (class_id, timetable_subject_id) -> [teacher_ids]
		class_subject_teachers: Dict[str, List[str]] = {}
		for a in inp.assignments:
			key = f"{a.class_id}|{a.timetable_subject_id}"
			if key not in class_subject_teachers:
				class_subject_teachers[key] = []
			if a.teacher_id not in class_subject_teachers[key]:
				class_subject_teachers[key].append(a.teacher_id)
		inp.class_subject_teachers = class_subject_teachers
