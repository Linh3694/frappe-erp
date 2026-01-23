# -*- coding: utf-8 -*-
"""
Report Card Module
==================

Module chứa các APIs liên quan đến Report Card (Sổ điểm/Học bạ)

Cấu trúc:
- utils.py: Shared utilities
- validators.py: Validation functions
- serializers.py: Template serializers & normalizers
- template.py: Template CRUD APIs
- student_report.py: Student Report CRUD APIs
- approval.py: Approval & notification logic
- images.py: Image upload/retrieval APIs
- classes.py: Class-related APIs
- form.py: Form CRUD APIs
"""

# Template APIs
from .template import (
    get_all_templates,
    get_template_by_id,
    create_template,
    update_template,
    delete_template,
)

# Validators
from .validators import validate_comment_titles

# Approval
from .approval import (
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
)

# Images
from .images import (
    upload_report_card_images,
    get_report_card_images,
)

# Classes
from .classes import (
    get_all_classes_for_reports,
    get_my_classes,
    get_class_reports,
)

# Form
from .form import (
    get_all_forms,
    get_form_by_id,
    create_form,
    update_form,
    delete_form,
    ensure_default_forms,
    ensure_intl_forms,
)

# Student Report
from .student_report import (
    create_reports_for_class,
    get_reports_by_class,
    list_reports,
    get_report,
    get_report_by_id,
    update_report_section,
    delete_report,
    sync_new_subjects_to_reports,
    get_previous_semester_score,
)

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
    # Student Report
    "create_reports_for_class",
    "get_reports_by_class",
    "list_reports",
    "get_report",
    "get_report_by_id",
    "update_report_section",
    "delete_report",
    "sync_new_subjects_to_reports",
    "get_previous_semester_score",
]
