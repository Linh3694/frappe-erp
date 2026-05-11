"""
Tối ưu index cho 3 bảng nóng — giảm P95 các API:
  - SIS Class Log Subject:  (class_id, log_date)                       → save_contact_log, get_contact_log_status
  - SIS Class Log Subject:  (timetable_instance_id, log_date, period)  → save_class_log
  - SIS Class Log Student:  (subject_id, student_id)                   → save_contact_log, save_class_log (UPSERT)
  - SIS Class Attendance:   (class_id, date, period)                   → get_class_attendance & batch_*

Lưu ý: UNIQUE INDEX (student_id, class_id, date, period) đã có từ patch
`dedup_class_attendance_add_unique_index` nhưng vì `student_id` đứng đầu
nên KHÔNG dùng được khi filter chỉ có (class_id, date, period).

Created: 2026-05-11
"""

import frappe


# (table_name, index_name, "col1, col2, ...", is_unique)
INDEX_SPECS = [
    ("tabSIS Class Log Subject", "idx_class_logdate", "class_id, log_date", False),
    ("tabSIS Class Log Subject", "idx_inst_date_period", "timetable_instance_id, log_date, period", False),
    ("tabSIS Class Log Student", "uq_subject_student", "subject_id, student_id", True),
    ("tabSIS Class Attendance", "idx_class_date_period", "class_id, `date`, period", False),
]


def _index_exists(table, idx_name):
    rows = frappe.db.sql(
        f"SHOW INDEX FROM `{table}` WHERE Key_name = %s",
        (idx_name,),
        as_dict=True,
    )
    return bool(rows)


def _dedup_for_unique_subject_student():
    """
    Dọn dữ liệu trùng (subject_id, student_id) trong SIS Class Log Student
    trước khi gắn UNIQUE INDEX. Giữ bản ghi có name nhỏ nhất (creation sớm nhất).
    """
    if not frappe.db.table_exists("SIS Class Log Student"):
        return 0

    duplicates = frappe.db.sql(
        """
        SELECT t.name
        FROM `tabSIS Class Log Student` t
        INNER JOIN (
            SELECT subject_id, student_id, MIN(name) AS keep_name
            FROM `tabSIS Class Log Student`
            WHERE subject_id IS NOT NULL AND student_id IS NOT NULL
            GROUP BY subject_id, student_id
            HAVING COUNT(*) > 1
        ) dup
            ON dup.subject_id = t.subject_id
           AND dup.student_id = t.student_id
        WHERE t.name <> dup.keep_name
        """,
        as_dict=True,
    )

    deleted = len(duplicates)
    if deleted:
        names = [d["name"] for d in duplicates]
        for i in range(0, len(names), 500):
            batch = names[i:i + 500]
            placeholders = ", ".join(["%s"] * len(batch))
            frappe.db.sql(
                f"DELETE FROM `tabSIS Class Log Student` WHERE name IN ({placeholders})",
                tuple(batch),
            )
        frappe.db.commit()
        frappe.logger().info(
            f"[optimize_classlog_attendance_indexes] Đã xoá {deleted} bản ghi trùng (subject_id, student_id)"
        )
    return deleted


def execute():
    # Bước 1: dedup trước khi gắn UNIQUE
    try:
        _dedup_for_unique_subject_student()
    except Exception as ex:
        frappe.logger().error(
            f"[optimize_classlog_attendance_indexes] Dedup thất bại: {ex}"
        )

    # Bước 2: tạo các index nếu chưa có
    for table, idx_name, cols, is_unique in INDEX_SPECS:
        if not frappe.db.table_exists(table.replace("tab", "", 1)):
            frappe.logger().warning(
                f"[optimize_classlog_attendance_indexes] Bỏ qua — bảng {table} không tồn tại"
            )
            continue

        if _index_exists(table, idx_name):
            frappe.logger().info(
                f"[optimize_classlog_attendance_indexes] Index {idx_name} trên {table} đã tồn tại"
            )
            continue

        keyword = "UNIQUE INDEX" if is_unique else "INDEX"
        try:
            frappe.db.sql(
                f"CREATE {keyword} `{idx_name}` ON `{table}` ({cols})"
            )
            frappe.db.commit()
            frappe.logger().info(
                f"[optimize_classlog_attendance_indexes] Đã tạo {keyword} {idx_name} ON {table} ({cols})"
            )
        except Exception as ex:
            # Nếu UNIQUE còn vướng dữ liệu trùng → log để xử lý tay (không raise để migrate khác chạy tiếp)
            if is_unique and "Duplicate entry" in str(ex):
                frappe.logger().error(
                    f"[optimize_classlog_attendance_indexes] Vẫn còn trùng trên {table} cho {cols}: {ex}"
                )
            else:
                frappe.logger().error(
                    f"[optimize_classlog_attendance_indexes] Tạo {idx_name} thất bại: {ex}"
                )
