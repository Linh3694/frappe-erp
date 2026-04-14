import frappe


# Danh sách role cần đảm bảo tồn tại sau mỗi lần migrate
REQUIRED_ROLES = [
    "SIS Medical",
]


def _ensure_administrative_ticket_file_folder():
    """Folder upload ticket HC (khớp mobile/web Home/AdministrativeTicket)."""
    if frappe.db.exists(
        "File",
        {"is_folder": 1, "file_name": "AdministrativeTicket", "folder": "Home"},
    ):
        return
    try:
        frappe.get_doc(
            {
                "doctype": "File",
                "file_name": "AdministrativeTicket",
                "is_folder": 1,
                "folder": "Home",
            }
        ).insert(ignore_permissions=True)
        frappe.db.commit()
    except Exception:
        frappe.db.rollback()


def execute():
    """Tạo các role cần thiết nếu chưa tồn tại."""
    for role_name in REQUIRED_ROLES:
        if not frappe.db.exists("Role", role_name):
            frappe.get_doc({"doctype": "Role", "role_name": role_name}).insert(ignore_permissions=True)
            frappe.db.commit()

    _ensure_administrative_ticket_file_folder()
