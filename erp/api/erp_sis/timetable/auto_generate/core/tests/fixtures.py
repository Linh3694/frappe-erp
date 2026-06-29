"""Fixture pytest — không cần bench/frappe."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class ClassInfo:
	name: str
	title: str
	education_grade_id: str
	room_id: Optional[str] = None


@dataclass
class PeriodInfo:
	name: str
	period_name: str
	period_priority: int
	period_type: str = "study"
	start_time: str = "07:00"
	end_time: str = "07:45"


@dataclass
class TeacherInfo:
	name: str
	user_id: str = ""
	max_periods_per_day: int = 8
	max_periods_per_week: int = 24
	max_consecutive_periods: int = 10
	workload_spread_mode: str = "auto"
	unavailable_slots: list = field(default_factory=list)
	tier_max_consecutive: str = "weak"
	tier_avoid_gap: str = "weak"
	tier_balance: str = "weak"


@dataclass
class SubjectRequirement:
	timetable_subject_id: str
	timetable_subject_title: str
	class_id: str
	periods_per_week: int
	max_periods_per_day: int = 2
	force_pair: bool = False
	is_heavy: bool = False
	program_id: Optional[str] = None
	tier_spread: str = "weak"
	tier_preferred: str = "weak"
	enforcement: str = "mandatory"
	enforcement_weight: int = 1


@dataclass
class SoftRules:
	teacher_gap_minimization: int = 0
	workload_balance: int = 0
	homeroom_preference: int = 0
	subject_pair_exclusions: list = field(default_factory=list)
	subject_time_preferences: list = field(default_factory=list)


@dataclass
class TimetableInput:
	classes: List[ClassInfo] = field(default_factory=list)
	periods: List[PeriodInfo] = field(default_factory=list)
	teachers: Dict[str, TeacherInfo] = field(default_factory=dict)
	rooms: list = field(default_factory=list)
	requirements: List[SubjectRequirement] = field(default_factory=list)
	assignments: list = field(default_factory=list)
	pinned_slots: list = field(default_factory=list)
	soft_rules: SoftRules = field(default_factory=SoftRules)
	working_days: List[str] = field(default_factory=lambda: ["mon", "tue", "wed", "thu", "fri"])
	solver_time_limit: int = 30
	class_subjects: Dict[str, List[str]] = field(default_factory=dict)
	class_subject_teachers: Dict[str, List[str]] = field(default_factory=dict)
	column_period_index: Dict[str, int] = field(default_factory=dict)
	subject_is_heavy: Dict[str, bool] = field(default_factory=dict)


def tiny_input() -> TimetableInput:
	inp = TimetableInput(
		classes=[ClassInfo("C1", "Lớp 1", "G1", "R1")],
		periods=[
			PeriodInfo("P1", "Tiết 1", 1),
			PeriodInfo("P2", "Tiết 2", 2),
			PeriodInfo("P3", "Tiết 3", 3),
			PeriodInfo("P4", "Tiết 4", 4),
		],
		teachers={"T1": TeacherInfo("T1")},
		requirements=[
			SubjectRequirement("M1", "Toán", "C1", 4),
			SubjectRequirement("M2", "Văn", "C1", 4),
		],
		working_days=["mon", "tue", "wed", "thu", "fri"],
	)
	inp.class_subjects = {"C1": ["M1", "M2"]}
	inp.class_subject_teachers = {"C1|M1": ["T1"], "C1|M2": ["T1"]}
	inp.column_period_index = {"P1": 0, "P2": 1, "P3": 2, "P4": 3}
	return inp
