# -*- coding: utf-8 -*-
"""
Report Card Approval Module
===========================

Module quản lý approval flow cho Report Card.
Tách thành các submodules theo chức năng để dễ maintain.

Backward Compatibility:
-----------------------
Tất cả APIs được re-export ở đây để giữ nguyên import paths cũ.
Frontend gọi: erp.api.erp_sis.report_card.approval.approve_class_reports
→ Vẫn hoạt động sau refactor

Structure:
----------
- single.py: Single report approval APIs (approve_level_1, approve_level_2, etc.)
- batch.py: Batch operations (submit_class_reports, approve_class_reports, etc.)
- queries.py: Pending approvals queries (get_pending_approvals, get_pending_approvals_grouped)
- config.py: Config + Subject managers + Teacher permissions
- utils.py: Notification, HTML rendering utilities
"""

# =============================================================================
# RE-EXPORTS CHO BACKWARD COMPATIBILITY
# =============================================================================

# Single report approval APIs
from .single import (
    approve_report_card,
    submit_section,
    approve_level_1,
    approve_level_2,
    review_report,
    final_publish,
    revoke_report,
)

# Batch operations
from .batch import (
    submit_class_reports,
    approve_class_reports,
    reject_class_reports,
    review_batch_reports,
    publish_batch_reports,
    reject_single_report,
)

# Pending approvals queries
from .queries import (
    get_pending_approvals,
    get_pending_approvals_grouped,
)

# Config + Subject managers + Permissions
from .config import (
    get_approval_config,
    save_approval_config,
    get_subject_managers,
    update_subject_managers,
    get_teacher_class_permissions,
)

# Utilities (internal, nhưng vẫn export cho backward compat)
from .utils import (
    render_report_card_html,
)

# =============================================================================
# BACKWARD COMPATIBILITY ALIASES
# Import helpers từ approval_helpers để code cũ vẫn hoạt động
# =============================================================================
from ..approval_helpers.helpers import (
    # Data JSON helpers
    get_subject_approval_from_data_json,
    set_subject_approval_in_data_json,
    detect_board_type_for_subject,
    
    # Counters
    compute_approval_counters,
    update_report_counters,
    
    # Permission checks
    check_user_is_level_1_approver,
    check_user_is_level_2_approver,
    check_user_is_level_3_reviewer,
    check_user_is_level_4_approver,
    check_user_has_manager_role,
    
    # Level 3 check
    can_approve_level_3,
    
    # Notification
    send_report_card_notification,
    
    # Approval history
    add_approval_history,
    
    # Utility
    get_section_name,
    get_teacher_for_user,
)

# Aliases với prefix _ (backward compat cho code cũ dùng internal functions)
_get_subject_approval_from_data_json = get_subject_approval_from_data_json
_set_subject_approval_in_data_json = set_subject_approval_in_data_json
_compute_approval_counters = compute_approval_counters
_update_report_counters = update_report_counters
_can_approve_level_3 = can_approve_level_3
_check_user_is_level_1_approver = check_user_is_level_1_approver
_check_user_is_level_2_approver = check_user_is_level_2_approver
_check_user_is_level_3_reviewer = check_user_is_level_3_reviewer
_check_user_is_level_4_approver = check_user_is_level_4_approver
_add_approval_history = add_approval_history
_send_report_card_notification = send_report_card_notification

# =============================================================================
# __all__ - Explicit exports
# =============================================================================
__all__ = [
    # Single report APIs
    "approve_report_card",
    "submit_section",
    "approve_level_1",
    "approve_level_2",
    "review_report",
    "final_publish",
    "revoke_report",
    
    # Batch operations
    "submit_class_reports",
    "approve_class_reports",
    "reject_class_reports",
    "review_batch_reports",
    "publish_batch_reports",
    "reject_single_report",
    
    # Queries
    "get_pending_approvals",
    "get_pending_approvals_grouped",
    
    # Config
    "get_approval_config",
    "save_approval_config",
    "get_subject_managers",
    "update_subject_managers",
    "get_teacher_class_permissions",
    
    # Utils
    "render_report_card_html",
    
    # Helper re-exports
    "get_subject_approval_from_data_json",
    "set_subject_approval_in_data_json",
    "compute_approval_counters",
    "update_report_counters",
    "check_user_is_level_1_approver",
    "check_user_is_level_2_approver",
    "check_user_is_level_3_reviewer",
    "check_user_is_level_4_approver",
    "add_approval_history",
    "send_report_card_notification",
]
