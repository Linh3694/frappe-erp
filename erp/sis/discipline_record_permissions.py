# Copyright (c) 2025, Wellspring International School and contributors
# For license information, please see license.txt

"""
Phân quyền ghi nhận lỗi (dùng chung API + Document hook).
SIS Supervisory: chỉ tạo/sửa/xóa bản ghi mình là owner (người tạo).
SIS Supervisory Admin + System Manager + SIS BOD + Administrator: mọi bản ghi.
"""


import frappe


def session_roles_normalized() -> set[str]:
    """Role hiện tại đã strip — tránh lệch chuỗi với khoảng trắng thừa."""
    return {str(r).strip() for r in frappe.get_roles(frappe.session.user)}


def discipline_session_matches_owner(doc_owner: str | None) -> bool:
    if not doc_owner:
        return False
    u = (frappe.session.user or "").strip()
    o = (doc_owner or "").strip()
    if not u or not o:
        return False
    if o == u:
        return True
    if "@" in u and o.lower() == u.lower():
        return True
    return False


def user_can_create_discipline_record():
    """Tạo bản ghi: Supervisory / Supervisory Admin / System Manager / SIS BOD / Administrator"""
    if frappe.session.user in (None, "Guest"):
        return False, "Chưa đăng nhập"
    roles = session_roles_normalized()
    if roles & {"System Manager", "SIS BOD", "Administrator"}:
        return True, None
    if "SIS Supervisory Admin" in roles or "SIS Supervisory" in roles:
        return True, None
    return False, "Không có quyền tạo ghi nhận lỗi"


def user_can_write_existing_discipline_record(doc_owner: str | None):
    """
    Sửa/xóa bản ghi đã tồn tại.
    Supervisory Admin + quyền hệ thống: mọi bản ghi.
    Chỉ SIS Supervisory: owner (người tạo) phải khớp session.
    """
    if frappe.session.user in (None, "Guest"):
        return False, "Chưa đăng nhập"
    roles = session_roles_normalized()
    if roles & {"System Manager", "SIS BOD", "Administrator"}:
        return True, None
    if "SIS Supervisory Admin" in roles:
        return True, None
    if "SIS Supervisory" in roles:
        if discipline_session_matches_owner(doc_owner):
            return True, None
        return False, "Bạn chỉ được sửa/xóa bản ghi do chính mình tạo"
    return False, "Không có quyền thao tác ghi nhận lỗi"
