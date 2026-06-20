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
from .budget_code_import import (
    download_budget_code_import_template,
    import_budget_codes_excel,
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
    get_pending_plans,
    get_reviewable_plans,
    get_all_plans,
    get_plan,
    upsert_plan,
    submit_plan,
    approve_plan,
    return_plan,
    unsubmit_plan,
    create_amendment,
    activate_plan,
    close_plan,
    get_plan_history,
    get_my_department,
)

# Budget Plan Comment (bình luận theo khoản mục)
from .comment import (
    list_plan_comments,
    get_plan_comment_counts,
    add_plan_comment,
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
    "download_budget_code_import_template",
    "import_budget_codes_excel",
    # Period
    "list_periods",
    "get_period",
    "create_period",
    "update_period",
    "set_period_status",
    "list_departments",
    # Plan
    "get_my_plans",
    "get_pending_plans",
    "get_reviewable_plans",
    "get_all_plans",
    "get_plan",
    "upsert_plan",
    "submit_plan",
    "approve_plan",
    "return_plan",
    "unsubmit_plan",
    "create_amendment",
    "activate_plan",
    "close_plan",
    "get_plan_history",
    "get_my_department",
    # Plan Comment
    "list_plan_comments",
    "get_plan_comment_counts",
    "add_plan_comment",
    # Dashboard
    "get_dashboard",
]
