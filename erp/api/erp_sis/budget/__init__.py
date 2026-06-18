"""
Budget API Module - Module Ngân sách
Quản lý ngân sách năm theo phòng ban, duyệt nhiều cấp cấu hình được, điều chỉnh giữa năm.

Re-export tất cả whitelisted functions để frontend gọi qua path:
/api/method/erp.api.erp_sis.budget.<function_name>
"""

# Budget Code (master mã ngân sách)
from .budget_code import (
    list_budget_codes,
    get_budget_code,
    upsert_budget_code,
    delete_budget_code,
)

# Budget Period (kì ngân sách)
from .period import (
    list_periods,
    get_period,
    create_period,
    update_period,
    set_period_status,
)

# Budget Plan (form ngân sách phòng ban)
from .plan import (
    get_my_plans,
    get_all_plans,
    get_plan,
    upsert_plan,
    submit_plan,
    approve_plan,
    return_plan,
    unsubmit_plan,
    activate_plan,
    close_plan,
    get_plan_history,
    get_my_department,
)

# Budget Adjustment (điều chỉnh giữa năm)
from .adjustment import (
    list_adjustments,
    get_adjustment,
    create_adjustment,
    update_adjustment,
    submit_adjustment,
    approve_adjustment,
    return_adjustment,
    get_effective_budget,
)

# Approval Config (cấu hình luồng duyệt)
from .approval_config import (
    list_approval_configs,
    get_approval_config,
    upsert_approval_config,
    delete_approval_config,
)

__all__ = [
    # Budget Code
    "list_budget_codes",
    "get_budget_code",
    "upsert_budget_code",
    "delete_budget_code",
    # Period
    "list_periods",
    "get_period",
    "create_period",
    "update_period",
    "set_period_status",
    # Plan
    "get_my_plans",
    "get_all_plans",
    "get_plan",
    "upsert_plan",
    "submit_plan",
    "approve_plan",
    "return_plan",
    "unsubmit_plan",
    "activate_plan",
    "close_plan",
    "get_plan_history",
    "get_my_department",
    # Adjustment
    "list_adjustments",
    "get_adjustment",
    "create_adjustment",
    "update_adjustment",
    "submit_adjustment",
    "approve_adjustment",
    "return_adjustment",
    "get_effective_budget",
    # Approval Config
    "list_approval_configs",
    "get_approval_config",
    "upsert_approval_config",
    "delete_approval_config",
]
