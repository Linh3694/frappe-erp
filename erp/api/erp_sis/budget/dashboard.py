"""
Budget Dashboard API - số liệu ngân sách cho Trang chủ module.

Scope theo vai trò người gọi (D6):
- Trưởng phòng (∈ leaders cấp Phòng), KHÔNG phải TC/BOD -> chỉ phòng mình.
- SIS Finance / SIS BOD / System Manager -> toàn trường + breakdown theo phòng.

Ngân sách duyệt 1 lần, không điều chỉnh -> số hiệu lực = approved_amount.
"""

import frappe

from erp.utils.api_response import single_item_response

from .utils import (
    PLAN_DT,
    _session_email,
    _is_finance,
    _is_bod,
    _user_led_unit,
    _unit_name,
)

# Trạng thái plan được tính là "đã chốt" để hiển thị số đã duyệt
_APPROVED_STATES = ["Approved", "Active", "Closed"]


def _empty_dashboard(scope, period, department=None, department_name=None):
    return {
        "scope": scope,
        "period": period,
        "department": department,
        "department_name": department_name,
        "totals": {
            "total_planned": 0,
            "total_approved": 0,
        },
        "by_code": [],
        "by_department": [],
        "plan_count": 0,
    }


@frappe.whitelist(allow_guest=False)
def get_dashboard(period=None):
    """Số liệu ngân sách Trang chủ — tự động scope theo vai trò người gọi."""
    email = _session_email()
    is_global = _is_finance() or _is_bod()

    if is_global:
        return single_item_response(_global_dashboard(period))

    unit = _user_led_unit(email)
    if not unit:
        # Không phải trưởng phòng và không phải TC/BOD -> không có số liệu
        return single_item_response(_empty_dashboard("department", period))

    return single_item_response(_department_dashboard(unit, period))


def _department_dashboard(department, period):
    data = _empty_dashboard("department", period, department, _unit_name(department))

    plan_filters = {"department": department, "is_current": 1}
    if period:
        plan_filters["period"] = period
    plan_names = frappe.get_all(
        PLAN_DT, filters=plan_filters, pluck="name", order_by="creation desc"
    )
    if not plan_names:
        return data

    data["plan_count"] = len(plan_names)

    for pn in plan_names:
        plan = frappe.get_doc(PLAN_DT, pn)
        is_approved = plan.workflow_state in _APPROVED_STATES
        for l in plan.lines:
            planned = l.planned_amount or 0
            approved = (l.approved_amount or 0) if is_approved else 0
            data["by_code"].append(
                {
                    "budget_code": l.budget_code,
                    "account_item": l.account_item,
                    "planned_amount": planned,
                    "approved_amount": approved,
                }
            )
            data["totals"]["total_planned"] += planned
            data["totals"]["total_approved"] += approved

    return data


def _global_dashboard(period):
    data = _empty_dashboard("global", period)

    plan_filters = {"is_current": 1, "workflow_state": ("in", _APPROVED_STATES)}
    if period:
        plan_filters["period"] = period
    plan_names = frappe.get_all(PLAN_DT, filters=plan_filters, pluck="name")

    data["plan_count"] = len(plan_names)
    by_dept = {}

    for pn in plan_names:
        plan = frappe.get_doc(PLAN_DT, pn)
        row = by_dept.setdefault(
            plan.department,
            {
                "department": plan.department,
                "department_name": plan.department_name,
                "total_planned": 0,
                "total_approved": 0,
            },
        )
        for l in plan.lines:
            planned = l.planned_amount or 0
            approved = l.approved_amount or 0
            row["total_planned"] += planned
            row["total_approved"] += approved
            data["totals"]["total_planned"] += planned
            data["totals"]["total_approved"] += approved

    data["by_department"] = sorted(
        by_dept.values(), key=lambda r: r["total_approved"], reverse=True
    )
    return data
