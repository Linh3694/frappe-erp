"""
Quét hạn xử lý (SLA) các bước duyệt đang chờ, đánh dấu quá hạn + leo thang thông báo.
Nhân bản mẫu erp/api/crm/sla_scheduler.py. Đăng ký ở hooks.py scheduler_events.cron.
"""

import frappe
from frappe.utils import getdate, now

from erp.common.notification_emit import emit_staff_notify

from . import notify as wf_notify
from . import principals

STEP_DT = "ERP Approval Step"


def _notify(parenttype, parent, label, recipients):
    step_label = str(label or "").strip()
    data = {"doc_doctype": parenttype, "doc_name": parent, "step_label": step_label}
    url = wf_notify.DOC_URLS.get(parenttype)
    if url:
        data["url"] = url
    body = f"{wf_notify.DOC_LABELS.get(parenttype, parenttype)} {parent} đã quá hạn duyệt"
    body = f"{body} ở bước {step_label}." if step_label else f"{body}."
    try:
        emit_staff_notify(
            list(recipients or []),
            "Quá hạn duyệt",
            body,
            "approval_overdue",
            data,
            reference_doctype=parenttype,
            reference_name=parent,
        )
    except Exception:
        frappe.log_error(title="WF SLA notify fail", message=frappe.get_traceback())


def check_workflow_deadlines():
    """Job định kỳ: bước Pending quá deadline_at -> overdue + thông báo (debounce 1 lần/ngày)."""
    rows = frappe.db.sql(
        """
        SELECT name, parent, parenttype, label, scope_unit, escalation,
               assignee_principal_type, approver_role, approver_user, assignee_position, last_escalated_at
        FROM `tabERP Approval Step`
        WHERE is_active = 1 AND status = 'Pending'
          AND deadline_at IS NOT NULL AND deadline_at < %(now)s
        """,
        {"now": now()},
        as_dict=True,
    )
    today = getdate()
    for r in rows:
        try:
            mode = r.get("escalation") or "notify"
            already = r.get("last_escalated_at") and getdate(r.get("last_escalated_at")) == today
            if mode != "none" and not already:
                recipients = set(principals.assignee_emails(r))
                if mode == "escalate_up":
                    recipients |= set(principals.parent_unit_leader(r.get("scope_unit")))
                _notify(r.parenttype, r.parent, r.get("label"), recipients)
            frappe.db.set_value(
                STEP_DT, r.name, {"overdue": 1, "last_escalated_at": now()}, update_modified=False
            )
        except Exception:
            frappe.log_error(title="WF SLA step fail", message=frappe.get_traceback())
    frappe.db.commit()
