"""
Budget Approval Config APIs - cấu hình luồng duyệt (v2).
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

from .utils import CONFIG_DT, _get_request_data, _parse, _is_finance


def _step_to_dict(s):
    return {
        "step_order": s.step_order,
        "approver_role": s.approver_role,
        "can_return": s.can_return,
        "applies_to_type": s.applies_to_type,
        "min_amount": s.min_amount,
        "max_amount": s.max_amount,
        "approver_users": [{"user": u.user, "full_name": u.full_name} for u in (s.approver_users or [])],
    }


def _config_to_dict(doc):
    return {
        "name": doc.name,
        "title": doc.title,
        "campus_id": doc.campus_id,
        "school_year_id": doc.school_year_id,
        "is_active": doc.is_active,
        "plan_steps": [_step_to_dict(s) for s in (doc.plan_steps or [])],
        "adjustment_steps": [_step_to_dict(s) for s in (doc.adjustment_steps or [])],
    }


@frappe.whitelist(allow_guest=False)
def list_approval_configs(campus_id=None, school_year_id=None):
    try:
        filters = {}
        if campus_id:
            filters["campus_id"] = campus_id
        if school_year_id:
            filters["school_year_id"] = school_year_id
        names = frappe.get_all(CONFIG_DT, filters=filters, pluck="name", order_by="creation desc")
        data = [_config_to_dict(frappe.get_doc(CONFIG_DT, n)) for n in names]
        return list_response(data)
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "List Budget Approval Configs Error")
        return error_response(f"Lỗi khi lấy danh sách cấu hình: {str(e)}")


@frappe.whitelist(allow_guest=False)
def get_approval_config(name=None):
    name = name or _get_request_data().get("name")
    if not name or not frappe.db.exists(CONFIG_DT, name):
        return not_found_response(f"Không tìm thấy cấu hình: {name}")
    return single_item_response(_config_to_dict(frappe.get_doc(CONFIG_DT, name)))


def _apply_steps(doc, fieldname, steps):
    doc.set(fieldname, [])
    for s in steps or []:
        if not isinstance(s, dict):
            continue
        row = doc.append(
            fieldname,
            {
                "step_order": s.get("step_order"),
                "approver_role": s.get("approver_role"),
                "can_return": 1 if s.get("can_return") in (1, "1", True, "true") else 0,
                "applies_to_type": s.get("applies_to_type") or "All",
                "min_amount": s.get("min_amount") or 0,
                "max_amount": s.get("max_amount") or 0,
            },
        )
        for u in (s.get("approver_users") or []):
            user = u.get("user") if isinstance(u, dict) else u
            if user:
                row.append("approver_users", {"user": user})


@frappe.whitelist(allow_guest=False)
def upsert_approval_config():
    if not _is_finance():
        return error_response("Bạn không có quyền cấu hình luồng duyệt")
    data = _get_request_data()
    name = data.get("name")
    if not name and not data.get("title"):
        return validation_error_response("Thiếu title", {"title": ["Bắt buộc"]})
    try:
        if name and frappe.db.exists(CONFIG_DT, name):
            doc = frappe.get_doc(CONFIG_DT, name)
        else:
            doc = frappe.new_doc(CONFIG_DT)

        for f in ("title", "campus_id", "school_year_id"):
            if f in data:
                setattr(doc, f, data.get(f))
        if "is_active" in data:
            doc.is_active = 1 if data.get("is_active") in (1, "1", True, "true") else 0

        if "plan_steps" in data:
            _apply_steps(doc, "plan_steps", _parse(data.get("plan_steps")))
        if "adjustment_steps" in data:
            _apply_steps(doc, "adjustment_steps", _parse(data.get("adjustment_steps")))

        doc.save(ignore_permissions=True)
        frappe.db.commit()
        return single_item_response(_config_to_dict(doc), message="Lưu cấu hình thành công")
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(frappe.get_traceback(), "Upsert Budget Approval Config Error")
        return error_response(f"Lỗi khi lưu cấu hình: {str(e)}")


@frappe.whitelist(allow_guest=False)
def delete_approval_config():
    if not _is_finance():
        return error_response("Bạn không có quyền xóa cấu hình")
    data = _get_request_data()
    name = data.get("name")
    if not name or not frappe.db.exists(CONFIG_DT, name):
        return not_found_response(f"Không tìm thấy cấu hình: {name}")
    used = frappe.db.exists("SIS Budget Period", {"approval_config": name})
    if used:
        return error_response("Không thể xóa: cấu hình đang được kì ngân sách sử dụng")
    try:
        frappe.delete_doc(CONFIG_DT, name, ignore_permissions=True)
        frappe.db.commit()
        return success_response(message="Xóa cấu hình thành công")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Lỗi khi xóa: {str(e)}")
