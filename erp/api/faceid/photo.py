"""Lấy ảnh person từ CRM/SIS/User để đẩy xuống controller."""

from __future__ import annotations

import os

import frappe


def _read_file_bytes(file_url: str | None) -> bytes | None:
    if not file_url:
        return None
    path = file_url if file_url.startswith("/") else f"/{file_url.lstrip('/')}"
    if not path.startswith("/files/"):
        path = f"/files/{path.lstrip('/')}"
    full = frappe.get_site_path("public", path.lstrip("/"))
    if not os.path.isfile(full):
        return None
    with open(full, "rb") as f:
        return f.read()


def get_student_photo_bytes(crm_student: str) -> bytes | None:
    """Ảnh học sinh từ SIS Photo (ưu tiên năm học active)."""
    current_school_year = frappe.db.get_value(
        "SIS School Year", {"is_active": 1}, "name"
    )
    photos = frappe.db.sql(
        """
        SELECT photo FROM `tabSIS Photo`
        WHERE student_id = %(sid)s AND type = 'student' AND status = 'Active'
        ORDER BY
            CASE WHEN school_year_id = %(year)s THEN 0 ELSE 1 END,
            upload_date DESC, creation DESC
        LIMIT 1
        """,
        {"sid": crm_student, "year": current_school_year},
        as_dict=True,
    )
    if photos and photos[0].photo:
        return _read_file_bytes(photos[0].photo)
    return None


def get_guardian_photo_bytes(crm_guardian: str) -> bytes | None:
    img = frappe.db.get_value("CRM Guardian", crm_guardian, "guardian_image")
    return _read_file_bytes(img)


def get_guardian_photo_url(crm_guardian: str) -> str | None:
    return frappe.db.get_value("CRM Guardian", crm_guardian, "guardian_image")


def get_user_photo_bytes(user: str) -> bytes | None:
    img = frappe.db.get_value("User", user, "user_image")
    return _read_file_bytes(img)


def get_user_photo_url(user: str) -> str | None:
    return frappe.db.get_value("User", user, "user_image")


def get_student_photo_url(crm_student: str) -> str | None:
    """URL ảnh học sinh từ SIS Photo."""
    current_school_year = frappe.db.get_value(
        "SIS School Year", {"is_enable": 1}, "name"
    )
    photos = frappe.db.sql(
        """
        SELECT photo FROM `tabSIS Photo`
        WHERE student_id = %(sid)s AND type = 'student' AND status = 'Active'
        ORDER BY
            CASE WHEN school_year_id = %(year)s THEN 0 ELSE 1 END,
            upload_date DESC, creation DESC
        LIMIT 1
        """,
        {"sid": crm_student, "year": current_school_year},
        as_dict=True,
    )
    if photos and photos[0].photo:
        return photos[0].photo
    return None


def get_person_photo_url(doc) -> str | None:
    """URL ảnh theo loại FaceID Person (ưu tiên photo_url cache)."""
    if doc.photo_url:
        return doc.photo_url
    if doc.photo_file:
        return doc.photo_file
    if doc.person_type == "student" and doc.crm_student:
        return get_student_photo_url(doc.crm_student)
    if doc.person_type == "guardian" and doc.crm_guardian:
        return get_guardian_photo_url(doc.crm_guardian)
    if doc.person_type == "staff" and doc.user:
        return get_user_photo_url(doc.user)
    return None


def get_person_photo_bytes(doc) -> bytes | None:
    """Đọc ảnh theo loại FaceID Person."""
    if doc.photo_file:
        return _read_file_bytes(doc.photo_file)
    if doc.person_type == "student" and doc.crm_student:
        return get_student_photo_bytes(doc.crm_student)
    if doc.person_type == "guardian" and doc.crm_guardian:
        return get_guardian_photo_bytes(doc.crm_guardian)
    if doc.person_type == "staff" and doc.user:
        return get_user_photo_bytes(doc.user)
    return None
