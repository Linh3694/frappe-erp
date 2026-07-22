"""
Budget - Thông báo qua email + trung tâm thông báo nhân viên.

Mọi hàm bọc try/except, lỗi gửi KHÔNG làm rollback nghiệp vụ.
"""

import frappe

from erp.common.notification_emit import emit_staff_notify

PLAN_DT = "ERP Budget Plan"
BUDGET_URL = "/operation/budget"


def _safe_sendmail(recipients, subject, message, *, event_type=None, plan=None):
    """Gửi email an toàn + đẩy in-app; bỏ qua nếu không có recipient hợp lệ."""
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

    # Subject đã mô tả đủ ("[Ngân sách] Đã nộp: <tên>") -> làm body, bỏ tiền tố vì
    # tiêu đề noti đã nói rõ nghiệp vụ.
    try:
        emit_staff_notify(
            recipients,
            "Ngân sách",
            str(subject or "").replace("[Ngân sách]", "").strip(),
            event_type or "budget_plan",
            {"url": BUDGET_URL, "plan_name": getattr(plan, "name", None)},
            reference_doctype=PLAN_DT if plan is not None else None,
            reference_name=getattr(plan, "name", None),
        )
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Budget In-App Notify Error")


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
    _safe_sendmail(recipients, subject, body, event_type="budget_plan_submitted", plan=plan)


def notify_plan_advanced(plan, next_step_role):
    """approve_plan (sang step kế) -> người duyệt step kế."""
    subject = f"[Ngân sách] Chờ duyệt bước kế: {plan.title or plan.name}"
    body = (
        f"Ngân sách <b>{plan.name}</b> của phòng "
        f"<b>{plan.department_name or plan.department}</b> đã qua 1 cấp duyệt, "
        f"đang chờ bạn duyệt."
    )
    _safe_sendmail(
        _users_with_role(next_step_role), subject, body,
        event_type="budget_plan_advanced", plan=plan,
    )


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
    _safe_sendmail(recipients, subject, body, event_type="budget_plan_approved", plan=plan)


def notify_plan_returned(plan, head_email, reason):
    """return_plan (về phòng ban) / unsubmit_plan -> trưởng phòng (kèm lý do)."""
    subject = f"[Ngân sách] Bị trả lại: {plan.title or plan.name}"
    body = (
        f"Ngân sách <b>{plan.name}</b> của phòng "
        f"<b>{plan.department_name or plan.department}</b> đã bị trả lại.<br>"
        f"Lý do: {reason or '(không có)'}"
    )
    _safe_sendmail(
        [head_email] if head_email else [], subject, body,
        event_type="budget_plan_returned", plan=plan,
    )


def notify_plan_returned_to_step(plan, step_role, reason):
    """return_plan trả giật về cấp duyệt thấp hơn -> người duyệt cấp đó (kèm lý do)."""
    subject = f"[Ngân sách] Trả lại để xem lại: {plan.title or plan.name}"
    body = (
        f"Ngân sách <b>{plan.name}</b> của phòng "
        f"<b>{plan.department_name or plan.department}</b> bị cấp trên trả lại để xem lại.<br>"
        f"Lý do: {reason or '(không có)'}"
    )
    _safe_sendmail(
        _users_with_role(step_role), subject, body,
        event_type="budget_plan_returned_to_step", plan=plan,
    )
