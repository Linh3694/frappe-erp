# -*- coding: utf-8 -*-
"""
Gán `subject_type = 'academic'` cho mọi SIS Subject đã có. Idempotent.

Cột này tách môn câu lạc bộ khỏi môn học thuật. Không có nó, môn CLB sẽ:
  - hiện trong mọi dropdown chọn môn (get_all_subjects chỉ lọc theo campus), và
  - lọt vào bộ dữ liệu của solver xếp thời khoá biểu — vì hai luồng auto-generate
    dùng `timetable_subject_id IS NOT NULL` làm dấu hiệu "môn có tham gia TKB",
    mà môn CLB BUỘC phải gắn Timetable Subject để có tên tiếng Anh hiển thị trên
    Parent Portal.

Mọi dòng cũ đều là môn học thuật nên backfill thẳng 'academic'; hành vi hiện tại
không đổi chút nào sau khi patch chạy.
"""

import frappe


def execute():
    # Frappe đánh dấu patch ĐÃ CHẠY ngay khi execute() thoát không lỗi, nên không
    # được lặng lẽ `return` — làm vậy là backfill không bao giờ chạy nữa.
    # Lưu ý `table_exists()` TỰ thêm tiền tố `tab`: truyền "tabSIS Subject" sẽ luôn
    # trả False và khiến patch no-op im lặng.
    frappe.reload_doc("sis", "doctype", "sis_subject")

    if not frappe.db.table_exists("SIS Subject"):
        frappe.throw("Không tìm thấy bảng `tabSIS Subject` — doctype chưa được sync.")

    frappe.db.sql(
        """
        UPDATE `tabSIS Subject`
        SET subject_type = 'academic'
        WHERE subject_type IS NULL OR subject_type = ''
        """
    )
    frappe.db.commit()
