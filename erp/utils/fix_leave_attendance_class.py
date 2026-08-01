#!/usr/bin/env python3
# Copyright (c) 2025, Wellspring International School and contributors
# For license information, please see license.txt

"""
Rà soát và sửa bản ghi SIS Class Attendance sinh từ đơn nghỉ phép bị gán sai lớp (SIS-178).

Trước bản sửa SIS-177, `sync_to_attendance` chọn lớp bằng query chỉ lọc `student_id`,
không lọc năm học / `class_type` và không có ORDER BY (frappe mặc định
KEEP_DEFAULT_ORDERING) ⇒ bản ghi "excused" có thể rơi vào lớp năm học cũ hoặc lớp chạy.
Lớp chủ nhiệm hiện tại không thấy học sinh nghỉ phép nên dễ bị chấm vắng không phép.

Lớp đúng được xác định theo năm học phủ ĐÚNG NGÀY của từng bản ghi (không dùng năm đang
bật), vì đây là dữ liệu lịch sử trải qua nhiều năm học.

Usage (from bench console):
    from erp.utils.fix_leave_attendance_class import check_leave_attendance_class, fix_leave_attendance_class

    # 1. Dry-run: chỉ đọc và in báo cáo, không ghi gì
    check_leave_attendance_class()

    # 2. Chạy thật (sau khi đã xem báo cáo và bản sửa SIS-177 đã lên production)
    fix_leave_attendance_class(confirm=True)

    # 3. Dry-run lại để xác nhận còn 0 bản ghi cần sửa
    check_leave_attendance_class()
"""

import re

import frappe

from erp.utils.student_class import get_regular_class_row

# Khớp đuôi "(ID: <leave_request_id>)" do sync_to_attendance ghi vào remarks.
_LEAVE_ID_PATTERN = re.compile(r"\(ID:\s*([^)]+)\)")

# Số bản ghi in ra làm mẫu cho mỗi nhóm khi báo cáo.
_SAMPLE_SIZE = 10


def _fetch_leave_attendance_rows():
	"""Mọi bản ghi điểm danh sinh tự động từ đơn nghỉ phép."""
	return frappe.db.sql(
		"""
		SELECT name, student_id, student_name, class_id, date, period, status, remarks, campus_id
		FROM `tabSIS Class Attendance`
		WHERE remarks LIKE %(pattern)s
		ORDER BY date DESC, name DESC
		""",
		{"pattern": "Đơn nghỉ phép:%(ID: %"},
		as_dict=True,
	)


def _leave_request_id_from_remarks(remarks):
	match = _LEAVE_ID_PATTERN.search(remarks or "")
	return match.group(1).strip() if match else None


def _classify(row, correct_row, current_class):
	"""Phân loại nguyên nhân sai để báo cáo cho người vận hành."""
	if not correct_row:
		return "unresolved"
	if row.get("class_id") == correct_row.get("class_id"):
		return "ok"
	if not current_class:
		return "wrong_missing_class"
	if (current_class.get("class_type") or "regular") != "regular":
		return "wrong_non_regular"
	if current_class.get("school_year_id") != correct_row.get("school_year_id"):
		return "wrong_old_year"
	return "wrong_other"


