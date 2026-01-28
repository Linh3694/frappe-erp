# -*- coding: utf-8 -*-
"""
Report Card Validators
======================

Validation functions cho Report Card module.
"""

import frappe
from frappe import _
from typing import List

from erp.utils.api_response import (
    success_response,
    error_response,
    validation_error_response,
)

from .utils import get_request_payload, get_current_campus_id


def validate_comment_title_exists(comment_title_id: str, campus_id: str) -> bool:
    """
    Kiểm tra comment title có tồn tại và thuộc về campus hiện tại.
    
    Args:
        comment_title_id: ID của comment title
        campus_id: ID campus
    
    Returns:
        True nếu hợp lệ, False nếu không
    """
    if not comment_title_id:
        frappe.logger().warning(f"Comment title validation: empty comment_title_id provided")
        return False

    try:
        doc = frappe.get_doc("SIS Report Card Comment Title", comment_title_id)
        if doc.campus_id != campus_id:
            frappe.logger().error(
                f"Comment title {comment_title_id} exists but belongs to "
                f"campus {doc.campus_id}, not {campus_id}"
            )
            return False
        return True
    except frappe.DoesNotExistError:
        frappe.logger().error(f"Comment title {comment_title_id} does not exist in database")
        return False
    except Exception as e:
        frappe.logger().error(f"Error validating comment title {comment_title_id}: {str(e)}")
        return False


def validate_actual_subject_exists(subject_id: str, campus_id: str) -> bool:
    """
    Kiểm tra môn học có tồn tại và thuộc về campus hiện tại.
    
    Args:
        subject_id: ID của môn học
        campus_id: ID campus
    
    Returns:
        True nếu hợp lệ, False nếu không
    """
    if not subject_id:
        frappe.logger().warning(f"Actual subject validation: empty subject_id provided")
        return False

    try:
        doc = frappe.get_doc("SIS Actual Subject", subject_id)
        if doc.campus_id != campus_id:
            frappe.logger().error(
                f"Actual subject {subject_id} exists but belongs to "
                f"campus {doc.campus_id}, not {campus_id}"
            )
            return False
        return True
    except frappe.DoesNotExistError:
        frappe.logger().error(f"Actual subject {subject_id} does not exist in database")
        return False
    except Exception as e:
        frappe.logger().error(f"Error validating actual subject {subject_id}: {str(e)}")
        return False


@frappe.whitelist(allow_guest=False, methods=["POST"])
def validate_comment_titles():
    """
    API endpoint: Validate danh sách comment titles trước khi save template.
    
    Request payload:
        {
            "comment_title_ids": ["ID-1", "ID-2", ...]
        }
    
    Returns:
        Success response với danh sách valid/invalid titles
    """
    try:
        data = get_request_payload()
        comment_title_ids = data.get("comment_title_ids", [])

        if not comment_title_ids:
            return validation_error_response(
                message="Danh sách comment_title_ids là bắt buộc",
                errors={"comment_title_ids": ["Required"]}
            )

        campus_id = get_current_campus_id()
        invalid_titles: List[str] = []
        valid_titles: List[str] = []

        for comment_title_id in comment_title_ids:
            if validate_comment_title_exists(comment_title_id, campus_id):
                valid_titles.append(comment_title_id)
            else:
                invalid_titles.append(comment_title_id)

        result = {
            "valid_titles": valid_titles,
            "invalid_titles": invalid_titles,
            "all_valid": len(invalid_titles) == 0
        }

        if invalid_titles:
            frappe.logger().warning(f"Invalid comment titles found: {invalid_titles}")
            return error_response(
                message=f"Các tiêu đề nhận xét sau không tồn tại: {', '.join(invalid_titles)}",
                code="INVALID_COMMENT_TITLES",
                debug_info=result
            )

        return success_response(
            data=result,
            message="Tất cả tiêu đề nhận xét đều hợp lệ"
        )

    except Exception as e:
        error_msg = str(e)
        frappe.logger().error(f"Error validating comment titles: {error_msg}")
        return error_response(
            message=f"Lỗi khi kiểm tra tiêu đề nhận xét: {error_msg}",
            code="VALIDATION_ERROR"
        )


