"""
Thăm khám: gán shared_with_homeroom = 1 cho toàn bộ bản ghi cũ (giữ hành vi trước khi có cờ nháp/đã gửi).
"""

import frappe


def execute():
    if not frappe.db.table_exists("SIS Health Examination"):
        return
    # has_column nhận tên DocType, không phải tên bảng MySQL (tab...)
    if not frappe.db.has_column("SIS Health Examination", "shared_with_homeroom"):
        return
    # Một lần khi triển khai field: toàn bộ dữ liệu lịch sử coi như đã chia sẻ GVCN.
    # Patch chỉ chạy một lần (bản nháp tạo sau khi triển khai không bị ảnh hưởng).
    frappe.db.sql(
        """UPDATE `tabSIS Health Examination` SET `shared_with_homeroom` = 1"""
    )
    frappe.db.commit()
