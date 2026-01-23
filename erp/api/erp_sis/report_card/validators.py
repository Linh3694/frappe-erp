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
