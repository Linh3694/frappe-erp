# -*- coding: utf-8 -*-
"""VỎ TƯƠNG THÍCH — giữ sống đường dẫn API cũ `erp.api.crm.reports.*`. SẼ XOÁ.

Module đã tách làm 3 cho đỡ lẫn:
  - `report_common.py`       — hạ tầng dùng chung (lọc chiều, phân quyền PIC, giải kỳ)
  - `reports_period.py`      — CODE THẬT của các endpoint dưới đây (đếm sự kiện trong kỳ)
  - `reports_school_year.py` — snapshot theo năm học mục tiêu (tên cũ: reports_v2.py)

ĐỪNG THÊM CODE VÀO ĐÂY — sửa ở `reports_period.py`.

Vì sao còn tồn tại: backend và frontend là 2 repo deploy riêng. Vỏ này để deploy lệch nhau
vẫn chạy — FE bản cũ gọi `erp.api.crm.reports.*`, FE bản mới gọi `erp.api.crm.reports_period.*`,
cả hai đều sống. Frappe kiểm whitelist theo ĐỐI TƯỢNG hàm, mà `import` giữ nguyên đối tượng,
nên re-export là đủ, không cần bọc lại `@frappe.whitelist()`.

XOÁ khi FE mới đã lên hết production (xoá cả `reports_v2.py`).
"""

from erp.api.crm.reports_period import (  # noqa: F401
    get_breakdown_by_grade_campus,
    get_breakdown_by_pic,
    get_breakdown_by_source,
    get_funnel,
    get_lost_analysis,
    get_overview_kpis,
    get_status_distribution,
    get_trend,
)
