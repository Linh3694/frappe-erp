import frappe


# Danh sách role cần đảm bảo tồn tại sau mỗi lần migrate
REQUIRED_ROLES = [
    "SIS Medical",
]


def execute():
    """Tạo các role cần thiết nếu chưa tồn tại."""
    for role_name in REQUIRED_ROLES:
        if not frappe.db.exists("Role", role_name):
            frappe.get_doc({"doctype": "Role", "role_name": role_name}).insert(ignore_permissions=True)
            frappe.db.commit()
