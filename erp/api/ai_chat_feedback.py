# Copyright (c) 2026, Wellspring International School and contributors
# For license information, please see license.txt

"""
API phản hồi Like/Dislike cho LIAVI (AI Assistant).
Doctype: SIS AI Chat Feedback
"""

import json

import frappe
from frappe import _
from frappe.utils import get_table_name

from erp.utils.api_response import (
    error_response,
    success_response,
    validation_error_response,
)

DOCTYPE = "SIS AI Chat Feedback"

AGENT_TYPES = ("WISers", "Receptionist", "Parent")
FEEDBACK_TYPES = ("Like", "Dislike")

DISLIKE_REASONS = (
    "Đúng kiến thức",
    "Đúng kiến thức/ Cách trình bày chưa hợp lý",
    "Sai kiến thức",
    "Thiếu kiến thức",
    "Chưa có kiến thức",
    "Dữ liệu sai",
)


def _check_admin_permission():
    """Chỉ staff IT / quản trị xem tổng hợp."""
    user_roles = frappe.get_roles()
    allowed_roles = ("System Manager", "SIS Manager", "SIS IT")
    if not any(role in allowed_roles for role in user_roles):
        frappe.throw(_("Bạn không có quyền truy cập API này"), frappe.PermissionError)


def _get_request_data():
    """Lấy JSON body hoặc form_dict."""
    if frappe.request and getattr(frappe.request, "is_json", False) and frappe.request.json:
        return frappe.request.json
    data = {}
    try:
        if hasattr(frappe.request, "data") and frappe.request.data:
            raw = frappe.request.data
            body = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw
            if body:
                parsed = json.loads(body)
                if isinstance(parsed, dict):
                    data.update(parsed)
    except (json.JSONDecodeError, AttributeError, TypeError):
        pass
    if not data and frappe.local.form_dict:
        data = dict(frappe.local.form_dict)
    return data


def _resolve_user_identity(data):
    """Email/tên từ body hoặc session (user đã đăng nhập Frappe)."""
    email = (data.get("user_email") or "").strip()
    name = (data.get("user_name") or "").strip()
    if frappe.session.user and frappe.session.user != "Guest":
        if not email:
            email = frappe.session.user
        if not name:
            try:
                name = frappe.db.get_value("User", frappe.session.user, "full_name") or ""
            except Exception:
                name = name or ""
    return email, name


@frappe.whitelist(allow_guest=True, methods=["POST"])
def submit_feedback():
    """
    Ghi nhận Like hoặc Dislike (cho phép Guest — khách lễ tân / phụ huynh chưa có User Frappe).

    Body JSON:
    - message_id (bắt buộc)
    - agent_type: WISers | Receptionist | Parent
    - feedback_type: Like | Dislike
    - user_question, ai_answer (nên có để admin review)
    - dislike_reason, dislike_detail — bắt buộc khi Dislike (reason)
    - user_email, user_name — tùy chọn; nếu đã login sẽ lấy từ session
    """
    try:
        data = _get_request_data()

        message_id = (data.get("message_id") or "").strip()
        agent_type = (data.get("agent_type") or "").strip()
        feedback_type = (data.get("feedback_type") or "").strip()

        if not message_id:
            return validation_error_response(
                "message_id là bắt buộc", {"message_id": ["message_id là bắt buộc"]}
            )
        if agent_type not in AGENT_TYPES:
            return validation_error_response(
                "agent_type không hợp lệ",
                {"agent_type": [f"Phải là một trong: {', '.join(AGENT_TYPES)}"]},
            )
        if feedback_type not in FEEDBACK_TYPES:
            return validation_error_response(
                "feedback_type không hợp lệ",
                {"feedback_type": [f"Phải là Like hoặc Dislike"]},
            )

        dislike_reason = (data.get("dislike_reason") or "").strip() or None
        dislike_detail = (data.get("dislike_detail") or "").strip() or None
        user_question = (data.get("user_question") or "").strip() or ""
        ai_answer = (data.get("ai_answer") or "").strip() or ""

        if feedback_type == "Dislike":
            if not dislike_reason or dislike_reason not in DISLIKE_REASONS:
                return validation_error_response(
                    "dislike_reason là bắt buộc và phải thuộc danh sách cho trước",
                    {"dislike_reason": ["Chọn một lý do hợp lệ"]},
                )
        else:
            dislike_reason = None
            dislike_detail = None

        user_email, user_name = _resolve_user_identity(data)

        doc = frappe.new_doc(DOCTYPE)
        doc.message_id = message_id
        doc.agent_type = agent_type
        doc.feedback_type = feedback_type
        doc.dislike_reason = dislike_reason
        doc.dislike_detail = dislike_detail
        doc.user_question = user_question
        doc.ai_answer = ai_answer
        doc.user_email = user_email or None
        doc.user_name = user_name or None

        doc.insert(ignore_permissions=True)
        frappe.db.commit()

        return success_response(
            data={"name": doc.name},
            message="Đã ghi nhận phản hồi",
        )
    except Exception as e:
        frappe.logger().error(f"submit_feedback error: {e!s}")
        frappe.db.rollback()
        return error_response(message=f"Lỗi khi ghi nhận phản hồi: {e!s}", code="SUBMIT_ERROR")


