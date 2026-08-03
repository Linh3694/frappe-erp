# -*- coding: utf-8 -*-
"""
Cấu hình cột và chuẩn hóa giá trị cho luồng nhập Excel các danh mục Bus.

File này cố ý KHÔNG import frappe: toàn bộ là hàm thuần, test chạy được bằng
python3 trên máy lập trình viên mà không cần dựng site.
"""

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class ColumnSpec:
    """Một cột trong file Excel và trường tương ứng trong doctype."""

    header: str
    field: str
    required: bool = False
    normalizer: Optional[str] = None
    default: str = ""


@dataclass(frozen=True)
class ImportSpec:
    """Cấu hình nhập Excel của một danh mục Bus."""

    key: str
    doctype: str
    entity_label: str
    columns: Tuple[ColumnSpec, ...]
    dedupe_fields: Tuple[str, ...]


def _fold(text: str) -> str:
    """Bỏ dấu tiếng Việt, hạ chữ thường, gộp khoảng trắng — để so khớp giá trị nhập."""
    normalized = unicodedata.normalize("NFD", text)
    without_marks = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    without_marks = without_marks.replace("đ", "d").replace("Đ", "D")
    return " ".join(without_marks.lower().split())


def normalize_cell(value: Any) -> str:
    """Đưa giá trị ô Excel về chuỗi đã cắt khoảng trắng; số nguyên không kèm đuôi .0."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else str(value).strip()
    if isinstance(value, int):
        return str(value)
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


_GENDER_MAP = {
    "nam": "Male",
    "male": "Male",
    "nu": "Female",
    "female": "Female",
    "khac": "Other",
    "other": "Other",
}

_STATUS_MAP = {
    "dang hoat dong": "Active",
    "hoat dong": "Active",
    "active": "Active",
    "ngung hoat dong": "Inactive",
    "khong hoat dong": "Inactive",
    "inactive": "Inactive",
}

_POINT_TYPE_MAP = {
    "don": "Đón",
    "tra": "Trả",
    "ca hai": "Cả hai",
    "both": "Cả hai",
}

_NORMALIZERS = {
    "gender": _GENDER_MAP,
    "status": _STATUS_MAP,
    "point_type": _POINT_TYPE_MAP,
}


def _normalize_choice(kind: str, raw: str) -> Optional[str]:
    return _NORMALIZERS[kind].get(_fold(raw))


_PERSON_COLUMNS = (
    ColumnSpec("Họ tên", "full_name", required=True),
    ColumnSpec("Giới tính", "gender", required=True, normalizer="gender"),
    ColumnSpec("CCCD", "citizen_id", required=True),
    ColumnSpec("Số điện thoại", "phone_number", required=True),
    ColumnSpec("Nhà thầu", "contractor", required=True),
    ColumnSpec("Địa chỉ", "address", required=True),
    ColumnSpec("Trạng thái", "status", normalizer="status", default="Active"),
)

BUS_IMPORT_SPECS: Dict[str, ImportSpec] = {
    "driver": ImportSpec(
        key="driver",
        doctype="SIS Bus Driver",
        entity_label="tài xế",
        columns=_PERSON_COLUMNS,
        dedupe_fields=("citizen_id",),
    ),
    "monitor": ImportSpec(
        key="monitor",
        doctype="SIS Bus Monitor",
        entity_label="giám sát",
        columns=_PERSON_COLUMNS,
        dedupe_fields=("citizen_id",),
    ),
    "transportation": ImportSpec(
        key="transportation",
        doctype="SIS Bus Transportation",
        entity_label="phương tiện",
        columns=(
            ColumnSpec("Biển số", "license_plate", required=True),
            ColumnSpec("Loại xe", "vehicle_type", required=True),
            ColumnSpec("Trạng thái", "status", normalizer="status", default="Active"),
        ),
        dedupe_fields=("license_plate",),
    ),
    "pickup_point": ImportSpec(
        key="pickup_point",
        doctype="SIS Bus Pickup Point",
        entity_label="điểm đón",
        columns=(
            ColumnSpec("Tên điểm đón", "point_name", required=True),
            ColumnSpec("Mã điểm đón", "point_code"),
            ColumnSpec("Loại điểm", "point_type", normalizer="point_type", default="Cả hai"),
            ColumnSpec("Địa chỉ", "address"),
            ColumnSpec("Mô tả", "description"),
            ColumnSpec("Trạng thái", "status", normalizer="status", default="Active"),
        ),
        dedupe_fields=("point_name",),
    ),
    "route": ImportSpec(
        key="route",
        doctype="SIS Bus Route",
        entity_label="tuyến đường",
        columns=(
            ColumnSpec("Tên tuyến", "route_name", required=True),
            ColumnSpec("Mã xe", "vehicle_code", required=True),
            ColumnSpec("Biển số", "license_plate", required=True),
            ColumnSpec("CCCD tài xế", "driver_citizen_id", required=True),
            ColumnSpec("CCCD giám sát 1", "monitor1_citizen_id", required=True),
            ColumnSpec("CCCD giám sát 2", "monitor2_citizen_id"),
            ColumnSpec("Trạng thái", "status", normalizer="status", default="Active"),
        ),
        dedupe_fields=("route_name",),
    ),
    "route_student": ImportSpec(
        key="route_student",
        doctype="SIS Bus Route Student",
        entity_label="học sinh trong tuyến",
        columns=(
            ColumnSpec("Tên tuyến", "route_name", required=True),
            ColumnSpec("Mã học sinh", "student_code", required=True),
            ColumnSpec("Thứ tự đón", "pickup_order", required=True),
            ColumnSpec("Điểm đón", "pickup_location"),
            ColumnSpec("Điểm trả", "drop_off_location"),
        ),
        dedupe_fields=("route_name", "student_code"),
    ),
    "student": ImportSpec(
        key="student",
        doctype="SIS Bus Student",
        entity_label="học sinh",
        columns=(
            ColumnSpec("Mã học sinh", "student_code", required=True),
            ColumnSpec("Tên tuyến", "route_name"),
            ColumnSpec("Trạng thái", "status", normalizer="status", default="Active"),
        ),
        dedupe_fields=("student_code",),
    ),
}


#: Nhập Excel chỉ hỗ trợ "cấu hình chung cho cả tuần" — các thứ trong tuần học.
BUS_WEEKDAYS: Tuple[str, ...] = ("Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6")


def weekly_trip_types(
    values: Dict[str, str], row_num: int
) -> Tuple[Optional[Tuple[str, ...]], Optional[str]]:
    """
    Suy lượt đi/về từ hai cột địa điểm: điền cột nào thì học sinh đi lượt đó.
    Điền cả hai → cả Đón và Trả; để trống cả hai → lỗi vì không biết xếp lượt nào.
    """
    trip_types: List[str] = []
    if (values.get("pickup_location") or "").strip():
        trip_types.append("Đón")
    if (values.get("drop_off_location") or "").strip():
        trip_types.append("Trả")

    if not trip_types:
        return None, (
            f"Dòng {row_num}: phải điền ít nhất một trong hai cột "
            "'Điểm đón' hoặc 'Điểm trả' để biết học sinh đi lượt nào"
        )
    return tuple(trip_types), None


def parse_pickup_order(raw: str, row_num: int) -> Tuple[Optional[int], Optional[str]]:
    """Thứ tự đón phải là số nguyên dương."""
    try:
        order = int(str(raw).strip())
    except (TypeError, ValueError):
        return None, f"Dòng {row_num}: cột 'Thứ tự đón' phải là số ('{raw}')"
    if order <= 0:
        return None, f"Dòng {row_num}: cột 'Thứ tự đón' phải lớn hơn 0 ('{raw}')"
    return order, None


def missing_headers(spec: ImportSpec, headers: List[str]) -> List[str]:
    """Các cột bắt buộc chưa có trong hàng tiêu đề của file."""
    present = {str(h).strip() for h in headers if h}
    return [col.header for col in spec.columns if col.required and col.header not in present]


def parse_row(
    spec: ImportSpec, row: Dict[str, Any], row_num: int
) -> Tuple[Optional[Dict[str, str]], Optional[str]]:
    """
    Đọc một dòng đã map theo tiêu đề → dict giá trị trường.
    Trả (giá trị, None) khi hợp lệ, hoặc (None, thông báo lỗi tiếng Việt kèm số dòng.
    """
    values: Dict[str, str] = {}
    for col in spec.columns:
        raw = normalize_cell(row.get(col.header))
        if not raw:
            if col.required:
                return None, f"Dòng {row_num}: thiếu giá trị cột '{col.header}'"
            values[col.field] = col.default
            continue
        if col.normalizer:
            mapped = _normalize_choice(col.normalizer, raw)
            if not mapped:
                return None, f"Dòng {row_num}: giá trị cột '{col.header}' không hợp lệ ('{raw}')"
            values[col.field] = mapped
            continue
        values[col.field] = raw
    return values, None


def _extract_key_name(message: str) -> Optional[str]:
    """Trích tên khóa từ phần ``for key '...'`` trong thông báo MariaDB."""
    match = re.search(r"for key\s+'([^']+)'", message, re.IGNORECASE)
    return match.group(1) if match else None


def _message_outside_quotes(message: str) -> str:
    """Bỏ giá trị trong dấu nháy đơn để tránh khớp nhầm tên trường từ dữ liệu."""
    return re.sub(r"'[^']*'", "''", message)


def _field_matches_key(field: str, key_name: str) -> bool:
    """Khớp tên trường với tên khóa (trọn từ, hỗ trợ tiền tố bảng/index)."""
    field_lower = field.lower()
    key_lower = key_name.lower()
    if field_lower == key_lower:
        return True
    # Phần sau dấu chấm (ví dụ tabSIS Bus Driver.phone_number)
    if key_lower.split(".")[-1] == field_lower:
        return True
    # Khớp trọn từ — tránh ``code`` khớp nhầm ``driver_code``
    pattern = r"(?<![a-z0-9_])" + re.escape(field_lower) + r"(?![a-z0-9_])"
    return bool(re.search(pattern, key_lower))


def _field_in_text(field: str, text: str) -> bool:
    """Kiểm tra tên trường xuất hiện trọn từ trong text (dùng cho fallback)."""
    field_lower = field.lower()
    pattern = r"(?<![a-z0-9_])" + re.escape(field_lower) + r"(?![a-z0-9_])"
    return bool(re.search(pattern, text, re.IGNORECASE))


def friendly_unique_error(message: str, spec: ImportSpec, row_num: int) -> Optional[str]:
    """
    Đổi lỗi trùng ràng buộc unique của Frappe/MariaDB thành câu tiếng Việt nêu đúng tên cột.
    Trả None nếu không phải lỗi trùng.
    """
    lowered = (message or "").lower()
    if "duplicate" not in lowered and "already exists" not in lowered:
        return None

    key_name = _extract_key_name(message or "")
    if key_name:
        # Ưu tiên so khớp theo tên khóa, không quét giá trị dữ liệu trong dấu nháy
        for col in spec.columns:
            if col.field and _field_matches_key(col.field, key_name):
                return f"Dòng {row_num}: giá trị cột '{col.header}' đã tồn tại trong hệ thống"
    else:
        # Fallback: chỉ xét phần thông báo ngoài các giá trị trong dấu nháy
        search_text = _message_outside_quotes(message or "")
        for col in spec.columns:
            if col.field and _field_in_text(col.field, search_text):
                return f"Dòng {row_num}: giá trị cột '{col.header}' đã tồn tại trong hệ thống"

    return f"Dòng {row_num}: dữ liệu trùng với bản ghi đã có trong hệ thống"
