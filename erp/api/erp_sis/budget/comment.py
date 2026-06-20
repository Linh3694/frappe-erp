"""
Budget Plan Comment APIs — bình luận theo từng khoản mục (budget_code) trong 1 plan.

Ai XEM được plan (_can_read_plan: leader/member phòng + leader nhóm trực thuộc,
Phòng TC, CFO/COO/CEO) thì XEM + THÊM bình luận được. Bình luận lưu riêng theo
(plan, budget_code) nên KHÔNG mất khi sửa/lưu lại các dòng plan.
"""

import frappe

from erp.utils.api_response import (
    list_response,
    single_item_response,
    error_response,
    not_found_response,
    forbidden_response,
    validation_error_response,
)

from .utils import (
    PLAN_DT,
    _get_request_data,
    _session_email,
    _can_read_plan,
)

COMMENT_DT = "ERP Budget Plan Comment"


def _comment_to_dict(c):
    return {
        "name": c.get("name"),
        "plan": c.get("plan"),
        "budget_code": c.get("budget_code"),
        "content": c.get("content"),
        "user_email": c.get("user_email"),
        "user_fullname": c.get("user_fullname"),
        "user_avatar": c.get("user_avatar"),
        "creation": str(c.get("creation")) if c.get("creation") else None,
    }


def _require_readable_plan(plan):
    """Trả về (doc, error_response|None)."""
    if not plan or not frappe.db.exists(PLAN_DT, plan):
        return None, not_found_response(f"Không tìm thấy ngân sách: {plan}")
    doc = frappe.get_doc(PLAN_DT, plan)
    if not _can_read_plan(doc):
        return None, forbidden_response("Bạn không có quyền xem ngân sách này")
    return doc, None


@frappe.whitelist(allow_guest=False)
def list_plan_comments(plan=None, budget_code=None):
    """Danh sách bình luận của 1 plan (lọc theo budget_code nếu có), cũ -> mới."""
    data = _get_request_data()
    plan = plan or data.get("plan")
    budget_code = budget_code or data.get("budget_code")

    _doc, err = _require_readable_plan(plan)
    if err:
        return err

    filters = {"plan": plan}
    if budget_code:
        filters["budget_code"] = budget_code
    rows = frappe.get_all(
        COMMENT_DT,
        filters=filters,
        fields=[
            "name",
            "plan",
            "budget_code",
            "content",
            "user_email",
            "user_fullname",
            "user_avatar",
            "creation",
        ],
        order_by="creation asc",
    )
    for r in rows:
        r["creation"] = str(r["creation"]) if r.get("creation") else None
    return list_response(rows)


@frappe.whitelist(allow_guest=False)
def get_plan_comment_counts(plan=None):
    """Số bình luận theo từng budget_code của 1 plan -> { budget_code: count }."""
    data = _get_request_data()
    plan = plan or data.get("plan")

    _doc, err = _require_readable_plan(plan)
    if err:
        return err

    rows = frappe.db.sql(
        """
        SELECT budget_code, COUNT(*) AS cnt
        FROM `tabERP Budget Plan Comment`
        WHERE plan = %(plan)s
        GROUP BY budget_code
        """,
        {"plan": plan},
        as_dict=True,
    )
    return single_item_response({r["budget_code"]: r["cnt"] for r in rows})


@frappe.whitelist(allow_guest=False)
def add_plan_comment():
    """Thêm 1 bình luận cho 1 khoản mục (budget_code) trong plan."""
    data = _get_request_data()
    plan = data.get("plan")
    budget_code = data.get("budget_code")
    content = (data.get("content") or "").strip()
    email = _session_email()

    doc, err = _require_readable_plan(plan)
    if err:
        return err
    if not budget_code:
        return validation_error_response("Thiếu khoản mục", {"budget_code": ["Bắt buộc"]})
    if not content:
        return validation_error_response("Nội dung trống", {"content": ["Bắt buộc"]})

    try:
        ufn = frappe.db.get_value("User", email, "full_name") or email
        uav = frappe.db.get_value("User", email, "user_image") or ""
        c = frappe.get_doc(
            {
                "doctype": COMMENT_DT,
                "plan": plan,
                "budget_code": budget_code,
                "content": content,
                "user_email": email,
                "user_fullname": ufn,
                "user_avatar": uav,
            }
        )
        c.insert(ignore_permissions=True)
        frappe.db.commit()
        return single_item_response(_comment_to_dict(c.as_dict()), message="Đã thêm bình luận")
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(frappe.get_traceback(), "Add Budget Plan Comment Error")
        return error_response(f"Lỗi khi thêm bình luận: {str(e)}")
