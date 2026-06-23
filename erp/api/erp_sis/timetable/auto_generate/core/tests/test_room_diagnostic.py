"""Chẩn đoán thắt cổ chai phòng.

Trước đây: nhiều lớp tranh 1 phòng (room_eligibility + room_max=1) làm vô nghiệm,
nhưng nút "Phân tích mâu thuẫn" trả UNSAT core rỗng ("không khoanh được rule").
Sau khi nới room_eligibility/room_max trong chế độ chẩn đoán, diagnose phải:
  - giữ NGUYÊN độ cứng ở lần giải thật (vẫn INFEASIBLE),
  - nhưng định vị đúng lớp–môn thiếu phòng (room_ineligible / room limit), hết empty core.
"""

from __future__ import annotations

from core.diagnostics import diagnose_infeasibility
from core.runner import build_and_solve
from core.tests.fixtures import (
	ClassInfo,
	PeriodInfo,
	SubjectRequirement,
	TeacherInfo,
	TimetableInput,
)


class _Room:
	def __init__(self, name):
		self.name = name


def _room_bottleneck_input() -> TimetableInput:
	"""3 lớp đều cần môn LAB, chỉ 1 phòng RLAB hợp lệ, room_max=1, 1 ngày 2 tiết.

	Mỗi lớp phải xếp LAB cả 2 tiết → 3 lớp tranh 1 phòng → vô nghiệm vì phòng.
	"""
	inp = TimetableInput(
		classes=[
			ClassInfo("C1", "Lớp 1", "G1", "R1"),
			ClassInfo("C2", "Lớp 2", "G1", "R2"),
			ClassInfo("C3", "Lớp 3", "G1", "R3"),
		],
		periods=[PeriodInfo("P1", "Tiết 1", 1), PeriodInfo("P2", "Tiết 2", 2)],
		teachers={
			"T1": TeacherInfo("T1"),
			"T2": TeacherInfo("T2"),
			"T3": TeacherInfo("T3"),
		},
		requirements=[
			SubjectRequirement("LAB", "Thí nghiệm", "C1", 2),
			SubjectRequirement("LAB", "Thí nghiệm", "C2", 2),
			SubjectRequirement("LAB", "Thí nghiệm", "C3", 2),
		],
		working_days=["mon"],
	)
	inp.class_subjects = {"C1": ["LAB"], "C2": ["LAB"], "C3": ["LAB"]}
	inp.class_subject_teachers = {"C1|LAB": ["T1"], "C2|LAB": ["T2"], "C3|LAB": ["T3"]}
	inp.column_period_index = {"P1": 0, "P2": 1}
	inp.rooms = [_Room("RLAB")]
	inp.subject_is_homeroom = {"LAB": False}
	inp.subject_allowed_room_ids = {"LAB": ["RLAB"]}  # chỉ RLAB hợp lệ cho LAB
	return inp


def test_room_bottleneck_real_solve_stays_hard_infeasible():
	"""Lần giải thật KHÔNG nới phòng → vẫn INFEASIBLE (rule cứng giữ nguyên)."""
	inp = _room_bottleneck_input()
	_solver, _builder, status, _ctx = build_and_solve(inp, diagnostic=False)
	assert status == "INFEASIBLE"


def test_room_bottleneck_diagnose_locates_room_not_empty_core():
	"""Chẩn đoán nới được thành nghiệm và chỉ đúng thủ phạm = phòng (hết empty core)."""
	inp = _room_bottleneck_input()
	report = diagnose_infeasibility(inp)

	assert report["feasible_relaxed"] is True
	# Không còn rơi vào nhánh UNSAT-core rỗng.
	assert not report.get("conflict_core")

	room_inelig = report.get("room_ineligible") or []
	room_limit = [
		lv for lv in report.get("limit_violations", [])
		if str(lv.get("tag", "")).startswith("room:")
	]
	assert room_inelig or room_limit, "phải định vị được vi phạm phòng"

	# Vi phạm phòng phải gắn đúng lớp đang tranh phòng.
	if room_inelig:
		assert {r["class_id"] for r in room_inelig} <= {"C1", "C2", "C3"}
		assert all(r["subject_id"] == "LAB" for r in room_inelig)

	msgs = " ".join(s.get("message", "") for s in report.get("suspects", []))
	assert "phòng" in msgs.lower()
