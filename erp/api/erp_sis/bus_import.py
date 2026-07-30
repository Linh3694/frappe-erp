# -*- coding: utf-8 -*-
"""
Nhập Excel hàng loạt cho các danh mục Bus.

Chạy đồng bộ và trả kết quả ngay: dữ liệu danh mục chỉ ở mức vài trăm dòng nên
không cần job nền như erp/api/bulk_import.py.
"""

from typing import Any, Callable, Dict, List, Optional, Tuple

import frappe
from frappe.utils.xlsxutils import read_xlsx_file_from_attached_file

from erp.utils.api_response import error_response, success_response, validation_error_response
from erp.utils.campus_utils import get_current_campus_from_context

from .bus_import_columns import (
    BUS_IMPORT_SPECS,
    ImportSpec,
    friendly_unique_error,
    missing_headers,
    normalize_cell,
    parse_row,
)

# Số dòng lỗi / bỏ qua tối đa gửi về UI — tránh trả về danh sách quá dài
MAX_PREVIEW_ROWS = 200


class DuplicateHeaderError(ValueError):
    """File Excel có tiêu đề cột bị lặp."""

    def __init__(self, headers: List[str]):
        self.headers = headers
        super().__init__(", ".join(headers))


def _resolve_campus() -> str:
    """Campus của người dùng hiện tại; giữ fallback campus-1 như các API Bus khác."""
    return get_current_campus_from_context() or "campus-1"


def _read_rows(file_content: bytes) -> Tuple[List[str], List[Tuple[int, Dict[str, Any]]]]:
    """Đọc file .xlsx → (tiêu đề, các cặp số dòng Excel và dữ liệu dòng)."""
    data = read_xlsx_file_from_attached_file(fcontent=file_content)
    if not data:
        return [], []
    headers = [str(h).strip() if h is not None else "" for h in data[0]]
    seen_headers = set()
    duplicate_headers = []
    for header in headers:
        if not header:
            continue
        if header in seen_headers and header not in duplicate_headers:
            duplicate_headers.append(header)
        seen_headers.add(header)
    if duplicate_headers:
        raise DuplicateHeaderError(duplicate_headers)

    rows: List[Tuple[int, Dict[str, Any]]] = []
    for row_num, raw in enumerate(data[1:], start=2):
        if not any(normalize_cell(cell) for cell in raw):
            continue
        rows.append(
            (
                row_num,
                {
                    headers[idx]: (raw[idx] if idx < len(raw) else None)
                    for idx in range(len(headers))
                    if headers[idx]
                },
            )
        )
    return headers, rows


def _existing_doc_name(spec: ImportSpec, values: Dict[str, str], campus_id: str) -> Optional[str]:
    """Bản ghi đã có theo khóa chống trùng của danh mục (trong cùng campus)."""
    filters: Dict[str, Any] = {"campus_id": campus_id}
    for field in spec.dedupe_fields:
        value = values.get(field)
        if not value:
            return None
        filters[field] = value
    return frappe.db.get_value(spec.doctype, filters, "name")


def _run_import(
    spec: ImportSpec,
    rows: List[Tuple[int, Dict[str, Any]]],
    headers: List[str],
    campus_id: str,
    row_handler: Optional[Callable[[Dict[str, str], int, str], Tuple[Optional[Dict[str, Any]], Optional[str], bool]]] = None,
) -> Dict[str, Any]:
    """Duyệt từng dòng: chuẩn hóa, bỏ qua dòng trùng, tạo bản ghi, gom kết quả."""
    errors: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    success_count = 0
    seen_keys = set()

    for row_num, row in rows:
        values, parse_error = parse_row(spec, row, row_num)
        if parse_error:
            errors.append({"row": row_num, "error": parse_error})
            continue

        dedupe_key = tuple(values.get(f, "") for f in spec.dedupe_fields)
        if dedupe_key in seen_keys:
            skipped.append({"row": row_num, "error": f"Dòng {row_num}: trùng với một dòng khác trong file"})
            continue
        seen_keys.add(dedupe_key)

        if row_handler:
            payload, handler_error, should_skip = row_handler(values, row_num, campus_id)
            if should_skip:
                skipped.append({"row": row_num, "error": handler_error or f"Dòng {row_num}: đã tồn tại"})
                continue
            if handler_error:
                errors.append({"row": row_num, "error": handler_error})
                continue
        else:
            if _existing_doc_name(spec, values, campus_id):
                skipped.append({"row": row_num, "error": f"Dòng {row_num}: đã tồn tại trong hệ thống"})
                continue
            payload = dict(values)
            payload["campus_id"] = campus_id

        save_point = f"bus_import_row_{row_num}"
        frappe.db.savepoint(save_point=save_point)
        try:
            doc = frappe.get_doc({"doctype": spec.doctype, **payload})
            doc.insert()
            success_count += 1
        except Exception as ex:  # noqa: BLE001 — gom mọi lỗi tạo doc về mức dòng
            frappe.db.rollback(save_point=save_point)
            frappe.log_error(
                title=f"Lỗi import Excel {spec.doctype}, dòng {row_num}",
                message=frappe.get_traceback(),
            )
            duplicate_message = friendly_unique_error(str(ex), spec, row_num)
            if duplicate_message:
                skipped.append({"row": row_num, "error": duplicate_message})
            else:
                errors.append(
                    {
                        "row": row_num,
                        "error": (
                            f"Dòng {row_num}: không tạo được bản ghi, "
                            "vui lòng kiểm tra lại dữ liệu dòng này"
                        ),
                    }
                )

    frappe.db.commit()

    return {
        "total_rows": len(rows),
        "success_count": success_count,
        "error_count": len(errors),
        "skipped_count": len(skipped),
        "errors_preview": errors[:MAX_PREVIEW_ROWS],
        "skipped_preview": skipped[:MAX_PREVIEW_ROWS],
    }


