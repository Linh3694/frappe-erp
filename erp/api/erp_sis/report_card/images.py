# -*- coding: utf-8 -*-
"""
Report Card Image APIs
======================

APIs cho việc upload và lấy ảnh Report Card.
"""

import frappe
from frappe import _
import os
import glob
from typing import Optional

from erp.utils.api_response import (
    success_response,
    error_response,
)


@frappe.whitelist(allow_guest=True)
def upload_report_card_images():
    """
    Upload report card dưới dạng PNG images.
    
    Request: multipart/form-data với:
        - report_id: Report card ID
        - images: Array của PNG files
    """
    try:
        user = frappe.session.user
        user_roles = frappe.get_roles(user)
        
        # Check permissions
        allowed_roles = ["SIS Manager", "SIS BOD", "System Manager"]
        has_permission = any(role in user_roles for role in allowed_roles)
        
        if not has_permission:
            frappe.throw(
                _("Bạn không có quyền tải lên báo cáo học tập."),
                title="Permission Denied"
            )
        
        # Get report_id
        report_id = None
        if hasattr(frappe.request, 'form') and frappe.request.form:
            report_id = frappe.request.form.get('report_id')
        if not report_id:
            report_id = frappe.form_dict.get('report_id')
        if not report_id:
            frappe.throw(_("report_id is required"), title="Missing Parameter")
        
        # Get report
        try:
            report = frappe.get_doc("SIS Student Report Card", report_id, ignore_permissions=True)
        except frappe.DoesNotExistError:
            frappe.throw(
                _("Báo cáo học tập không được tìm thấy: {0}").format(report_id),
                title="Not Found"
            )
        
        # Get student code
        try:
            student = frappe.get_doc("CRM Student", report.student_id, ignore_permissions=True)
            student_code = student.student_code or report.student_id
        except Exception:
            student_code = report.student_id
        
        # Get school year and semester
        school_year = (
            getattr(report, 'school_year', None) or 
            getattr(report, 'academic_year', None) or 
            'unknown'
        )
        
        semester_part = (
            getattr(report, 'semester_part', None) or 
            getattr(report, 'semester', None) or 
            'semester_1'
        )
        
        # Build folder path
        files_path = frappe.get_site_path('public', 'files', 'reportcard', student_code, school_year, semester_part)
        os.makedirs(files_path, exist_ok=True)
        
        # Get uploaded files
        files = frappe.request.files
        if not files or 'images' not in files:
            frappe.throw(_("Không có ảnh được tải lên."), title="No Files")
        
        uploaded_images = files.getlist('images')
        if not uploaded_images:
            frappe.throw(_("Danh sách ảnh trống"), title="Empty Images")
        
        file_paths = []
        
        for idx, file in enumerate(uploaded_images):
            try:
                filename = f"page_{idx+1}.png"
                file_path = os.path.join(files_path, filename)
                file.save(file_path)
                
                relative_path = f"/files/reportcard/{student_code}/{school_year}/{semester_part}/{filename}"
                file_paths.append({
                    "filename": filename,
                    "path": relative_path,
                    "page": idx + 1
                })
            except Exception as e:
                frappe.logger().error(f"Error saving image {idx+1}: {str(e)}")
                continue
        
        if not file_paths:
            frappe.throw(_("Không có ảnh nào được lưu thành công"), title="Save Error")
        
        # Update report
        try:
            report.report_card_images_folder = f"/files/reportcard/{student_code}/{school_year}/{semester_part}"
            report.save(ignore_permissions=True)
            frappe.db.commit()
        except Exception as e:
            frappe.logger().warning(f"Could not update report with image folder: {str(e)}")
        
        return success_response(
            data={
                "report_id": report_id,
                "student_code": student_code,
                "school_year": school_year,
                "semester_part": semester_part,
                "images": file_paths,
                "total_pages": len(file_paths),
                "folder_path": f"/files/reportcard/{student_code}/{school_year}/{semester_part}"
            },
            message=f"Successfully uploaded {len(file_paths)} images"
        )
        
    except frappe.PermissionError:
        raise
    except Exception as e:
        frappe.logger().error(f"Error in upload_report_card_images: {str(e)}")
        frappe.logger().error(frappe.get_traceback())
        frappe.throw(
            _("Lỗi khi tải lên ảnh báo cáo: {0}").format(str(e)),
            title="Upload Error"
        )


@frappe.whitelist(allow_guest=False)
def get_report_card_images(report_id: Optional[str] = None):
    """
    Lấy danh sách PNG images của một report card.
    
    Args:
        report_id: Report card ID
    """
    try:
        # Get report_id
        if not report_id:
            report_id = frappe.form_dict.get("report_id")
        if not report_id:
            report_id = (frappe.local.form_dict or {}).get("report_id")
        
        if not report_id:
            return error_response(
                message="Missing report_id",
                code="MISSING_PARAMS"
            )
        
        # Get report
        try:
            report = frappe.get_doc("SIS Student Report Card", report_id, ignore_permissions=True)
        except frappe.DoesNotExistError:
            return error_response(
                message="Báo cáo học tập không được tìm thấy",
                code="NOT_FOUND"
            )
        
        # Get student code
        try:
            student = frappe.get_doc("CRM Student", report.student_id, ignore_permissions=True)
            student_code = student.student_code or report.student_id
        except Exception:
            student_code = report.student_id
        
        # Get school year and semester
        school_year = (
            getattr(report, 'school_year', None) or 
            getattr(report, 'academic_year', None) or 
            'unknown'
        )
        
        semester_part = (
            getattr(report, 'semester_part', None) or 
            getattr(report, 'semester', None) or 
            'semester_1'
        )
        
        # Build folder path
        report_folder = frappe.get_site_path(
            'public', 'files', 'reportcard',
            student_code, school_year, semester_part
        )
        
        # Get PNG files
        image_files = sorted(glob.glob(os.path.join(report_folder, '*.png')))
        
        if not image_files:
            return success_response(
                data={
                    "report_id": report_id,
                    "images": [],
                    "has_images": False,
                    "folder_path": f"/files/reportcard/{student_code}/{school_year}/{semester_part}"
                },
                message="Báo cáo chưa được xuất ảnh"
            )
        
        # Convert to URLs
        image_urls = []
        for idx, image_path in enumerate(image_files):
            filename = os.path.basename(image_path)
            url = f"/files/reportcard/{student_code}/{school_year}/{semester_part}/{filename}"
            image_urls.append({
                "page": idx + 1,
                "filename": filename,
                "url": url
            })
        
        return success_response(
            data={
                "report_id": report_id,
                "student_code": student_code,
                "school_year": school_year,
                "semester_part": semester_part,
                "images": image_urls,
                "total_pages": len(image_urls),
                "has_images": True,
                "folder_path": f"/files/reportcard/{student_code}/{school_year}/{semester_part}"
            },
            message=f"Found {len(image_urls)} pages"
        )
        
    except Exception as e:
        frappe.logger().error(f"Error in get_report_card_images: {str(e)}")
        frappe.logger().error(frappe.get_traceback())
        return error_response(
            message=f"Lỗi khi lấy ảnh báo cáo: {str(e)}",
            code="SERVER_ERROR"
        )
