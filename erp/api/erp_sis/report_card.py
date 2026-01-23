# -*- coding: utf-8 -*-
"""
Report Card APIs
================

DEPRECATED: File này được giữ lại để backward compatible.
Code thực tế đã được move vào package erp.api.erp_sis.report_card/

Tất cả imports và API paths cũ vẫn hoạt động bình thường.
"""

# Re-export tất cả APIs từ package mới
from erp.api.erp_sis.report_card import (
    # Template APIs
    get_all_templates,
    get_template_by_id,
    create_template,
    update_template,
    delete_template,
    # Validators
    validate_comment_titles,
    # Approval
    approve_report_card,
    # Images
    upload_report_card_images,
    get_report_card_images,
    # Classes
    get_all_classes_for_reports,
    get_my_classes,
    get_class_reports,
    # Form
    get_all_forms,
    get_form_by_id,
    create_form,
    update_form,
    delete_form,
    ensure_default_forms,
    ensure_intl_forms,
)

# Export cho backward compatibility
__all__ = [
    # Template APIs
    "get_all_templates",
    "get_template_by_id",
    "create_template",
    "update_template",
    "delete_template",
    # Validators
    "validate_comment_titles",
    # Approval
    "approve_report_card",
    # Images
    "upload_report_card_images",
    "get_report_card_images",
    # Classes
    "get_all_classes_for_reports",
    "get_my_classes",
    "get_class_reports",
    # Form
    "get_all_forms",
    "get_form_by_id",
    "create_form",
    "update_form",
    "delete_form",
    "ensure_default_forms",
    "ensure_intl_forms",
]
