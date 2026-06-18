"""
Budget Period APIs - kì ngân sách.
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

from .utils import (
    PERIOD_DT,
    PLAN_DT,
    _get_request_data,
    _department_unit_type,
    _is_finance,
    list_budget_departments,
    ORG_UNIT_DT,
)

VALID_STATUS = ("Draft", "Open", "Closed")


def _period_to_dict(doc):
    return {
        "name": doc.name,
        "school_year_id": doc.school_year_id,
        "status": doc.status,
    }


@frappe.whitelist(allow_guest=False)
def list_periods(status=None):
    try:
        filters = {}
        if status:
            filters["status"] = status
        names = frappe.get_all(PERIOD_DT, filters=filters, pluck="name", order_by="creation desc")
        data = [_period_to_dict(frappe.get_doc(PERIOD_DT, n)) for n in names]
        return list_response(data)
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "List Budget Periods Error")
        return error_response(f"Lỗi khi lấy danh sách kì ngân sách: {str(e)}")


@frappe.whitelist(allow_guest=False)
def get_period(name=None):
    name = name or _get_request_data().get("name")
    if not name:
        return validation_error_response("Thiếu name", {"name": ["Bắt buộc"]})
    if not frappe.db.exists(PERIOD_DT, name):
        return not_found_response(f"Không tìm thấy kì ngân sách: {name}")
    return single_item_response(_period_to_dict(frappe.get_doc(PERIOD_DT, name)))


@frappe.whitelist(allow_guest=False)
def create_period():
    if not _is_finance():
        return error_response("Bạn không có quyền tạo kì ngân sách")
    data = _get_request_data()
    if not data.get("school_year_id"):
        return validation_error_response("Thiếu school_year_id", {"school_year_id": ["Bắt buộc"]})
    try:
        doc = frappe.new_doc(PERIOD_DT)
        doc.school_year_id = data["school_year_id"]
        doc.status = data.get("status") or "Draft"
        doc.insert(ignore_permissions=True)
        frappe.db.commit()

        result = _period_to_dict(doc)
        # Cảnh báo phòng chưa có trưởng phòng (không ai nộp được) — toàn trường
        result["warnings"] = _departments_without_leader()
        return single_item_response(result, message="Tạo kì ngân sách thành công")
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(frappe.get_traceback(), "Create Budget Period Error")
        return error_response(f"Lỗi khi tạo kì ngân sách: {str(e)}")


@frappe.whitelist(allow_guest=False)
def update_period():
    if not _is_finance():
        return error_response("Bạn không có quyền cập nhật kì ngân sách")
    data = _get_request_data()
    name = data.get("name")
    if not name or not frappe.db.exists(PERIOD_DT, name):
        return not_found_response(f"Không tìm thấy kì ngân sách: {name}")
    try:
        doc = frappe.get_doc(PERIOD_DT, name)
        for f in ("school_year_id",):
            if f in data:
                setattr(doc, f, data.get(f))
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        return single_item_response(_period_to_dict(doc), message="Cập nhật thành công")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Lỗi khi cập nhật kì ngân sách: {str(e)}")


@frappe.whitelist(allow_guest=False)
def set_period_status():
    """Đổi trạng thái kì: Draft/Open/Closed."""
    if not _is_finance():
        return error_response("Bạn không có quyền đổi trạng thái kì ngân sách")
    data = _get_request_data()
    name = data.get("name")
    status = data.get("status")
    if not name or not frappe.db.exists(PERIOD_DT, name):
        return not_found_response(f"Không tìm thấy kì ngân sách: {name}")
    if status not in VALID_STATUS:
        return validation_error_response(
            "Trạng thái không hợp lệ", {"status": [f"Phải thuộc {VALID_STATUS}"]}
        )
    try:
        doc = frappe.get_doc(PERIOD_DT, name)
        doc.status = status
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        return single_item_response(_period_to_dict(doc), message=f"Đã chuyển kì sang {status}")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Lỗi khi đổi trạng thái: {str(e)}")


@frappe.whitelist(allow_guest=False)
def list_departments(campus_id=None):
    """Danh sách đơn vị cấp 'Phòng' (được phép nộp ngân sách) để đổ dropdown."""
    return list_response(list_budget_departments(campus_id))


def _departments_without_leader(campus_id=None):
    """Danh sách phòng (cấp Phòng) chưa gán trưởng phòng -> cảnh báo cho TC (toàn trường)."""
    dept_type = _department_unit_type()
    if not dept_type:
        return []
    filters = {"unit_type": dept_type, "is_active": 1}
    if campus_id:
        filters["campus_id"] = campus_id
    units = frappe.get_all(ORG_UNIT_DT, filters=filters, fields=["name", "unit_name_vn"])
    result = []
    for u in units:
        has_leader = frappe.db.exists(
            "ERP Organization Unit Leader", {"parent": u.name, "parenttype": ORG_UNIT_DT}
        )
        if not has_leader:
            result.append({"department": u.name, "department_name": u.unit_name_vn})
    return result
