"""
API CRM Issue Group - Cau hinh Nhom van de (truoc day hardcode "Gop y" / "Su vu").

`CRM Issue.issue_group` van luu TEN nhom (Data) chu khong phai Link, va doctype nay
autoname theo `group_name` nen docname == ten hien thi. Nho vay du lieu cu khong can
migrate. Doi ten nhom thi `update_group` backfill luon cac van de dang dung ten cu.
"""

import frappe

from erp.utils.api_response import (
    success_response,
    error_response,
    single_item_response,
    validation_error_response,
    not_found_response,
)
from erp.api.crm.utils import get_request_data

CONFIG_ROLES = [
    "System Manager",
    "SIS Manager",
    "SIS Sales Care Admin",
    "SIS Sales Admin",
]

# Hai nhom co san truoc khi co man cau hinh — seed de du lieu cu khong bi coi la khong hop le.
DEFAULT_GROUPS = [
    {"group_name": "Góp ý", "group_name_en": "Feedback"},
    {"group_name": "Sự vụ", "group_name_en": "Incident"},
]


def _check_config_permission():
    user_roles = frappe.get_roles(frappe.session.user)
    if not any(r in user_roles for r in CONFIG_ROLES):
        frappe.throw("Khong co quyen cau hinh nhom van de", frappe.PermissionError)


def ensure_default_groups():
    """Tao 2 nhom mac dinh neu bang con rong (lan dau chay sau khi migrate)."""
    try:
        if frappe.db.count("CRM Issue Group"):
            return
        for row in DEFAULT_GROUPS:
            doc = frappe.new_doc("CRM Issue Group")
            doc.group_name = row["group_name"]
            doc.group_name_en = row["group_name_en"]
            doc.is_active = 1
            doc.insert(ignore_permissions=True)
        frappe.db.commit()
    except Exception:
        frappe.db.rollback()
        frappe.logger().error("issue_group: seed default failed", exc_info=True)


def active_group_names():
    """Ten cac nhom dang bat — dung de validate `issue_group` khi tao/duyet van de.

    KHONG goi `ensure_default_groups()` o day: ham do commit, ma day lai chay giua
    transaction tao/sua van de. Bang rong thi caller (`_valid_issue_groups`) tu quay ve
    DEFAULT_ISSUE_GROUPS; viec seed de man cau hinh (`get_groups`) lo.
    """
    return frappe.get_all(
        "CRM Issue Group",
        filters={"is_active": 1},
        pluck="group_name",
        order_by="group_name asc",
    ) or []


@frappe.whitelist()
def get_groups():
    """Danh sach nhom van de. Doc mo cho moi user dang nhap (form tao van de can)."""
    ensure_default_groups()
    is_active = frappe.request.args.get("is_active")
    filters = {}
    if is_active is not None and is_active != "":
        filters["is_active"] = 1 if str(is_active).lower() in ("1", "true", "yes") else 0

    groups = frappe.get_all(
        "CRM Issue Group",
        filters=filters or None,
        fields=[
            "name",
            "group_name",
            "group_name_en",
            "is_active",
            "modified",
        ],
        order_by="group_name asc",
    )
    for g in groups:
        g["issue_count"] = frappe.db.count("CRM Issue", {"issue_group": g["group_name"]})
    return success_response(groups)


@frappe.whitelist(methods=["POST"])
def create_group():
    _check_config_permission()
    data = get_request_data()
    name = (data.get("group_name") or "").strip()
    if not name:
        return validation_error_response("Thieu thong tin", {"group_name": ["Bat buoc"]})
    if frappe.db.exists("CRM Issue Group", name):
        return validation_error_response("Nhom da ton tai", {"group_name": ["Trung ten"]})

    try:
        doc = frappe.new_doc("CRM Issue Group")
        doc.group_name = name
        doc.group_name_en = (data.get("group_name_en") or "").strip()
        doc.is_active = 1 if data.get("is_active", True) else 0
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
        return single_item_response(doc.as_dict(), "Tao nhom van de thanh cong")
    except Exception as e:
        frappe.db.rollback()
        return error_response(str(e))


@frappe.whitelist(methods=["POST"])
def update_group():
    """Sua nhom van de.

    Doi `group_name` cung la doi docname. `CRM Issue.issue_group` luu TEN nhom nen phai
    backfill cac van de cu sang ten moi — lam trong CUNG transaction voi rename, hong thi
    rollback ca hai, khong de nua doi nua duoi.
    """
    _check_config_permission()
    data = get_request_data()
    name = data.get("name")
    if not name or not frappe.db.exists("CRM Issue Group", name):
        return not_found_response("Khong tim thay nhom van de")

    migrated = 0
    try:
        doc = frappe.get_doc("CRM Issue Group", name)
        new_name = (data.get("group_name") or "").strip()
        if new_name and new_name != doc.group_name:
            if frappe.db.exists("CRM Issue Group", new_name):
                return validation_error_response("Nhom da ton tai", {"group_name": ["Trung ten"]})
            old_name = doc.group_name
            frappe.rename_doc("CRM Issue Group", doc.name, new_name, ignore_permissions=True)
            doc = frappe.get_doc("CRM Issue Group", new_name)
            doc.group_name = new_name
            migrated = frappe.db.count("CRM Issue", {"issue_group": old_name})
            if migrated:
                frappe.db.sql(
                    "UPDATE `tabCRM Issue` SET issue_group = %s WHERE issue_group = %s",
                    (new_name, old_name),
                )

        if "group_name_en" in data:
            doc.group_name_en = (data.get("group_name_en") or "").strip()
        if "is_active" in data:
            doc.is_active = 1 if data.get("is_active") else 0
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        msg = "Cap nhat thanh cong"
        if migrated:
            msg = f"Cap nhat thanh cong. Da chuyen {migrated} van de sang ten nhom moi."
        return single_item_response(doc.as_dict(), msg)
    except Exception as e:
        frappe.db.rollback()
        return error_response(str(e))


@frappe.whitelist(methods=["POST"])
def delete_group():
    """Xoa nhom neu chua co van de nao dung."""
    _check_config_permission()
    data = get_request_data()
    name = data.get("name")
    if not name:
        return validation_error_response("Thieu name", {"name": ["Bat buoc"]})
    if not frappe.db.exists("CRM Issue Group", name):
        return not_found_response("Khong tim thay nhom van de")

    group_name = frappe.db.get_value("CRM Issue Group", name, "group_name") or name
    cnt = frappe.db.count("CRM Issue", {"issue_group": group_name})
    if cnt:
        return error_response(f"Khong the xoa: dang co {cnt} van de dung nhom nay")

    try:
        frappe.delete_doc("CRM Issue Group", name, ignore_permissions=True)
        frappe.db.commit()
        return success_response({"deleted": True}, "Da xoa")
    except Exception as e:
        frappe.db.rollback()
        return error_response(str(e))


def resolve_group_name(preferred: str) -> str:
    """Ten nhom de ghi vao `CRM Issue.issue_group` tu cac luong tu dong (vd Gop y tu PH).

    `preferred` con hoat dong -> giu nguyen. Neu admin doi ten nhom do thi tra ve nhom dang
    bat dau tien, con hon ghi mot gia tri khong con trong danh sach.
    """
    want = (preferred or "").strip()
    try:
        names = active_group_names()
    except Exception:
        return want
    if not names:
        return want
    return want if want in names else names[0]
