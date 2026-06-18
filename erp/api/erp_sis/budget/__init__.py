"""
Budget API Module - Module Ngân sách
Quản lý ngân sách năm theo phòng ban, duyệt nhiều cấp cấu hình được.
Ngân sách duyệt 1 lần/năm học, không điều chỉnh giữa năm.

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
    list_departments,
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

# Approval Config (cấu hình luồng duyệt)
from .approval_config import (
    list_approval_configs,
    get_approval_config,
    upsert_approval_config,
    delete_approval_config,
)

# Dashboard (số liệu Trang chủ)
from .dashboard import (
    get_dashboard,
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
    "list_departments",
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
    # Approval Config
    "list_approval_configs",
    "get_approval_config",
    "upsert_approval_config",
    "delete_approval_config",
    # Dashboard
    "get_dashboard",
]
