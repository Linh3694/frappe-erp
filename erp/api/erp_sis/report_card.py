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
    # Serializers
    intl_scoreboard_enabled,
    # Approval
    approve_report_card,
    submit_section,
    submit_class_reports,
    approve_level_1,
    approve_level_2,
    review_report,
    final_publish,
    get_pending_approvals,
    get_pending_approvals_grouped,
    approve_class_reports,
    reject_class_reports,
    get_approval_config,
    save_approval_config,
    get_subject_managers,
    update_subject_managers,
    get_teacher_class_permissions,
    review_batch_reports,
    publish_batch_reports,
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
    # Serializers
    "intl_scoreboard_enabled",
    # Approval
    "approve_report_card",
    "submit_section",
    "submit_class_reports",
    "approve_level_1",
    "approve_level_2",
    "review_report",
    "final_publish",
    "get_pending_approvals",
    "get_pending_approvals_grouped",
    "approve_class_reports",
    "reject_class_reports",
    "get_approval_config",
    "save_approval_config",
    "get_subject_managers",
    "update_subject_managers",
    "get_teacher_class_permissions",
    "review_batch_reports",
    "publish_batch_reports",
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
