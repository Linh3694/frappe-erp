"""
Hook before_insert: tự gán campus_id từ context nếu DocType có field và chưa set.

⚠️ GIỚI HẠN QUAN TRỌNG
Hook này chỉ chạy khi document được tạo qua `doc.insert()` / `frappe.get_doc(...).insert()`.
Nó **KHÔNG** chạy với `frappe.db.sql("INSERT INTO ...")` hay `frappe.db.bulk_insert`.

Đây từng là nguyên nhân khiến 282k dòng `SIS Class Log Student` và 60k dòng
`SIS Teacher Timetable` có campus_id NULL dù doctype đã đăng ký hook: code dùng bulk
INSERT thô để tối ưu tốc độ. Đã vá tại (2026-08-07):
  - erp/api/erp_sis/class_log.py            (SIS Class Log Student)
  - erp/api/erp_sis/contact_log.py          (SIS Class Log Student)
  - erp/api/erp_sis/timetable/bulk_sync_engine.py        (SIS Teacher Timetable)
  - erp/api/erp_sis/utils/materialized_view_optimizer.py (SIS Teacher Timetable)
  - erp/api/erp_sis/health.py               (SIS Health Report)

Khi viết bulk INSERT mới vào bảng có campus_id: PHẢI tự set cột đó, và nên lấy theo
DỮ LIỆU (class_id/student_id → campus của lớp/học sinh) chứ không theo session —
session có thể là Administrator trong job nền và sẽ đóng dấu sai campus.
"""

from __future__ import annotations

import frappe

from erp.utils.campus_utils import get_current_campus_from_context


def inject_campus_id(doc, method=None):
	"""Gán campus_id mặc định khi tạo document mới."""
	if doc.get("__islocal") is False:
		return

	meta = frappe.get_meta(doc.doctype)
	if not meta.get_field("campus_id"):
		return

	if doc.get("campus_id"):
		return

	campus_id = get_current_campus_from_context()
	if campus_id:
		doc.campus_id = campus_id