def _summary_message(spec: ImportSpec, result: Dict[str, Any]) -> str:
    parts = [f"Đã nhập {result['success_count']} {spec.entity_label}"]
    if result["skipped_count"]:
        parts.append(f"bỏ qua {result['skipped_count']} dòng đã có")
    if result["error_count"]:
        parts.append(f"{result['error_count']} dòng lỗi")
    return ", ".join(parts)


def _import_by_key(spec_key: str, row_handler=None):
    """Khung xử lý chung cho mọi endpoint import Bus."""
    spec = BUS_IMPORT_SPECS[spec_key]

    if not frappe.request or "file" not in frappe.request.files:
        return validation_error_response("Thiếu file Excel", {"file": ["required"]})

    uploaded = frappe.request.files["file"]
    if not uploaded:
        return validation_error_response("File rỗng", {"file": ["empty"]})

    try:
        headers, rows = _read_rows(uploaded.stream.read())
    except DuplicateHeaderError as ex:
        return validation_error_response(
            f"File có cột bị lặp: {', '.join(ex.headers)}",
            {"file": ["duplicate_columns"]},
        )
    except Exception:  # noqa: BLE001
        # Chi tiết lỗi thư viện đọc file chỉ để tra cứu, không đưa ra cho người dùng
        frappe.log_error(
            title=f"Lỗi đọc file Excel import {spec.doctype}",
            message=frappe.get_traceback(),
        )
        return validation_error_response(
            "File Excel không đúng định dạng hoặc bị hỏng", {"file": ["invalid"]}
        )

    if not rows:
        return validation_error_response("File không có dữ liệu", {"file": ["empty"]})

    lacking = missing_headers(spec, headers)
    if lacking:
        return validation_error_response(
            f"File thiếu cột bắt buộc: {', '.join(lacking)}", {"file": ["missing_columns"]}
        )

    try:
        result = _run_import(spec, rows, headers, _resolve_campus(), row_handler=row_handler)
    except Exception:  # noqa: BLE001
        frappe.db.rollback()
        frappe.log_error(
            title=f"Lỗi import Excel {spec.doctype}",
            message=frappe.get_traceback(),
        )
        return error_response("Nhập Excel thất bại, vui lòng thử lại hoặc liên hệ quản trị")

    return success_response(data=result, message=_summary_message(spec, result))


@frappe.whitelist()
def import_bus_drivers():
    """Nhập danh sách tài xế từ Excel."""
    return _import_by_key("driver")


@frappe.whitelist()
def import_bus_monitors():
    """Nhập danh sách giám sát từ Excel."""
    return _import_by_key("monitor")


@frappe.whitelist()
def import_bus_transportations():
    """Nhập danh sách phương tiện từ Excel."""
    return _import_by_key("transportation")


@frappe.whitelist()
def import_bus_pickup_points():
    """Nhập danh sách điểm đón từ Excel."""
    return _import_by_key("pickup_point")


def _lookup_student_for_bus(student_code: str, campus_id: str) -> Optional[Dict[str, Any]]:
    """Hồ sơ học sinh gốc + lớp + năm học, tra theo mã học sinh trong campus."""
    found = frappe.db.sql(
        """
        SELECT
            s.student_name AS full_name,
            s.student_code,
            cs.class_id,
            cs.school_year_id
        FROM `tabCRM Student` s
        INNER JOIN `tabSIS Class Student` cs ON s.name = cs.student_id
        WHERE s.student_code = %s
            AND s.campus_id = %s
            AND cs.class_type = 'regular'
        ORDER BY cs.creation DESC, cs.name DESC
        LIMIT 1
        """,
        (student_code, campus_id),
        as_dict=True,
    )
    return found[0] if found else None


def _student_row_handler(
    values: Dict[str, str], row_num: int, campus_id: str
) -> Tuple[Optional[Dict[str, Any]], Optional[str], bool]:
    """Dựng payload SIS Bus Student từ mã học sinh; tên tuyến (nếu có) tra sang route_id."""
    student_code = values.get("student_code", "")

    if frappe.db.exists("SIS Bus Student", {"student_code": student_code, "campus_id": campus_id}):
        return None, f"Dòng {row_num}: học sinh {student_code} đã có trong danh sách xe buýt", True

    student = _lookup_student_for_bus(student_code, campus_id)
    if not student:
        return (
            None,
            f"Dòng {row_num}: không tìm thấy học sinh có mã '{student_code}' đã được xếp lớp trong campus",
            False,
        )

    payload: Dict[str, Any] = {
        "full_name": student["full_name"],
        "student_code": student["student_code"],
        "class_id": student["class_id"],
        "status": values.get("status") or "Active",
        "campus_id": campus_id,
        "school_year_id": student["school_year_id"],
    }

    route_name = values.get("route_name", "")
    if route_name:
        route_id = frappe.db.get_value(
            "SIS Bus Route", {"route_name": route_name, "campus_id": campus_id}, "name"
        )
        if not route_id:
            return None, f"Dòng {row_num}: không tìm thấy tuyến đường '{route_name}'", False
        payload["route_id"] = route_id

    return payload, None, False


@frappe.whitelist()
def import_bus_students():
    """Nhập danh sách học sinh đi xe buýt từ Excel (đối chiếu mã học sinh với CRM Student)."""
    return _import_by_key("student", row_handler=_student_row_handler)
