"""Đổi tên 11 doctype Ngân sách: 'SIS Budget *' -> 'ERP Budget *' (chuyển module sang Finance).

Chạy ở pre_model_sync để rename bảng DB hiện có TRƯỚC khi sync JSON mới
(nếu không sync sẽ tạo doctype mới và để doctype/bảng cũ mồ côi).
rename_doc với DocType tự cập nhật: tên bảng, options Link/Table trỏ tới nó,
và parenttype trong các child table -> giữ nguyên dữ liệu.
"""

import frappe

# Parent trước, child/leaf sau cho an toàn parenttype.
RENAMES = [
    ("SIS Budget Approval Config", "ERP Budget Approval Config"),
    ("SIS Budget Plan", "ERP Budget Plan"),
    ("SIS Budget Adjustment", "ERP Budget Adjustment"),
    ("SIS Budget Code", "ERP Budget Code"),
    ("SIS Budget Period", "ERP Budget Period"),
    ("SIS Budget Approval Step", "ERP Budget Approval Step"),
    ("SIS Budget Approver", "ERP Budget Approver"),
    ("SIS Budget Plan Line", "ERP Budget Plan Line"),
    ("SIS Budget Plan History", "ERP Budget Plan History"),
    ("SIS Budget Adjustment Line", "ERP Budget Adjustment Line"),
    ("SIS Budget Code Department", "ERP Budget Code Department"),
]


def execute():
    for old, new in RENAMES:
        if not frappe.db.exists("DocType", old):
            continue
        if frappe.db.exists("DocType", new):
            # Đã rename (chạy lại patch) -> bỏ qua
            continue
        frappe.rename_doc("DocType", old, new, force=True)

    # Đảm bảo module trỏ về Finance (sync JSON sẽ set, nhưng set sớm cho chắc)
    for _old, new in RENAMES:
        if frappe.db.exists("DocType", new):
            frappe.db.set_value("DocType", new, "module", "Finance", update_modified=False)

    frappe.clear_cache()