def _analyze():
	"""Quét toàn bộ và trả về (buckets, plan) — không ghi gì.

	buckets: dict nhóm -> list bản ghi (để báo cáo)
	plan:    list hành động cần thực hiện khi chạy thật
	"""
	rows = _fetch_leave_attendance_rows()

	buckets = {
		"ok": [],
		"wrong_old_year": [],
		"wrong_non_regular": [],
		"wrong_missing_class": [],
		"wrong_other": [],
		"unresolved": [],
	}
	plan = []
	class_cache = {}
	correct_cache = {}

	for row in rows:
		current_class = None
		if row.get("class_id"):
			if row["class_id"] not in class_cache:
				class_cache[row["class_id"]] = frappe.db.get_value(
					"SIS Class",
					row["class_id"],
					["name", "title", "class_type", "school_year_id"],
					as_dict=True,
				)
			current_class = class_cache[row["class_id"]]

		cache_key = (row.get("student_id"), str(row.get("date")))
		if cache_key not in correct_cache:
			correct_cache[cache_key] = get_regular_class_row(
				row.get("student_id"),
				campus_id=row.get("campus_id"),
				on_date=str(row.get("date")),
			)
		correct_row = correct_cache[cache_key]

		bucket = _classify(row, correct_row, current_class)
		entry = {
			"name": row["name"],
			"student_id": row.get("student_id"),
			"student_name": row.get("student_name"),
			"date": str(row.get("date")),
			"period": row.get("period"),
			"status": row.get("status"),
			"leave_request_id": _leave_request_id_from_remarks(row.get("remarks")),
			"current_class_id": row.get("class_id"),
			"current_class_title": (current_class or {}).get("title"),
			"current_class_type": (current_class or {}).get("class_type"),
			"correct_class_id": (correct_row or {}).get("class_id"),
			"correct_class_title": (correct_row or {}).get("class_title"),
		}
		buckets[bucket].append(entry)

		if bucket in ("ok", "unresolved"):
			continue

		# Lớp đúng đã có bản ghi cùng (student, date, period) ⇒ gộp: giữ bản ghi ở lớp
		# đúng, xoá bản ghi lạc. Không đè status của bản ghi đích vì đó có thể là kết quả
		# giáo viên tự điểm danh.
		existing = frappe.db.get_value(
			"SIS Class Attendance",
			{
				"student_id": row.get("student_id"),
				"class_id": correct_row.get("class_id"),
				"date": row.get("date"),
				"period": row.get("period"),
			},
			["name", "status"],
			as_dict=True,
		)

		if existing:
			entry["action"] = "delete_duplicate"
			entry["target_name"] = existing["name"]
			entry["target_status"] = existing["status"]
			entry["status_conflict"] = existing["status"] != row.get("status")
		else:
			entry["action"] = "move"

		plan.append(entry)

	return buckets, plan


def _print_report(buckets, plan):
	labels = {
		"ok": "Đúng lớp (bỏ qua)",
		"wrong_old_year": "SAI: lớp thuộc năm học khác",
		"wrong_non_regular": "SAI: lớp không phải lớp chính quy (lớp chạy/CLB)",
		"wrong_missing_class": "SAI: lớp đang gán không còn tồn tại",
		"wrong_other": "SAI: khác lớp đúng (nguyên nhân khác)",
		"unresolved": "KHÔNG XÁC ĐỊNH được lớp đúng (chỉ báo cáo, không đụng)",
	}

	total = sum(len(v) for v in buckets.values())
	print(f"\n=== Rà soát điểm danh sinh từ đơn nghỉ phép: {total} bản ghi ===")
	for key, label in labels.items():
		entries = buckets[key]
		print(f"  {label}: {len(entries)}")
		for entry in entries[:_SAMPLE_SIZE]:
			print(
				f"    - {entry['date']} {entry['student_name'] or entry['student_id']}"
				f" | lớp đang gán: {entry['current_class_title'] or entry['current_class_id']}"
				f" ({entry['current_class_type']})"
				f" -> lớp đúng: {entry['correct_class_title'] or entry['correct_class_id']}"
			)
		if len(entries) > _SAMPLE_SIZE:
			print(f"    ... còn {len(entries) - _SAMPLE_SIZE} bản ghi nữa (chỉ in {_SAMPLE_SIZE} mẫu đầu)")

	moves = [e for e in plan if e.get("action") == "move"]
	dups = [e for e in plan if e.get("action") == "delete_duplicate"]
	conflicts = [e for e in dups if e.get("status_conflict")]

	print(f"\n--- Kế hoạch sửa: {len(plan)} bản ghi ---")
	print(f"  Chuyển sang lớp đúng: {len(moves)}")
	print(f"  Xoá vì lớp đúng đã có bản ghi: {len(dups)}")
	if conflicts:
		print(
			f"  ⚠️  Trong đó {len(conflicts)} bản ghi mà lớp đúng đang có status KHÁC "
			f"(giáo viên đã tự điểm danh) — giữ nguyên status của lớp đúng:"
		)
		for entry in conflicts[:_SAMPLE_SIZE]:
			print(
				f"    - {entry['date']} {entry['student_name'] or entry['student_id']}"
				f" | đơn nghỉ: {entry['status']} vs lớp đúng: {entry['target_status']}"
			)
		if len(conflicts) > _SAMPLE_SIZE:
			print(f"    ... còn {len(conflicts) - _SAMPLE_SIZE} bản ghi nữa")

	return {
		"total": total,
		"counts": {key: len(value) for key, value in buckets.items()},
		"to_move": len(moves),
		"to_delete": len(dups),
		"status_conflicts": len(conflicts),
	}


