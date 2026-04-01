"""
Dọn bản ghi SIS Class Attendance trùng (student_id, class_id, date, period)
rồi thêm UNIQUE INDEX ngăn tái phát.

Với mỗi nhóm trùng: giữ bản có creation sớm nhất, xoá phần còn lại.

Created: 2026-04-01
"""

import frappe


def execute():
	if not frappe.db.table_exists("SIS Class Attendance"):
		return

	# Bước 1: Tìm và xoá bản ghi trùng — giữ bản có name nhỏ nhất (creation sớm nhất)
	duplicates = frappe.db.sql("""
		SELECT t.name
		FROM `tabSIS Class Attendance` t
		INNER JOIN (
			SELECT student_id, class_id, `date`, period, MIN(name) AS keep_name
			FROM `tabSIS Class Attendance`
			GROUP BY student_id, class_id, `date`, period
			HAVING COUNT(*) > 1
		) dup
			ON  dup.student_id = t.student_id
			AND dup.class_id   = t.class_id
			AND dup.date       = t.date
			AND dup.period     = t.period
		WHERE t.name != dup.keep_name
	""", as_dict=True)

	deleted = len(duplicates)
	if deleted:
		names = [d["name"] for d in duplicates]
		# Xoá theo batch 500 để tránh query quá dài
		batch_size = 500
		for i in range(0, len(names), batch_size):
			batch = names[i:i + batch_size]
			placeholders = ", ".join(["%s"] * len(batch))
			frappe.db.sql(
				f"DELETE FROM `tabSIS Class Attendance` WHERE name IN ({placeholders})",
				tuple(batch),
			)
		frappe.db.commit()
		frappe.logger().info(
			f"[dedup_class_attendance] Đã xoá {deleted} bản ghi trùng"
		)
	else:
		frappe.logger().info("[dedup_class_attendance] Không có bản ghi trùng")

	# Bước 2: Thêm UNIQUE INDEX
	idx_name = "uq_student_class_date_period"
	existing = frappe.db.sql(
		"SHOW INDEX FROM `tabSIS Class Attendance` WHERE Key_name = %s",
		(idx_name,),
		as_dict=True,
	)
	if not existing:
		try:
			frappe.db.sql(f"""
				CREATE UNIQUE INDEX `{idx_name}`
				ON `tabSIS Class Attendance` (student_id, class_id, `date`, period)
			""")
			frappe.db.commit()
			frappe.logger().info(
				f"[dedup_class_attendance] Đã tạo UNIQUE INDEX {idx_name}"
			)
		except Exception as e:
			if "Duplicate entry" in str(e):
				frappe.logger().error(
					"[dedup_class_attendance] Vẫn còn trùng sau khi dọn — kiểm tra lại dữ liệu"
				)
				raise
			raise
	else:
		frappe.logger().info(f"[dedup_class_attendance] Index {idx_name} đã tồn tại")
