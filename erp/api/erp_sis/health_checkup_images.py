# -*- coding: utf-8 -*-
# Copyright (c) 2026, Wellspring International School and contributors
"""
Ảnh phiếu khám SK định kỳ gửi Parent Portal — upload / xóa / liệt kê URL.
Pattern tương tự erp.api.erp_sis.report_card.images (lưu public/files/...).
"""

import glob
import os
import re
import shutil

import frappe
from frappe import _

from erp.utils.api_response import error_response, success_response


def _get_student_code_for_checkup(doc):
    """Lấy mã HS để dựng đường dẫn thư mục."""
    try:
        st = frappe.get_doc("CRM Student", doc.student_id, ignore_permissions=True)
        return (st.student_code or doc.student_id or "").strip() or doc.student_id
    except Exception:
        return doc.student_id


def _health_checkup_folder_path(doc):
    """Đường dẫn tuyệt đối trên disk: site/public/files/health_checkup/..."""
    student_code = _get_student_code_for_checkup(doc)
    school_year = doc.school_year_id or "unknown"
    phase = doc.checkup_phase or "beginning"
    return frappe.get_site_path("public", "files", "health_checkup", student_code, school_year, phase)


def _health_checkup_folder_url(doc):
    """URL tương đối /files/health_checkup/..."""
    student_code = _get_student_code_for_checkup(doc)
    school_year = doc.school_year_id or "unknown"
    phase = doc.checkup_phase or "beginning"
    return f"/files/health_checkup/{student_code}/{school_year}/{phase}"


def _sort_health_checkup_page_png_paths(paths):
    """Sắp page_1.png, page_2.png, … đúng thứ tự (tránh sort chữ: page_10 trước page_2)."""
    def sort_key(p):
        m = re.search(r"page_(\d+)\.png$", os.path.basename(p), re.IGNORECASE)
        return int(m.group(1)) if m else 0

    return sorted(paths, key=sort_key)


def _public_file_url_with_mtime_cache_bust(base_url: str, filename: str, disk_path: str) -> str:
    """URL + ?t=mtime — tránh cache ảnh cũ trên Parent Portal sau khi ghi đè file cùng tên."""
    try:
        mt = int(os.path.getmtime(disk_path)) if os.path.isfile(disk_path) else 0
    except OSError:
        mt = 0
    return f"{base_url}/{filename}?t={mt}"


def _teacher_id_from_session_user():
    uid = frappe.session.user
    if uid in ("Guest", "Administrator"):
        return None
    return frappe.db.get_value("SIS Teacher", {"user_id": uid}, "name")


def _is_homeroom_for_student(student_id, school_year_id) -> bool:
    tid = _teacher_id_from_session_user()
    if not tid:
        return False
    rows = frappe.db.sql(
        """
        SELECT c.homeroom_teacher, c.vice_homeroom_teacher
        FROM `tabSIS Class Student` cs
        INNER JOIN `tabSIS Class` c ON c.name = cs.class_id
        WHERE cs.student_id = %(sid)s AND cs.school_year_id = %(sy)s AND c.class_type = 'regular'
        LIMIT 1
        """,
        {"sid": student_id, "sy": school_year_id},
        as_dict=True,
    )
    if not rows:
        return False
    row = rows[0]
    return tid in (row.get("homeroom_teacher"), row.get("vice_homeroom_teacher"))


def _can_manage_checkup_images(doc):
    """GVCN lớp regular của HS, hoặc System Manager, hoặc SIS Medical (y tế chỉnh phiếu)."""
    if "System Manager" in frappe.get_roles():
        return True
    if _is_homeroom_for_student(doc.student_id, doc.school_year_id):
        return True
    if "SIS Medical" in frappe.get_roles() or "SIS Medical Admin" in frappe.get_roles():
        return True
    return False


@frappe.whitelist(allow_guest=False)
def upload_health_checkup_images():
    """
    Upload ảnh PNG phiếu khám (multipart: checkup_name, images[]).
    Cập nhật health_checkup_images_folder trên DocType.
    """
    try:
        checkup_name = None
        if hasattr(frappe.request, "form") and frappe.request.form:
            checkup_name = frappe.request.form.get("checkup_name")
        if not checkup_name:
            checkup_name = frappe.form_dict.get("checkup_name")
        if not checkup_name:
            frappe.throw(_("Thiếu checkup_name"), title="Missing Parameter")

        doc = frappe.get_doc("SIS Student Health Checkup", checkup_name, ignore_permissions=True)
        if not _can_manage_checkup_images(doc):
            frappe.throw(_("Bạn không có quyền tải ảnh cho phiếu này."), title="Permission Denied")

        files = frappe.request.files
        if not files or "images" not in files:
            frappe.throw(_("Không có ảnh được tải lên."), title="No Files")

        uploaded_images = files.getlist("images")
        if not uploaded_images:
            frappe.throw(_("Danh sách ảnh trống"), title="Empty Images")

        files_path = _health_checkup_folder_path(doc)
        os.makedirs(files_path, exist_ok=True)

        # Xóa ảnh cũ trong folder trước khi ghi mới (tránh page_1.png cũ sót lại)
        for old in glob.glob(os.path.join(files_path, "page_*.png")):
            try:
                os.remove(old)
            except OSError:
                pass

        file_paths = []
        for idx, file in enumerate(uploaded_images):
            try:
                filename = f"page_{idx + 1}.png"
                file_path = os.path.join(files_path, filename)
                file.save(file_path)
                rel = f"{_health_checkup_folder_url(doc)}/{filename}"
                file_paths.append({"filename": filename, "path": rel, "page": idx + 1})
            except Exception as e:
                frappe.logger().error(f"upload_health_checkup_images save {idx}: {str(e)}")
                continue

        if not file_paths:
            frappe.throw(_("Không có ảnh nào được lưu thành công"), title="Save Error")

        folder_url = _health_checkup_folder_url(doc)
        if frappe.db.has_column("SIS Student Health Checkup", "health_checkup_images_folder"):
            doc.db_set("health_checkup_images_folder", folder_url, update_modified=False)
        frappe.db.commit()

        return success_response(
            data={
                "checkup_name": checkup_name,
                "student_code": _get_student_code_for_checkup(doc),
                "school_year_id": doc.school_year_id,
                "checkup_phase": doc.checkup_phase,
                "images": file_paths,
                "total_pages": len(file_paths),
                "folder_path": folder_url,
            },
            message=f"Đã tải lên {len(file_paths)} ảnh",
        )
    except frappe.PermissionError:
        raise
    except Exception as e:
        frappe.logger().error(f"upload_health_checkup_images: {str(e)}")
        frappe.logger().error(frappe.get_traceback())
        frappe.throw(_("Lỗi khi tải lên ảnh: {0}").format(str(e)), title="Upload Error")


