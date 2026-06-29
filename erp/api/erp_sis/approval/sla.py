"""
Quét hạn xử lý (SLA) các bước duyệt đang chờ, đánh dấu quá hạn + leo thang thông báo.
Nhân bản mẫu erp/api/crm/sla_scheduler.py. Đăng ký ở hooks.py scheduler_events.cron.
"""

import frappe
from frappe.utils import getdate, now

from . import principals

STEP_DT = "ERP Approval Step"


def _notify(parenttype, parent, label, recipients):
    title = f"Quá hạn duyệt: {label or parenttype} · {parent}"
    for email in {e for e in recipients if e}:
        try:
            frappe.get_doc(
                {
                    "doctype": "Notification Log",
                    "for_user": email,
                    "type": "Alert",
                    "subject": title,
                    "document_type": parenttype,
                    "document_name": parent,
                }
            ).insert(ignore_permissions=True)
        except Exception:
            frappe.log_error(title=f"WF SLA notify fail {email}", message=frappe.get_traceback())


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
