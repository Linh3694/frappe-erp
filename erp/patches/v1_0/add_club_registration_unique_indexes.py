# -*- coding: utf-8 -*-
"""
Hai UNIQUE index ép hai luật đăng ký CLB ở tầng DB. Idempotent.

    uq_club_reg_student_subject (period_id, subject_id, active_student_key)
        -> mỗi HS tối đa 1 đăng ký / 1 môn / 1 đợt, kể cả khi môn đó mở ở nhiều thứ
    uq_club_reg_student_day     (period_id, day_of_week, active_student_key)
        -> mỗi HS tối đa 1 môn / thứ

Vì sao dùng cột `active_student_key` thay cho `student_id`:
MariaDB BỎ QUA mọi dòng có cột NULL trong UNIQUE index. `active_student_key`
bằng `student_id` khi đăng ký còn hiệu lực và bằng NULL khi đã huỷ, nên ràng
buộc chỉ áp lên dòng active — một đăng ký đã huỷ không chặn học sinh đăng ký
lại chính môn đó. MySQL/MariaDB không có partial index nên đây là cách duy nhất.

Index theo `subject_id` bao trùm luôn ràng buộc theo `offering_id`: một offering
chỉ có đúng một subject, nên hai đăng ký cùng offering tất yếu cùng subject.

CẢNH BÁO: đây là lưới an toàn cuối cùng cho chống trùng. Lock ở tầng ứng dụng
(erp/sis/utils/club_registration.py) chỉ chặn được request đi qua nó; index này
chặn cả bench console, import và mọi code tương lai.
"""

import frappe

TABLE = "tabSIS Club Registration"


def _has_index(index_name: str) -> bool:
    return bool(
        frappe.db.sql(f"SHOW INDEX FROM `{TABLE}` WHERE Key_name = %s", (index_name,))
    )


def _sync_active_student_key() -> None:
    """Đồng bộ cột khoá cho dữ liệu đã có (bảng thường rỗng ở lần deploy đầu)."""
    frappe.db.sql(
        f"""
        UPDATE `{TABLE}`
        SET active_student_key = CASE WHEN status = 'active' THEN student_id ELSE NULL END
        """
    )


def _cancel_duplicates(group_column: str) -> None:
    """
    Huỷ các dòng trùng trước khi ALTER — còn trùng thì ALTER fail và
    `bench migrate` đứng giữa chừng. Giữ dòng CŨ NHẤT (FIFO: ai đăng ký trước
    thì giữ chỗ), huỷ các dòng sau.
    """
    frappe.db.sql(
        f"""
        UPDATE `{TABLE}` r
        JOIN (
            SELECT name FROM (
                SELECT name,
                       ROW_NUMBER() OVER (
                           PARTITION BY period_id, `{group_column}`, active_student_key
                           ORDER BY creation ASC, name ASC
                       ) AS rn
                FROM `{TABLE}`
                WHERE active_student_key IS NOT NULL
            ) ranked WHERE ranked.rn > 1
        ) dup ON dup.name = r.name
        SET r.status = 'cancelled',
            r.active_student_key = NULL,
            r.cancel_reason = 'Tự động huỷ: trùng lặp phát hiện khi thêm unique index'
        """
    )


def _add_unique(index_name: str, columns_sql: str) -> None:
    if _has_index(index_name):
        return
    frappe.db.sql(
        f"ALTER TABLE `{TABLE}` ADD UNIQUE INDEX `{index_name}` ({columns_sql})"
    )


def _add_index(index_name: str, columns_sql: str) -> None:
    if _has_index(index_name):
        return
    frappe.db.sql(f"ALTER TABLE `{TABLE}` ADD INDEX `{index_name}` ({columns_sql})")


def execute():
    if not frappe.db.table_exists(TABLE):
        return

    _sync_active_student_key()
    _cancel_duplicates("subject_id")
    _cancel_duplicates("day_of_week")

    _add_unique(
        "uq_club_reg_student_subject",
        "`period_id`, `subject_id`, `active_student_key`",
    )
    _add_unique(
        "uq_club_reg_student_day",
        "`period_id`, `day_of_week`, `active_student_key`",
    )

    # Index phục vụ đếm số chỗ đã dùng của một môn.
    _add_index("idx_club_reg_offering_status", "`offering_id`, `status`")
    # Index phục vụ tra "học sinh này đã đăng ký gì trong đợt".
    _add_index("idx_club_reg_period_student", "`period_id`, `student_id`, `status`")

    frappe.db.commit()