def delete_health_checkup_images_files(checkup_name: str) -> bool:
    """
    Xóa file PNG trong thư mục và clear field health_checkup_images_folder.
    Dùng nội bộ từ revoke workflow (không whitelist).
    """
    doc = frappe.get_doc("SIS Student Health Checkup", checkup_name, ignore_permissions=True)
    files_path = _health_checkup_folder_path(doc)
    if os.path.isdir(files_path):
        try:
            shutil.rmtree(files_path, ignore_errors=True)
        except Exception as e:
            frappe.logger().warning(f"delete_health_checkup_images_files rmtree: {str(e)}")
    if frappe.db.has_column("SIS Student Health Checkup", "health_checkup_images_folder"):
        doc.db_set("health_checkup_images_folder", None, update_modified=False)
    return True


@frappe.whitelist(allow_guest=False)
def delete_health_checkup_images():
    """API xóa ảnh (GVCN / y tế / System Manager)."""
    try:
        data = {}
        if frappe.local.form_dict:
            data.update(dict(frappe.local.form_dict))
        if hasattr(frappe.request, "is_json") and frappe.request.is_json:
            data.update(frappe.request.json or {})
        checkup_name = data.get("checkup_name")
        if not checkup_name:
            return error_response(message="Thiếu checkup_name", code="VALIDATION_ERROR")

        doc = frappe.get_doc("SIS Student Health Checkup", checkup_name, ignore_permissions=True)
        if not _can_manage_checkup_images(doc):
            return error_response(message="Không có quyền", code="FORBIDDEN")

        delete_health_checkup_images_files(checkup_name)
        frappe.db.commit()
        return success_response(data={"checkup_name": checkup_name}, message="Đã xóa ảnh")
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(f"delete_health_checkup_images: {str(e)}")
        return error_response(message=str(e), code="DELETE_ERROR")


@frappe.whitelist(allow_guest=False)
def get_health_checkup_images(checkup_name=None):
    """Liệt kê URL ảnh page_*.png (staff)."""
    try:
        if not checkup_name:
            checkup_name = frappe.form_dict.get("checkup_name")
        if not checkup_name:
            return error_response(message="Thiếu checkup_name", code="MISSING_PARAMS")

        doc = frappe.get_doc("SIS Student Health Checkup", checkup_name, ignore_permissions=True)
        if not _can_manage_checkup_images(doc):
            return error_response(message="Không có quyền", code="FORBIDDEN")

        folder_disk = _health_checkup_folder_path(doc)
        image_files = _sort_health_checkup_page_png_paths(glob.glob(os.path.join(folder_disk, "page_*.png")))
        base_url = _health_checkup_folder_url(doc)
        image_urls = []
        for idx, p in enumerate(image_files):
            fn = os.path.basename(p)
            image_urls.append(
                {
                    "page": idx + 1,
                    "filename": fn,
                    "url": _public_file_url_with_mtime_cache_bust(base_url, fn, p),
                }
            )

        return success_response(
            data={
                "checkup_name": checkup_name,
                "images": image_urls,
                "has_images": len(image_urls) > 0,
                "folder_path": doc.health_checkup_images_folder or base_url,
                "total_pages": len(image_urls),
            },
            message="OK",
        )
    except Exception as e:
        frappe.log_error(f"get_health_checkup_images: {str(e)}")
        return error_response(message=str(e), code="SERVER_ERROR")


def folder_has_health_checkup_images(checkup_name: str) -> bool:
    """True nếu có ít nhất một file page_*.png trong thư mục."""
    try:
        doc = frappe.get_doc("SIS Student Health Checkup", checkup_name, ignore_permissions=True)
        folder_disk = _health_checkup_folder_path(doc)
        return bool(glob.glob(os.path.join(folder_disk, "page_*.png")))
    except Exception:
        return False


def get_health_checkup_image_urls_for_checkup(checkup_name: str):
    """
    Liệt kê URL ảnh công khai (dùng sau khi đã kiểm tra quyền PH + published).
    Trả về list dict {page, filename, url}.
    """
    doc = frappe.get_doc("SIS Student Health Checkup", checkup_name, ignore_permissions=True)
    if doc.approval_status != "published":
        return []
    folder_disk = _health_checkup_folder_path(doc)
    base_url = _health_checkup_folder_url(doc)
    image_files = _sort_health_checkup_page_png_paths(glob.glob(os.path.join(folder_disk, "page_*.png")))
    out = []
    for idx, p in enumerate(image_files):
        fn = os.path.basename(p)
        out.append(
            {
                "page": idx + 1,
                "filename": fn,
                "url": _public_file_url_with_mtime_cache_bust(base_url, fn, p),
            }
        )
    return out
