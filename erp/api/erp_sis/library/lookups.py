from typing import List

import frappe
from erp.utils.api_response import (
    success_response,
    error_response,
    list_response,
    validation_error_response,
    not_found_response,
)

from ._constants import LOOKUP_DTYPE, VALID_LOOKUP_TYPES
from ._common import _require_library_role, _get_json_payload, _import_excel_to_rows

@frappe.whitelist(allow_guest=False)
def list_lookups(type: str | None = None):
    if (resp := _require_library_role()):
        return resp
    try:
        # Lấy type từ nhiều nguồn - ưu tiên theo thứ tự
        # 1. Function parameter (từ frappe.call)
        # 2. Query string params (request.args)
        # 3. form_dict (frappe internal)
        # 4. JSON payload
        lookup_type = (
            type 
            or (frappe.request.args.get("type") if frappe.request else None)
            or frappe.form_dict.get("type") 
            or _get_json_payload().get("type")
        )
        
        filters = {}
        if lookup_type:
            if lookup_type not in VALID_LOOKUP_TYPES:
                return validation_error_response(
                    message="Loại danh mục không hợp lệ",
                    errors={"type": ["invalid"]},
                )
            filters["lookup_type"] = lookup_type

        items = frappe.get_all(
            LOOKUP_DTYPE,
            filters=filters,
            fields=["name as id", "code", "lookup_type as type", "name_vi as name", "language", "storage"],
            order_by="modified desc",
        )
        return list_response(data=items, message="Fetched lookups")
    except Exception as ex:
        frappe.log_error(f"list_lookups failed: {ex}")
        return error_response(message="Không lấy được danh mục", code="LOOKUP_LIST_ERROR")


@frappe.whitelist(allow_guest=False)
def create_lookup():
    """
    Tạo danh mục thư viện.
    Schema theo từng loại:
    - document_type: name (Tên đầu mục) + code (Mã) - cả 2 bắt buộc
    - series: name (Tên tùng thư) - chỉ name
    - author: name (Tên tác giả) - chỉ name  
    - convention: code (Mã đặc biệt) + storage (Nơi lưu trữ) + language (Ngôn ngữ)
    """
    if (resp := _require_library_role()):
        return resp
    data = _get_json_payload()
    lookup_type = data.get("type")
    if lookup_type not in VALID_LOOKUP_TYPES:
        return validation_error_response(message="Loại danh mục không hợp lệ", errors={"type": ["invalid"]})

    code = (data.get("code") or "").strip()
    name = (data.get("name") or "").strip()
    language = (data.get("language") or "").strip()
    storage = (data.get("storage") or "").strip()

    # Validate theo từng loại
    if lookup_type == "document_type":
        # Phân loại tài liệu: cần name (Tên đầu mục) + code (Mã)
        if not name:
            return validation_error_response(message="Thiếu tên đầu mục", errors={"name": ["required"]})
        if not code:
            return validation_error_response(message="Thiếu mã", errors={"code": ["required"]})
    elif lookup_type == "series":
        # Tùng thư: chỉ cần name (Tên tùng thư)
        if not name:
            return validation_error_response(message="Thiếu tên tùng thư", errors={"name": ["required"]})
    elif lookup_type == "author":
        # Tác giả: chỉ cần name (Tên tác giả)
        if not name:
            return validation_error_response(message="Thiếu tên tác giả", errors={"name": ["required"]})
    elif lookup_type == "convention":
        # Mã quy ước: code (Mã đặc biệt) + storage (Nơi lưu trữ) + language (Ngôn ngữ)
        if not code:
            return validation_error_response(message="Thiếu mã đặc biệt", errors={"code": ["required"]})
        if not storage:
            return validation_error_response(message="Thiếu nơi lưu trữ", errors={"storage": ["required"]})
        if not language:
            return validation_error_response(message="Thiếu ngôn ngữ", errors={"language": ["required"]})

    try:
        doc = frappe.get_doc(
            {
                "doctype": LOOKUP_DTYPE,
                "lookup_type": lookup_type,
                "code": code or None,
                "name_vi": name or None,
                "language": language or None,
                "storage": storage or None,
            }
        )
        doc.insert(ignore_permissions=True)
        return success_response(
            data={
                "id": doc.name, 
                "code": doc.code, 
                "name": doc.name_vi, 
                "type": doc.lookup_type, 
                "language": doc.language, 
                "storage": doc.storage
            },
            message="Tạo danh mục thành công",
        )
    except Exception as ex:
        frappe.log_error(f"create_lookup failed: {ex}")
        return error_response(message="Không tạo được danh mục", code="LOOKUP_CREATE_ERROR")


