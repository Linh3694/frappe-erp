"""
Budget Dashboard API - số liệu ngân sách cho Trang chủ module.

Scope theo vai trò người gọi (D6):
- Trưởng phòng (∈ leaders cấp Phòng), KHÔNG phải TC/BOD -> chỉ phòng mình.
- SIS Finance / SIS BOD / System Manager -> toàn trường + breakdown theo phòng.

Ngân sách hiệu lực = approved_amount (bản is_current đã duyệt) + Σ delta_amount (adjustment Approved).
"""

import frappe

from erp.utils.api_response import single_item_response

from .utils import (
    PLAN_DT,
    ADJUSTMENT_DT,
    _session_email,
    _is_finance,
    _is_bod,
    _user_led_unit,
    _unit_name,
)

# Trạng thái plan được tính là "đã chốt" để hiển thị số đã duyệt/hiệu lực
_APPROVED_STATES = ["Approved", "Active", "Closed"]


def _delta_map(period=None):
    """Map (plan, budget_code) -> Σ delta_amount của các adjustment Approved."""
    filters = {"workflow_state": "Approved"}
    if period:
        filters["period"] = period
    result = {}
    for an in frappe.get_all(ADJUSTMENT_DT, filters=filters, pluck="name"):
        adj = frappe.get_doc(ADJUSTMENT_DT, an)
        for l in adj.lines:
            key = (l.plan, l.budget_code)
            result[key] = result.get(key, 0) + (l.delta_amount or 0)
    return result


def _empty_dashboard(scope, period, department=None, department_name=None):
    return {
        "scope": scope,
        "period": period,
        "department": department,
        "department_name": department_name,
        "totals": {
            "total_planned": 0,
            "total_approved": 0,
            "total_delta": 0,
            "total_effective": 0,
        },
        "by_code": [],
        "by_department": [],
        "plan_count": 0,
        "adjustment_count": 0,
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

    deltas = _delta_map(period)
    data["plan_count"] = len(plan_names)
    seen_adj_keys = set()

    for pn in plan_names:
        plan = frappe.get_doc(PLAN_DT, pn)
        is_approved = plan.workflow_state in _APPROVED_STATES
        for l in plan.lines:
            planned = l.planned_amount or 0
            approved = (l.approved_amount or 0) if is_approved else 0
            delta = deltas.get((pn, l.budget_code), 0) if is_approved else 0
            if delta:
                seen_adj_keys.add((pn, l.budget_code))
            effective = approved + delta
            data["by_code"].append(
                {
                    "budget_code": l.budget_code,
                    "account_item": l.account_item,
                    "planned_amount": planned,
                    "approved_amount": approved,
                    "delta_total": delta,
                    "effective_amount": effective,
                }
            )
            data["totals"]["total_planned"] += planned
            data["totals"]["total_approved"] += approved
            data["totals"]["total_delta"] += delta
            data["totals"]["total_effective"] += effective

    data["adjustment_count"] = len(seen_adj_keys)
    return data


def _global_dashboard(period):
    data = _empty_dashboard("global", period)

    plan_filters = {"is_current": 1, "workflow_state": ("in", _APPROVED_STATES)}
    if period:
        plan_filters["period"] = period
    plan_names = frappe.get_all(PLAN_DT, filters=plan_filters, pluck="name")

    deltas = _delta_map(period)
    data["plan_count"] = len(plan_names)
    by_dept = {}
    adj_keys = set()

    for pn in plan_names:
        plan = frappe.get_doc(PLAN_DT, pn)
        row = by_dept.setdefault(
            plan.department,
            {
                "department": plan.department,
                "department_name": plan.department_name,
                "total_planned": 0,
                "total_approved": 0,
                "total_delta": 0,
                "total_effective": 0,
            },
        )
        for l in plan.lines:
            planned = l.planned_amount or 0
            approved = l.approved_amount or 0
            delta = deltas.get((pn, l.budget_code), 0)
            if delta:
                adj_keys.add((pn, l.budget_code))
            effective = approved + delta
            row["total_planned"] += planned
            row["total_approved"] += approved
            row["total_delta"] += delta
            row["total_effective"] += effective
            data["totals"]["total_planned"] += planned
            data["totals"]["total_approved"] += approved
            data["totals"]["total_delta"] += delta
            data["totals"]["total_effective"] += effective

    data["by_department"] = sorted(
        by_dept.values(), key=lambda r: r["total_effective"], reverse=True
    )
    data["adjustment_count"] = len(adj_keys)
    return data