# =============================================================================
# VALIDATION HELPERS
# =============================================================================

def validate_report_access(report_id: str, campus_id: str) -> tuple:
    """
    Validate report tồn tại và thuộc về campus.
    
    Args:
        report_id: ID của báo cáo học tập
        campus_id: ID campus
    
    Returns:
        (report_doc, error_response) - report nếu valid, None và error response nếu invalid
    
    Example:
        report, error = validate_report_access(report_id, campus_id)
        if error:
            return error
        # ... continue với report
    """
    from .constants import Messages
    
    if not report_id:
        return None, validation_error_response(
            message=Messages.REPORT_ID_REQUIRED,
            errors={"report_id": ["Required"]}
        )
    
    try:
        report = frappe.get_doc("SIS Student Report Card", report_id)
    except frappe.DoesNotExistError:
        return None, not_found_response(Messages.REPORT_NOT_FOUND)
    
    if report.campus_id != campus_id:
        return None, forbidden_response(Messages.ACCESS_DENIED_REPORT)
    
    return report, None


def validate_template_access(template_id: str, campus_id: str) -> tuple:
    """
    Validate template tồn tại và thuộc về campus.
    
    Args:
        template_id: ID của template
        campus_id: ID campus
    
    Returns:
        (template_doc, error_response) - template nếu valid, None và error response nếu invalid
    
    Example:
        template, error = validate_template_access(template_id, campus_id)
        if error:
            return error
        # ... continue với template
    """
    from .constants import Messages
    
    if not template_id:
        return None, validation_error_response(
            message=Messages.TEMPLATE_ID_REQUIRED,
            errors={"template_id": ["Required"]}
        )
    
    try:
        template = frappe.get_doc("SIS Report Card Template", template_id)
    except frappe.DoesNotExistError:
        return None, not_found_response(Messages.TEMPLATE_NOT_FOUND)
    
    if template.campus_id != campus_id:
        return None, forbidden_response(Messages.ACCESS_DENIED_TEMPLATE)
    
    return template, None


def validate_class_access(class_id: str, campus_id: str) -> tuple:
    """
    Validate class tồn tại và thuộc về campus.
    
    Args:
        class_id: ID của lớp
        campus_id: ID campus
    
    Returns:
        (class_doc, error_response) - class nếu valid, None và error response nếu invalid
    """
    from .constants import Messages
    
    if not class_id:
        return None, validation_error_response(
            message=Messages.CLASS_ID_REQUIRED,
            errors={"class_id": ["Required"]}
        )
    
    try:
        class_doc = frappe.get_doc("SIS Class", class_id)
    except frappe.DoesNotExistError:
        return None, not_found_response(Messages.CLASS_NOT_FOUND)
    
    if class_doc.campus_id != campus_id:
        return None, forbidden_response(Messages.ACCESS_DENIED_CAMPUS)
    
    return class_doc, None


def validate_approval_status_transition(current_status: str, target_status: str, allowed_from: List[str]) -> tuple:
    """
    Validate trạng thái chuyển đổi có hợp lệ không.
    
    Args:
        current_status: Trạng thái hiện tại
        target_status: Trạng thái muốn chuyển đến
        allowed_from: List các trạng thái được phép chuyển từ
    
    Returns:
        (is_valid, error_message)
    """
    from .constants import Messages
    
    if current_status not in allowed_from:
        return False, Messages.INVALID_STATUS_FOR_APPROVAL.format(
            required=", ".join(allowed_from),
            current=current_status
        )
    
    return True, None


def not_found_response(message: str):
    """Trả về response 404."""
    from erp.utils.api_response import not_found_response as api_not_found
    return api_not_found(message)


def forbidden_response(message: str):
    """Trả về response 403."""
    from erp.utils.api_response import forbidden_response as api_forbidden
    return api_forbidden(message)
