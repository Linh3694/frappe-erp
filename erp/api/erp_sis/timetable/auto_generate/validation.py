"""Validation dùng chung cho validate_session API và solver."""

from typing import Dict, List, Tuple

from .data_collector import TeacherInfo, TimetableInput


def _teacher_label(t_id: str, teachers: Dict[str, TeacherInfo]) -> str:
	"""Nhãn GV: tên hiển thị kèm ID DocType."""
	teacher = teachers.get(t_id)
	if not teacher:
		return t_id
	name = (teacher.full_name or "").strip()
	if name and name not in (t_id, teacher.user_id):
		return f"{name} ({t_id})"
	return t_id


def validate_timetable_input(inp: TimetableInput) -> Tuple[List[str], List[str]]:
	"""Trả về (errors, warnings). Errors chặn solve."""
	errors: List[str] = []
	warnings: List[str] = []

	if not inp.classes:
		errors.append("Không tìm thấy lớp nào trong phạm vi đã chọn")
	if not inp.periods:
		errors.append("Không tìm thấy tiết học nào trong schedule đã chọn")
	if not inp.requirements:
		errors.append("Chưa có yêu cầu số tiết/tuần nào")

	num_periods = len(inp.periods)
	num_days = len(inp.working_days)
	max_slots_per_week = num_periods * num_days
	room_by_id = {r.name: r for r in inp.rooms}
	req_map = {(r.class_id, r.timetable_subject_id): r for r in inp.requirements}

	# Lớp thiếu GV + tổng tiết vượt capacity
	for c in inp.classes:
		total_required = 0
		for ts_id in inp.class_subjects.get(c.name, []):
			req = req_map.get((c.name, ts_id))
			if req:
				total_required += req.periods_per_week
			key_a = f"{c.name}|{ts_id}"
			teachers = inp.class_subject_teachers.get(key_a, [])
			if not teachers and req and req.periods_per_week > 0:
				subject_name = req.timetable_subject_title or ts_id
				# Chưa phân công GV vẫn cho xếp TKB — chỉ cảnh báo
				warnings.append(f"Lớp {c.title} chưa có GV phân công cho môn {subject_name}")

		if total_required > max_slots_per_week:
			errors.append(
				f"Lớp {c.title}: tổng yêu cầu {total_required} tiết/tuần "
				f"vượt khả năng {max_slots_per_week} slot ({num_periods} tiết x {num_days} ngày)"
			)

	# GV quá tải tuần
	teacher_weekly_load = {}
	for c in inp.classes:
		for ts_id in inp.class_subjects.get(c.name, []):
			req = req_map.get((c.name, ts_id))
			if not req or req.periods_per_week <= 0:
				continue
			key_a = f"{c.name}|{ts_id}"
			for t_id in inp.class_subject_teachers.get(key_a, []):
				teacher_weekly_load[t_id] = teacher_weekly_load.get(t_id, 0) + req.periods_per_week

	for t_id, load in teacher_weekly_load.items():
		teacher = inp.teachers.get(t_id)
		if not teacher:
			continue
		max_week = teacher.max_periods_per_week or max_slots_per_week
		max_day = teacher.max_periods_per_day or num_periods
		gv = _teacher_label(t_id, inp.teachers)
		if load > max_week:
			errors.append(
				f"GV {gv}: tổng {load} tiết/tuần vượt giới hạn {max_week}"
			)
		if load > max_day * num_days:
			errors.append(
				f"GV {gv}: tổng {load} tiết/tuần không thể xếp với tối đa "
				f"{max_day} tiết/ngày x {num_days} ngày"
			)

	# room_type_required: phải có ít nhất 1 phòng loại đó trong campus
	room_types_available = {r.room_type for r in inp.rooms if r.room_type}
	for req in inp.requirements:
		if not req.room_type_required:
			continue
		if req.room_type_required not in room_types_available:
			# Rule room_type_match đang tắt — chỉ cảnh báo, không chặn solve
			warnings.append(
				f"Môn {req.timetable_subject_title}: yêu cầu phòng loại "
				f"'{req.room_type_required}' nhưng campus chưa có phòng loại này"
			)

	# Xung đột pinned slot cùng lớp + slot
	seen_pins = {}
	for pin in inp.pinned_slots:
		target_classes = [c.name for c in inp.classes] if not pin.class_id else [pin.class_id]
		p_idx = inp.column_period_index.get(pin.timetable_column_id)
		if p_idx is None:
			warnings.append(f"Pinned slot {pin.name or ''}: cột {pin.timetable_column_id} không thuộc schedule session")
			continue
		for c_id in target_classes:
			key = (c_id, pin.day_of_week, p_idx)
			if key in seen_pins:
				errors.append(
					f"Xung đột pinned slot: lớp {c_id} ngày {pin.day_of_week} tiết {p_idx} "
					f"bị pin 2 lần"
				)
			seen_pins[key] = pin

	return errors, warnings
