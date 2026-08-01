# Copyright (c) 2025, Wellspring International School and contributors
# For license information, please see license.txt

"""
Tra cứu lớp chủ nhiệm (lớp chính quy) của học sinh.

Vì sao cần module riêng: bản ghi `SIS Class Student` được giữ lại theo TỪNG NĂM HỌC làm
lịch sử — quy tắc "một lớp regular / học sinh / năm học" ở
`erp.api.erp_sis.class_student.assign_student` chỉ đè dòng cũ khi chuyển lớp TRONG CÙNG
năm; sang năm mới thì insert dòng mới và giữ nguyên dòng năm cũ. Vì vậy mọi truy vấn
`SIS Class Student` chỉ lọc theo `student_id` đều trả về cả lớp của các năm trước, dẫn
tới gửi thông báo cho GVCN cũ hoặc ghi điểm danh vào lớp cũ (SIS-175).

Ngoài ra học sinh còn có thể thuộc lớp chạy (`mixed`) và câu lạc bộ (`club`) — các lớp
này cũng có trường `homeroom_teacher` nhưng người đó KHÔNG phải giáo viên chủ nhiệm.

Hai điều kiện `school_year_id` + `class_type = 'regular'` phải luôn đi cùng nhau.
"""

import frappe


def resolve_school_year_for_date(date_str, campus_id=None):
	"""Năm học phủ ngày `date_str`.

	Ưu tiên năm học của campus; không có thì bỏ ràng buộc campus (dữ liệu năm học cũ
	có thể chưa gán campus). Trả về None nếu không năm nào phủ ngày đó.
	"""
	if not date_str:
		return None

	filters = {
		"start_date": ["<=", date_str],
		"end_date": [">=", date_str],
	}

	if campus_id:
		rows = frappe.get_all(
			"SIS School Year",
			filters={**filters, "campus_id": campus_id},
			fields=["name"],
			order_by="start_date desc",
			limit=1,
		)
		if rows:
			return rows[0].name

	rows = frappe.get_all(
		"SIS School Year",
		filters=filters,
		fields=["name"],
		order_by="start_date desc",
		limit=1,
	)
	return rows[0].name if rows else None


def resolve_active_school_year(campus_id=None):
	"""Năm học đang bật (`is_enable = 1`), ưu tiên theo campus."""
	if campus_id:
		rows = frappe.get_all(
			"SIS School Year",
			filters={"is_enable": 1, "campus_id": campus_id},
			fields=["name"],
			order_by="start_date desc",
			limit=1,
		)
		if rows:
			return rows[0].name

	rows = frappe.get_all(
		"SIS School Year",
		filters={"is_enable": 1},
		fields=["name"],
		order_by="start_date desc",
		limit=1,
	)
	return rows[0].name if rows else None


def get_regular_class_row(student_id, school_year_id=None, campus_id=None, on_date=None):
	"""Lớp chính quy của học sinh trong đúng một năm học.

	Args:
		student_id: mã học sinh (CRM Student)
		school_year_id: chỉ định năm học; bỏ trống thì tự resolve
		campus_id: campus để ưu tiên khi resolve năm học; bỏ trống thì lấy từ CRM Student
		on_date: resolve năm học theo ngày này (YYYY-MM-DD) trước, rồi mới tới năm đang bật.
			Dùng cho dữ liệu lịch sử — đơn nghỉ phép không lưu năm học nên phải suy ra.

	Returns:
		dict {class_id, class_title, homeroom_teacher, vice_homeroom_teacher, school_year_id}
		hoặc None nếu học sinh không có lớp chính quy trong năm học đó.
	"""
	if not student_id:
		return None

	if not school_year_id:
		if not campus_id:
			campus_id = frappe.db.get_value("CRM Student", student_id, "campus_id")
		if on_date:
			school_year_id = resolve_school_year_for_date(on_date, campus_id)
		if not school_year_id:
			school_year_id = resolve_active_school_year(campus_id)

	if not school_year_id:
		frappe.logger().warning(
			f"⚠️ [StudentClass] Không xác định được năm học cho học sinh {student_id} "
			f"(campus={campus_id}, on_date={on_date})"
		)
		return None

	# ORDER BY xác định: trong một năm học chỉ nên có 1 lớp regular, nhưng nếu dữ liệu
	# lỡ có nhiều dòng thì vẫn phải chọn ổn định thay vì phó mặc storage engine.
	rows = frappe.db.sql(
		"""
		SELECT
			c.name AS class_id,
			c.title AS class_title,
			c.homeroom_teacher,
			c.vice_homeroom_teacher,
			cs.school_year_id
		FROM `tabSIS Class Student` cs
		INNER JOIN `tabSIS Class` c ON c.name = cs.class_id
		WHERE cs.student_id = %(sid)s
			AND cs.school_year_id = %(sy)s
			AND c.class_type = 'regular'
		ORDER BY cs.modified DESC, cs.name DESC
		LIMIT 1
		""",
		{"sid": student_id, "sy": school_year_id},
		as_dict=True,
	)

	if not rows:
		frappe.logger().info(
			f"📚 [StudentClass] Học sinh {student_id} không có lớp chính quy "
			f"trong năm học {school_year_id}"
		)
		return None

	return rows[0]


def get_homeroom_teacher_users(student_id, school_year_id=None, campus_id=None, on_date=None):
	"""GVCN + phó GVCN (kèm user_id) của lớp chính quy học sinh đang học.

	Returns:
		List[dict]: [{user_id, teacher_id, teacher_name, class_id, class_title}]
		Rỗng nếu không có lớp chính quy hợp lệ — KHÔNG fallback sang lớp năm cũ.
	"""
	row = get_regular_class_row(
		student_id,
		school_year_id=school_year_id,
		campus_id=campus_id,
		on_date=on_date,
	)
	if not row:
		return []

	result = []
	seen_users = set()

	for teacher_id in (row.get("homeroom_teacher"), row.get("vice_homeroom_teacher")):
		if not teacher_id:
			continue

		user_id = frappe.db.get_value("SIS Teacher", teacher_id, "user_id")
		if not user_id or user_id in seen_users:
			continue

		seen_users.add(user_id)
		result.append({
			"user_id": user_id,
			"teacher_id": teacher_id,
			"teacher_name": frappe.db.get_value("User", user_id, "full_name") or user_id,
			"class_id": row.get("class_id"),
			"class_title": row.get("class_title") or "",
		})

	return result