def check_leave_attendance_class():
	"""Dry-run: chỉ đọc, in báo cáo phân loại và kế hoạch sửa."""
	buckets, plan = _analyze()
	summary = _print_report(buckets, plan)
	print("\n(dry-run — chưa ghi gì. Chạy fix_leave_attendance_class(confirm=True) để sửa thật)\n")
	return summary


def fix_leave_attendance_class(confirm=False):
	"""Sửa thật các bản ghi bị gán sai lớp.

	Args:
		confirm: bắt buộc True mới ghi. Mặc định False để tránh chạy nhầm.
	"""
	buckets, plan = _analyze()
	summary = _print_report(buckets, plan)

	if not confirm:
		print("\n⚠️  confirm=False — không ghi gì. Gọi lại với confirm=True để thực hiện.\n")
		return summary

	if not plan:
		print("\n✅ Không có bản ghi nào cần sửa.\n")
		return summary

	from erp.api.erp_sis.attendance import invalidate_class_attendance_cache

	moved = 0
	deleted = 0
	failed = []
	cache_targets = set()

	for entry in plan:
		try:
			if entry["action"] == "move":
				frappe.db.set_value(
					"SIS Class Attendance",
					entry["name"],
					"class_id",
					entry["correct_class_id"],
					update_modified=True,
				)
				moved += 1
			else:
				frappe.delete_doc(
					"SIS Class Attendance",
					entry["name"],
					force=True,
					ignore_permissions=True,
				)
				deleted += 1

			cache_targets.add((entry["current_class_id"], entry["date"], entry["period"]))
			cache_targets.add((entry["correct_class_id"], entry["date"], entry["period"]))

		except Exception as e:
			failed.append({"name": entry["name"], "error": str(e)})
			frappe.logger().error(f"❌ [FixLeaveAttendance] {entry['name']}: {str(e)}")

	frappe.db.commit()

	for class_id, date_str, period in cache_targets:
		try:
			invalidate_class_attendance_cache(class_id, date_str, period)
		except Exception as e:
			frappe.logger().warning(f"⚠️ [FixLeaveAttendance] Xoá cache thất bại {class_id}/{date_str}: {str(e)}")

	print(f"\n✅ Đã chuyển lớp: {moved} | đã xoá trùng: {deleted} | lỗi: {len(failed)}")
	if failed:
		print("Các bản ghi lỗi:")
		for item in failed[:_SAMPLE_SIZE]:
			print(f"  - {item['name']}: {item['error']}")
		if len(failed) > _SAMPLE_SIZE:
			print(f"  ... còn {len(failed) - _SAMPLE_SIZE} lỗi nữa")
	print(f"Đã xoá cache của {len(cache_targets)} tổ hợp (lớp, ngày, tiết).\n")

	summary["moved"] = moved
	summary["deleted"] = deleted
	summary["failed"] = len(failed)
	return summary