@frappe.whitelist(allow_guest=False)
def admin_list():
    """Danh sách phản hồi AI (phân trang, lọc) — dành cho trang Review AI."""
    try:
        _check_admin_permission()

        data = _get_request_data()
        request_args = frappe.request.args or {}

        page = int(data.get("page") or request_args.get("page") or 1)
        page_length = int(data.get("page_length") or request_args.get("page_length") or 20)
        offset = (page - 1) * page_length

        filters = {}
        if data.get("agent_type") or request_args.get("agent_type"):
            filters["agent_type"] = data.get("agent_type") or request_args.get("agent_type")
        if data.get("feedback_type") or request_args.get("feedback_type"):
            filters["feedback_type"] = data.get("feedback_type") or request_args.get(
                "feedback_type"
            )

        date_from = data.get("date_from") or request_args.get("date_from")
        date_to = data.get("date_to") or request_args.get("date_to")
        if date_from and date_to:
            filters["creation"] = ["between", [date_from, date_to]]
        elif date_from:
            filters["creation"] = [">=", date_from]
        elif date_to:
            filters["creation"] = ["<=", date_to]

        search = (data.get("search") or request_args.get("search") or "").strip()
        or_filters = None
        if search:
            or_filters = [
                ["user_question", "like", f"%{search}%"],
                ["ai_answer", "like", f"%{search}%"],
                ["user_email", "like", f"%{search}%"],
                ["user_name", "like", f"%{search}%"],
                ["message_id", "like", f"%{search}%"],
            ]

        rows = frappe.get_all(
            DOCTYPE,
            filters=filters,
            or_filters=or_filters,
            fields=[
                "name",
                "message_id",
                "agent_type",
                "feedback_type",
                "dislike_reason",
                "dislike_detail",
                "user_question",
                "ai_answer",
                "user_email",
                "user_name",
                "creation",
            ],
            order_by="creation desc",
            limit=page_length,
            limit_start=offset,
        )

        if or_filters:
            total = len(
                frappe.get_all(
                    DOCTYPE,
                    filters=filters,
                    or_filters=or_filters,
                    pluck="name",
                )
            )
        else:
            total = frappe.db.count(DOCTYPE, filters=filters)

        return success_response(
            data={
                "data": rows,
                "total": total,
                "page": page,
                "page_length": page_length,
            },
            message="Lấy danh sách phản hồi AI thành công",
        )
    except frappe.PermissionError:
        raise
    except Exception as e:
        frappe.logger().error(f"admin_list ai_chat_feedback: {e!s}")
        return error_response(message=f"Lỗi khi lấy danh sách: {e!s}", code="LIST_ERROR")


@frappe.whitelist(allow_guest=False)
def admin_stats():
    """Thống kê tổng hợp Like/Dislike theo agent và lý do."""
    try:
        _check_admin_permission()

        data = _get_request_data()
        request_args = frappe.request.args or {}
        date_from = data.get("date_from") or request_args.get("date_from")
        date_to = data.get("date_to") or request_args.get("date_to")

        date_f = _date_filters_only(date_from, date_to)

        total = frappe.db.count(DOCTYPE, filters=date_f)

        like_count = frappe.db.count(
            DOCTYPE,
            filters={**date_f, "feedback_type": "Like"},
        )
        dislike_count = frappe.db.count(
            DOCTYPE,
            filters={**date_f, "feedback_type": "Dislike"},
        )

        # Nhóm theo agent — đếm từng giá trị (tránh lệ thuộc group_by của get_all)
        by_agent = {}
        for ag in AGENT_TYPES:
            n = frappe.db.count(DOCTYPE, filters={**date_f, "agent_type": ag})
            if n:
                by_agent[ag] = n

        tablename = get_table_name(DOCTYPE, wrap_in_backticks=True)

        sql_vals = []
        date_sql = ""
        if date_from:
            date_sql += " AND creation >= %s"
            sql_vals.append(date_from)
        if date_to:
            date_sql += " AND creation <= %s"
            sql_vals.append(date_to)

        by_reason = frappe.db.sql(
            f"""
            SELECT dislike_reason, COUNT(*) as cnt
            FROM {tablename}
            WHERE feedback_type = 'Dislike'
              AND IFNULL(dislike_reason, '') != ''
              {date_sql}
            GROUP BY dislike_reason
            """,
            tuple(sql_vals),
            as_dict=True,
        )

        like_rate = round((like_count / total * 100), 2) if total else 0.0

        return success_response(
            data={
                "total": total,
                "like_count": like_count,
                "dislike_count": dislike_count,
                "like_rate_percent": like_rate,
                "by_agent": by_agent,
                "by_dislike_reason": {r["dislike_reason"]: r["cnt"] for r in (by_reason or [])},
            },
            message="Thống kê phản hồi AI",
        )
    except frappe.PermissionError:
        raise
    except Exception as e:
        frappe.logger().error(f"admin_stats ai_chat_feedback: {e!s}")
        return error_response(message=f"Lỗi thống kê: {e!s}", code="STATS_ERROR")


def _date_filters_only(date_from, date_to):
    f = {}
    if date_from and date_to:
        f["creation"] = ["between", [date_from, date_to]]
    elif date_from:
        f["creation"] = [">=", date_from]
    elif date_to:
        f["creation"] = ["<=", date_to]
    return f


