"""Ngân sách: chuyển sang luồng duyệt CỐ ĐỊNH TC -> CFO -> CEO -> COO.

- Xoá hẳn các doctype cấu hình duyệt (Approval Config / Step / Approver) khỏi DB
  (đã bỏ khỏi code). Xử lý cả tên cũ 'SIS Budget *' lẫn 'ERP Budget *'.
- Tạo role CFO / CEO / COO nếu chưa có (để gán người duyệt từng cấp).
"""

import frappe

# Xoá theo thứ tự cha -> con cháu (Config chứa Step, Step chứa Approver)
_CONFIG_DOCTYPES = [
    "ERP Budget Approval Config",
    "SIS Budget Approval Config",
    "ERP Budget Approval Step",
    "SIS Budget Approval Step",
    "ERP Budget Approver",
    "SIS Budget Approver",
]

_EXEC_ROLES = ["CFO", "CEO", "COO"]


def execute():
    # 1) Xoá doctype cấu hình duyệt
    for dt in _CONFIG_DOCTYPES:
        if frappe.db.exists("DocType", dt):
            frappe.delete_doc("DocType", dt, force=True, ignore_permissions=True, ignore_missing=True)

    # 2) Tạo role exec cho luồng duyệt cố định
    for role in _EXEC_ROLES:
        if not frappe.db.exists("Role", role):
            frappe.get_doc(
                {
                    "doctype": "Role",
                    "role_name": role,
                    "desk_access": 1,
                }
            ).insert(ignore_permissions=True)

    frappe.db.commit()
