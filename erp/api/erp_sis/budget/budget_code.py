"""
Budget Code APIs - master danh mục mã ngân sách.
"""

import frappe
from frappe import _

from erp.utils.api_response import (
    list_response,
    single_item_response,
    success_response,
    error_response,
    not_found_response,
    validation_error_response,
)

from .utils import CODE_DT, _get_request_data, _parse, _is_finance


def _code_to_dict(doc):
    return {
        "name": doc.name,
        "budget_code": doc.budget_code,
        "account_item": doc.account_item,
        "is_active": doc.is_active,
        "parent_budget_code": doc.parent_budget_code,
        "is_group": doc.is_group,
        "level": doc.level,
        "applicable_departments": [
            {"department": d.department, "department_name": d.department_name}
            for d in (doc.applicable_departments or [])
        ],
    }


@frappe.whitelist(allow_guest=False)
def list_budget_codes(is_active=None):
    """Danh sách mã ngân sách (dùng chung toàn trường; lọc theo trạng thái)."""
    try:
        filters = {}
        if is_active is not None:
            filters["is_active"] = 1 if str(is_active) in ("1", "true", "True") else 0

        # Sắp theo cây (lft) để hiển thị phân cấp đúng thứ tự
        names = frappe.get_all(CODE_DT, filters=filters, pluck="name", order_by="lft asc")
        data = [_code_to_dict(frappe.get_doc(CODE_DT, n)) for n in names]
        return list_response(data)
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "List Budget Codes Error")
        return error_response(f"Lỗi khi lấy danh sách mã ngân sách: {str(e)}")


@frappe.whitelist(allow_guest=False)
def get_budget_code(name=None):
    name = name or _get_request_data().get("name")
    if not name:
        return validation_error_response("Thiếu name", {"name": ["Bắt buộc"]})
    if not frappe.db.exists(CODE_DT, name):
        return not_found_response(f"Không tìm thấy mã ngân sách: {name}")
    return single_item_response(_code_to_dict(frappe.get_doc(CODE_DT, name)))


@frappe.whitelist(allow_guest=False)
def upsert_budget_code():
    """Tạo mới / cập nhật mã ngân sách (chỉ Phòng TC)."""
    if not _is_finance():
        return error_response("Bạn không có quyền quản lý mã ngân sách")

    data = _get_request_data()
    name = data.get("name")
    budget_code = data.get("budget_code")

    if not name and not budget_code:
        return validation_error_response(
            "Thiếu trường bắt buộc", {"budget_code": ["Bắt buộc"]}
        )

    departments = _parse(data.get("applicable_departments")) or []

    try:
        if name and frappe.db.exists(CODE_DT, name):
            doc = frappe.get_doc(CODE_DT, name)
        else:
            doc = frappe.new_doc(CODE_DT)

        if budget_code is not None:
            doc.budget_code = budget_code
        if "account_item" in data:
            doc.account_item = data.get("account_item")
        if "parent_budget_code" in data:
            doc.parent_budget_code = data.get("parent_budget_code") or None
        if "is_group" in data:
            doc.is_group = 1 if data.get("is_group") in (1, "1", True, "true") else 0
        if "is_active" in data:
            doc.is_active = 1 if data.get("is_active") in (1, "1", True, "true") else 0

        if "applicable_departments" in data:
            doc.set("applicable_departments", [])
            for d in departments:
                dept = d.get("department") if isinstance(d, dict) else d
                if dept:
                    doc.append("applicable_departments", {"department": dept})

        doc.save(ignore_permissions=True)
        frappe.db.commit()
        return single_item_response(_code_to_dict(doc), message="Lưu mã ngân sách thành công")
    except frappe.ValidationError as e:
        frappe.db.rollback()
        return error_response(str(e))
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(frappe.get_traceback(), "Upsert Budget Code Error")
        return error_response(f"Lỗi khi lưu mã ngân sách: {str(e)}")


@frappe.whitelist(allow_guest=False)
def delete_budget_code():
    if not _is_finance():
        return error_response("Bạn không có quyền xóa mã ngân sách")
    data = _get_request_data()
    name = data.get("name")
    if not name:
        return validation_error_response("Thiếu name", {"name": ["Bắt buộc"]})
    if not frappe.db.exists(CODE_DT, name):
        return not_found_response(f"Không tìm thấy mã ngân sách: {name}")

    # Chặn xóa nếu còn mã con (cây)
    has_child = frappe.db.exists(CODE_DT, {"parent_budget_code": name})
    if has_child:
        return error_response("Không thể xóa: mã ngân sách còn mã con. Hãy xóa/di chuyển mã con trước.")

    # Chặn xóa nếu đang được dùng trong plan line
    used = frappe.db.exists("ERP Budget Plan Line", {"budget_code": name})
    if used:
        return error_response("Không thể xóa: mã ngân sách đang được dùng trong kế hoạch")
    try:
        frappe.delete_doc(CODE_DT, name, ignore_permissions=True)
        frappe.db.commit()
        return success_response(message="Xóa mã ngân sách thành công")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Lỗi khi xóa: {str(e)}")
