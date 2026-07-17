# -*- coding: utf-8 -*-
"""VỎ TƯƠNG THÍCH — giữ sống đường dẫn API cũ `erp.api.crm.reports_v2.*`. SẼ XOÁ.

Code thật đã chuyển sang `reports_school_year.py`. Đổi tên vì "v2" gây hiểu nhầm: nó
KHÔNG phải bản thay thế `reports.py`, mà là báo cáo đo TRỤC KHÁC — snapshot theo năm học
mục tiêu, thay vì đếm sự kiện trong khoảng ngày.

ĐỪNG THÊM CODE VÀO ĐÂY — sửa ở `reports_school_year.py`.

XOÁ cùng lúc với `reports.py`, khi FE mới đã lên hết production.
"""

from erp.api.crm.reports_school_year import (  # noqa: F401
    get_admission_profile_progress,
    get_course_activity_dashboard,
    get_enrolled_demographics,
    get_enrollment_progress_gauge,
    get_enrollment_target_progress,
    get_entrance_exam_activity_dashboard,
    get_event_activity_dashboard,
    get_kpi_member_funnel,
    get_kpi_overview,
    get_lead_filter_fields,
    get_overview_snapshot,
    get_pic_breakdown,
    get_source_breakdown,
    get_source_funnel_detail,
    get_source_lead_levels,
    get_status_by_grade,
    get_task_list,
)