@frappe.whitelist(allow_guest=False)
def update_lookup():
    if (resp := _require_library_role()):
        return resp
    data = _get_json_payload()
    lookup_id = data.get("id")
    if not lookup_id:
        return validation_error_response(message="Thiếu id", errors={"id": ["required"]})

    try:
        doc = frappe.get_doc(LOOKUP_DTYPE, lookup_id)
        if "code" in data and data["code"]:
            doc.code = data["code"]
        if "name" in data and data["name"]:
            doc.name_vi = data["name"]
        if "language" in data:
            doc.language = data.get("language")
        if "storage" in data:
            doc.storage = data.get("storage")
        doc.save(ignore_permissions=True)
        return success_response(
            data={"id": doc.name, "code": doc.code, "name": doc.name_vi, "type": doc.lookup_type, "language": doc.language, "storage": doc.storage},
            message="Cập nhật thành công",
        )
    except frappe.DoesNotExistError:
        return not_found_response(message="Không tìm thấy danh mục", code="LOOKUP_NOT_FOUND")
    except Exception as ex:
        frappe.log_error(f"update_lookup failed: {ex}")
        return error_response(message="Không cập nhật được danh mục", code="LOOKUP_UPDATE_ERROR")


@frappe.whitelist(allow_guest=False)
def delete_lookup():
    if (resp := _require_library_role()):
        return resp
    data = _get_json_payload()
    lookup_id = data.get("id")
    if not lookup_id:
        return validation_error_response(message="Thiếu id", errors={"id": ["required"]})
    try:
        frappe.delete_doc(LOOKUP_DTYPE, lookup_id, ignore_permissions=True)
        return success_response(data=True, message="Đã xóa danh mục")
    except Exception as ex:
        frappe.log_error(f"delete_lookup failed: {ex}")
        return error_response(message="Không xóa được danh mục", code="LOOKUP_DELETE_ERROR")


@frappe.whitelist(allow_guest=False)
def import_lookups_excel():
    """
    Upload Excel for lookups.
    Expected columns theo từng loại:
    - document_type: name/tên (Tên đầu mục), code/mã (Mã)
    - series: name/tên (Tên tùng thư)
    - author: name/tên (Tên tác giả)
    - convention: code/mã (Mã đặc biệt), storage/nơi lưu trữ, language/ngôn ngữ
    """
    if (resp := _require_library_role()):
        return resp
    
    # Với multipart/form-data, lấy type từ nhiều nguồn
    lookup_type = (
        frappe.request.form.get("type") 
        or (frappe.request.args.get("type") if frappe.request else None)
        or frappe.form_dict.get("type") 
        or _get_json_payload().get("type")
    )
    if lookup_type not in VALID_LOOKUP_TYPES:
        return validation_error_response(message="Loại danh mục không hợp lệ", errors={"type": ["invalid"]})

    if "file" not in frappe.request.files:
        return validation_error_response(message="Thiếu file Excel", errors={"file": ["required"]})

    file = frappe.request.files["file"]
    rows = _import_excel_to_rows(file.stream.read())
    created = 0
    errors: List[str] = []

    for idx, row in enumerate(rows, start=2):
        # Đọc các cột với nhiều tên có thể
        code = str(row.get("code") or row.get("mã") or row.get("Mã") or row.get("Mã đặc biệt") or "").strip()
        name = str(row.get("name") or row.get("tên") or row.get("Tên") or row.get("Tên đầu mục") or row.get("Tên tùng thư") or row.get("Tên tác giả") or "").strip()
        language = str(row.get("language") or row.get("ngôn ngữ") or row.get("Ngôn ngữ") or "").strip()
        storage = str(row.get("storage") or row.get("nơi lưu trữ") or row.get("Nơi lưu trữ") or row.get("kho") or row.get("Kho") or "").strip()

        # Validate theo từng loại
        if lookup_type == "document_type":
            if not name or not code:
                errors.append(f"Dòng {idx}: thiếu tên đầu mục hoặc mã")
                continue
        elif lookup_type in {"series", "author"}:
            if not name:
                errors.append(f"Dòng {idx}: thiếu tên")
                continue
        elif lookup_type == "convention":
            if not code:
                errors.append(f"Dòng {idx}: thiếu mã đặc biệt")
                continue
            if not storage:
                errors.append(f"Dòng {idx}: thiếu nơi lưu trữ")
                continue
            if not language:
                errors.append(f"Dòng {idx}: thiếu ngôn ngữ")
                continue

        try:
            doc = frappe.get_doc(
                {
                    "doctype": LOOKUP_DTYPE,
                    "lookup_type": lookup_type,
                    "code": code or None,
                    "name_vi": name or None,
                    "language": language or None,
                    "storage": storage or None,
                }
            )
            doc.insert(ignore_permissions=True)
            created += 1
        except Exception as ex:
            errors.append(f"Dòng {idx}: {ex}")

    return success_response(
        data={"success_count": created, "total_count": len(rows), "errors": errors},
        message="Đã import danh mục",
    )
