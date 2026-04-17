"""
Scheduler SLA CRM Issue — cap nhat sla_status + push canh bao (toi da 1 lan/ngay/issue).
"""

from typing import Optional

import frappe
from frappe.utils import getdate, now, nowdate

from erp.api.crm.issue import (
    _approver_emails,
    _compute_sla_status_from_values,
    _notify_crm_issue_mobile,
)


def _enabled_emails(emails):
    """Loc email user con hoat dong (enabled)."""
    if not emails:
        return []
    uniq = list({e for e in emails if e and e != "Guest"})
    if not uniq:
        return []
    return frappe.get_all("User", filters={"name": ["in", uniq], "enabled": 1}, pluck="name") or []


def _should_push_today(issue_name: str) -> bool:
    """True neu chua gui push SLA trong ngay (timezone site — dong bo nowdate)."""
    last = frappe.db.get_value("CRM Issue", issue_name, "sla_last_notified_at")
    if not last:
        return True
    return getdate(last) != getdate(nowdate())


def _push_sla_notification(issue_name: str, issue_code: str, pic: Optional[str], state: str) -> None:
    """Gui push toi PIC + Admin duyet; sau do ghi sla_last_notified_at (khong doi modified)."""
    recipients = []
    if pic:
        recipients.append(pic)
    recipients.extend(_approver_emails() or [])
    uniq = []
    seen = set()
    for email in _enabled_emails(recipients):
        if email and email not in seen:
            seen.add(email)
            uniq.append(email)

    code = (issue_code or issue_name or "").strip()
    if state == "Warning":
        title = f"[{code}] Sắp quá SLA"
        body = f"Vấn đề {code} sắp quá hạn — giải quyết ngay."
        notif_type = "crm_issue_sla_warning"
    else:
        title = f"[{code}] Đã quá SLA"
        body = f"Vấn đề {code} đã quá hạn SLA. Giải quyết ngay."
        notif_type = "crm_issue_sla_breached"

    class _IssueStub:
        __slots__ = ("name", "issue_code")

        def __init__(self, n, c):
            self.name = n
            self.issue_code = c

    stub = _IssueStub(issue_name, issue_code or "")

    _notify_crm_issue_mobile(uniq, title, body, stub, notif_type)
    frappe.db.set_value(
        "CRM Issue",
        issue_name,
        {"sla_last_notified_at": now()},
        update_modified=False,
    )


@frappe.whitelist()
def check_crm_issue_sla():
    """Chay dinh ky: cap nhat sla_status (set_value, khong touch modified) + push warning/breached."""
    rows = frappe.get_all(
        "CRM Issue",
        filters={
            "approval_status": "Da duyet",
            "sla_deadline": ["is", "set"],
            "first_response_at": ["is", "not set"],
        },
        fields=[
            "name",
            "sla_status",
            "sla_deadline",
            "sla_started_at",
            "first_response_at",
            "issue_code",
            "pic",
        ],
    )
    for row in rows:
        old = (row.get("sla_status") or "").strip() or "On track"
        new = _compute_sla_status_from_values(
            row.get("sla_started_at"),
            row.get("sla_deadline"),
            row.get("first_response_at"),
        )
        if new != old:
            frappe.db.set_value(
                "CRM Issue",
                row.name,
                {"sla_status": new},
                update_modified=False,
            )
        if new in ("Warning", "Breached") and _should_push_today(row.name):
            _push_sla_notification(
                row.name,
                row.get("issue_code") or "",
                row.get("pic"),
                new,
            )
    frappe.db.commit()
