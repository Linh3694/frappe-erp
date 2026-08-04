# Copyright (c) 2026, Wellspring and contributors
# For license information, please see license.txt

"""
Nguồn sự thật DUY NHẤT cho danh sách thứ sinh hoạt câu lạc bộ.

Trước đây danh sách này nằm rải rác: enum trong `sis_club_offering.json`, một
bản `DAY_LABELS_*` trong doctype offering, một bản nữa trong
`utils/club_registration.py`, cộng năm câu SQL `FIELD(day_of_week, 'mon', …)`.
Sáu chỗ phải sửa tay và giữ khớp nhau. Module này gom lại; các module cũ
re-export để mọi import sẵn có không phải đổi.

Lưu ý: enum trong `sis_club_offering.json` VẪN phải khớp thủ công với
`DAY_ORDER` — Frappe đọc options từ JSON lúc migrate, không gọi được Python.
`assert_enum_matches()` bên dưới dùng trong test/patch để phát hiện lệch.
"""

import json

DAY_ORDER = ["mon", "tue", "wed", "thu", "fri", "sat"]

DAY_LABELS_VN = {
    "mon": "Thứ 2",
    "tue": "Thứ 3",
    "wed": "Thứ 4",
    "thu": "Thứ 5",
    "fri": "Thứ 6",
    "sat": "Thứ 7",
}

DAY_LABELS_EN = {
    "mon": "Monday",
    "tue": "Tuesday",
    "wed": "Wednesday",
    "thu": "Thursday",
    "fri": "Friday",
    "sat": "Saturday",
}

#: Dùng trong `ORDER BY FIELD(day_of_week, …)` để khỏi viết tay chuỗi thứ.
DAY_SQL_ORDER = ",".join(f"'{d}'" for d in DAY_ORDER)


def normalize_days(value):
    """
    Đưa mọi kiểu đầu vào về danh sách thứ hợp lệ, không trùng, đúng thứ tự tuần.

    Nhận list (từ JSON body), chuỗi CSV (từ cột DB), hoặc chuỗi JSON (khi FE gửi
    `JSON.stringify`). Thứ lạ bị loại im lặng — dữ liệu rác không nên chặn cả
    thao tác lưu, và tầng validate sẽ báo nếu kết quả rỗng ngoài ý muốn.
    """
    if value is None:
        return []

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                value = json.loads(text)
            except (ValueError, TypeError):
                value = text.split(",")
        else:
            value = text.split(",")

    if not isinstance(value, (list, tuple, set)):
        return []

    seen = {str(item).strip().lower() for item in value if str(item).strip()}
    return [day for day in DAY_ORDER if day in seen]


def days_to_csv(value):
    """Danh sách thứ -> chuỗi CSV chuẩn hoá để lưu vào cột Data."""
    return ",".join(normalize_days(value))


def format_days_vn(value):
    """['tue','thu'] -> 'Thứ 3, Thứ 5' — dùng trong thông báo lỗi cho người dùng."""
    return ", ".join(DAY_LABELS_VN[day] for day in normalize_days(value))


def assert_enum_matches(options):
    """
    So `DAY_ORDER` với chuỗi options của field Select trong doctype JSON.

    Trả về danh sách chênh lệch (rỗng nghĩa là khớp). Tách ra hàm riêng để test
    gọi được mà không cần dựng Frappe.
    """
    enum_days = [line.strip() for line in (options or "").split("\n") if line.strip()]
    return {
        "missing_in_enum": [d for d in DAY_ORDER if d not in enum_days],
        "extra_in_enum": [d for d in enum_days if d not in DAY_ORDER],
    }
