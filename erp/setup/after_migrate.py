import frappe


# Danh sách role cần đảm bảo tồn tại sau mỗi lần migrate
REQUIRED_ROLES = [
    "SIS Medical",
    "SIS Finance",
]

# Danh mục ticket IT mặc định — title khớp FE (Overall, Camera, ...)
IT_SUPPORT_CATEGORIES = [
    {"title": "Overall", "ticket_code_prefix": "OVR", "support_role": "Overall"},
    {"title": "Camera", "ticket_code_prefix": "CAM", "support_role": "Camera System"},
    {"title": "Network", "ticket_code_prefix": "NW", "support_role": "Network System"},
    {"title": "Bell System", "ticket_code_prefix": "PA", "support_role": "Bell System"},
    {"title": "Software", "ticket_code_prefix": "SW", "support_role": "Software"},
    {"title": "Account", "ticket_code_prefix": "ACC", "support_role": "Account"},
    {"title": "Email Ticket", "ticket_code_prefix": "EML", "support_role": "Email Ticket"},
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


def _ensure_admission_file_folder():
    """Folder upload hồ sơ nhập học CRM (khớp FE Home/Admission)."""
    if frappe.db.exists(
        "File",
        {"is_folder": 1, "file_name": "Admission", "folder": "Home"},
    ):
        return
    try:
        frappe.get_doc(
            {
                "doctype": "File",
                "file_name": "Admission",
                "is_folder": 1,
                "folder": "Home",
            }
        ).insert(ignore_permissions=True)
        frappe.db.commit()
    except Exception:
        frappe.db.rollback()


def _ensure_it_support_ticket_file_folder():
    """Folder upload ảnh comment ticket IT."""
    if frappe.db.exists(
        "File",
        {"is_folder": 1, "file_name": "ITSupportTicket", "folder": "Home"},
    ):
        return
    try:
        frappe.get_doc(
            {
                "doctype": "File",
                "file_name": "ITSupportTicket",
                "is_folder": 1,
                "folder": "Home",
            }
        ).insert(ignore_permissions=True)
        frappe.db.commit()
    except Exception:
        frappe.db.rollback()


def _seed_it_support_categories():
    """Seed 7 danh mục ticket IT nếu chưa có."""
    for cat in IT_SUPPORT_CATEGORIES:
        title = cat["title"]
        if frappe.db.exists("ERP IT Support Category", {"title": title}):
            continue
        try:
            frappe.get_doc(
                {
                    "doctype": "ERP IT Support Category",
                    "title": title,
                    "ticket_code_prefix": cat["ticket_code_prefix"],
                    "support_role": cat["support_role"],
                }
            ).insert(ignore_permissions=True)
            frappe.db.commit()
        except Exception:
            frappe.db.rollback()


PROCUREMENT_ROLES = ["CFO", "COO", "CEO", "SIS BOD"]

PROCUREMENT_REQUEST_GROUPS = [
    ("Đồ dùng dạy học", 30),
    ("Đồ dùng cho sự kiện", 30),
    ("Bảo trì sửa chữa trang thiết bị", 7),
    ("Thuê dịch vụ", 30),
    ("Trang thiết bị cần đặt hàng sản xuất", 60),
    ("Trang thiết bị có sẵn trên thị trường", 14),
]


def _seed_procurement():
    """Role duyệt + nhóm yêu cầu mặc định cho module Mua sắm."""
    try:
        for role_name in PROCUREMENT_ROLES:
            if not frappe.db.exists("Role", role_name):
                frappe.get_doc({"doctype": "Role", "role_name": role_name}).insert(
                    ignore_permissions=True
                )
        for group_name, leadtime in PROCUREMENT_REQUEST_GROUPS:
            if not frappe.db.exists("ERP Procurement Request Group", group_name):
                frappe.get_doc(
                    {
                        "doctype": "ERP Procurement Request Group",
                        "group_name": group_name,
                        "default_leadtime_days": leadtime,
                        "is_active": 1,
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
    _ensure_it_support_ticket_file_folder()
    _ensure_admission_file_folder()
    _seed_it_support_categories()
    _seed_procurement()
