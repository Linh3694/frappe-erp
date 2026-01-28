# -*- coding: utf-8 -*-
"""
Report Card Approval Module
===========================

Module xử lý multi-level approval flow cho Report Card.

Flow:
- Level 1: Khối trưởng (chỉ cho Homeroom)
- Level 2: Subject Managers / Tổ trưởng
- Level 3: Reviewers (theo educational_stage)
- Level 4: Final Approvers (theo educational_stage)

Exports:
- Submit APIs: submit_section, submit_class_reports
- Approve APIs: approve_report_card, approve_level_1, approve_level_2, approve_class_reports
- Review/Publish APIs: review_report, final_publish, review_batch_reports, publish_batch_reports
- Reject APIs: reject_class_reports, reject_single_report
- Pending APIs: get_pending_approvals, get_pending_approvals_grouped
- Config APIs: get_approval_config, save_approval_config, get_subject_managers, update_subject_managers
"""

# Import từ submodules sẽ được thêm khi refactor hoàn tất
# Hiện tại vẫn export từ approval.py gốc để đảm bảo backward compatibility

# Helper exports cho các module khác sử dụng
from .helpers import (
    # Context managers
    batch_operation_savepoint,
    
    # Approval history
    add_approval_history,
    
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
    
    # Utility
    get_section_name,
    get_teacher_for_user,
)

__all__ = [
    # Helpers
    "batch_operation_savepoint",
    "add_approval_history",
    "get_subject_approval_from_data_json",
    "set_subject_approval_in_data_json",
    "detect_board_type_for_subject",
    "compute_approval_counters",
    "update_report_counters",
    "check_user_is_level_1_approver",
    "check_user_is_level_2_approver",
    "check_user_is_level_3_reviewer",
    "check_user_is_level_4_approver",
    "check_user_has_manager_role",
    "can_approve_level_3",
    "send_report_card_notification",
    "get_section_name",
    "get_teacher_for_user",
]
