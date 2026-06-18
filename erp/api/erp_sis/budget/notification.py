"""
Budget - Thông báo qua email (D8: email trước, chưa làm push/realtime/mobile).

Mọi hàm bọc try/except, lỗi gửi mail KHÔNG làm rollback nghiệp vụ.
"""

import frappe


def _safe_sendmail(recipients, subject, message):
    """Gửi email an toàn; bỏ qua nếu không có recipient hợp lệ."""
    recipients = [r for r in (recipients or []) if r and r != "Administrator"]
    if not recipients:
        return
    try:
        frappe.sendmail(
            recipients=recipients,
            subject=subject,
            message=message,
            now=False,
        )
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Budget Email Error")


def _users_with_role(role):
    """Danh sách email user có role (loại Administrator/Guest)."""
    if not role:
        return []
    rows = frappe.get_all(
        "Has Role",
        filters={"role": role, "parenttype": "User"},
        fields=["parent"],
    )
    return [
        r.parent
        for r in rows
        if r.parent not in ("Administrator", "Guest")
        and frappe.db.get_value("User", r.parent, "enabled")
    ]


def notify_plan_submitted(plan, next_step_role, head_email):
    """submit_plan -> trưởng phòng + người duyệt step hiện tại."""
    subject = f"[Ngân sách] Đã nộp: {plan.title or plan.name}"
    body = (
        f"Phòng ban <b>{plan.department_name or plan.department}</b> đã nộp ngân sách "
        f"<b>{plan.name}</b> (tổng kế hoạch: {plan.total_planned or 0:,.0f}).<br>"
        f"Vui lòng kiểm tra và duyệt."
    )
    recipients = list(_users_with_role(next_step_role))
    if head_email:
        recipients.append(head_email)
    _safe_sendmail(recipients, subject, body)


def notify_plan_advanced(plan, next_step_role):
    """approve_plan (sang step kế) -> người duyệt step kế."""
    subject = f"[Ngân sách] Chờ duyệt bước kế: {plan.title or plan.name}"
    body = (
        f"Ngân sách <b>{plan.name}</b> của phòng "
        f"<b>{plan.department_name or plan.department}</b> đã qua 1 cấp duyệt, "
        f"đang chờ bạn duyệt."
    )
    _safe_sendmail(_users_with_role(next_step_role), subject, body)


def notify_plan_approved(plan, head_email):
    """approve cuối -> trưởng phòng + TC."""
    subject = f"[Ngân sách] Đã duyệt: {plan.title or plan.name}"
    body = (
        f"Ngân sách <b>{plan.name}</b> của phòng "
        f"<b>{plan.department_name or plan.department}</b> đã được duyệt "
        f"(tổng: {plan.total_approved or 0:,.0f})."
    )
    recipients = list(_users_with_role("SIS Finance"))
    if head_email:
        recipients.append(head_email)
    _safe_sendmail(recipients, subject, body)


def notify_plan_returned(plan, head_email, reason):
    """return_plan / unsubmit_plan -> trưởng phòng (kèm lý do)."""
    subject = f"[Ngân sách] Bị trả lại: {plan.title or plan.name}"
    body = (
        f"Ngân sách <b>{plan.name}</b> của phòng "
        f"<b>{plan.department_name or plan.department}</b> đã bị trả lại.<br>"
        f"Lý do: {reason or '(không có)'}"
    )
    _safe_sendmail([head_email] if head_email else [], subject, body)


def notify_adjustment_event(adjustment, next_step_role, subject_prefix):
    """Thông báo sự kiện adjustment cho người duyệt step kế."""
    subject = f"[Ngân sách] {subject_prefix}: {adjustment.title or adjustment.name}"
    body = (
        f"Điều chỉnh <b>{adjustment.name}</b> ({adjustment.type}) "
        f"đang chờ xử lý."
    )
    _safe_sendmail(_users_with_role(next_step_role), subject, body)
