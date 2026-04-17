"""
Scheduler SLA CRM Issue — cap nhat sla_status + push canh bao (toi da 1 lan/ngay/issue).
"""

import frappe
from frappe.utils import getdate, now, now_datetime

from erp.api.crm.issue import (
    _approver_emails,
    _notify_crm_issue_mobile,
    _recompute_sla_state,
)


def _should_push_today(issue_name: str) -> bool:
    """True neu chua gui push SLA trong ngay (site timezone)."""
    last = frappe.db.get_value("CRM Issue", issue_name, "sla_last_notified_at")
    if not last:
        return True
    return getdate(last) != getdate(now_datetime())


def _push_sla_notification(doc, state: str) -> None:
    """Gui push toi PIC + Admin duyet; sau do ghi sla_last_notified_at (khong doi modified)."""
    recipients = []
    if getattr(doc, "pic", None):
        recipients.append(doc.pic)
    recipients.extend(_approver_emails() or [])
    seen = set()
    uniq = []
    for email in recipients:
        if email and email not in seen and email != "Guest":
            seen.add(email)
            uniq.append(email)

    if state == "Warning":
        title = "Sắp quá SLA"
        body = f"Vấn đề {doc.issue_code} sắp quá hạn — giải quyết ngay."
        notif_type = "crm_issue_sla_warning"
    else:
        title = "Bạn còn Issue chưa giải quyết xong"
        body = f"Vấn đề {doc.issue_code} đã quá hạn SLA. Giải quyết ngay."
        notif_type = "crm_issue_sla_breached"

    _notify_crm_issue_mobile(uniq, title, body, doc, notif_type)
    frappe.db.set_value(
        "CRM Issue",
        doc.name,
        {"sla_last_notified_at": now()},
        update_modified=False,
    )


@frappe.whitelist()
def check_crm_issue_sla():
    """Chay moi gio: cap nhat sla_status + push warning/breached (toi da 1 lan/ngay/issue)."""
    rows = frappe.get_all(
        "CRM Issue",
        filters={
            "approval_status": "Da duyet",
            "sla_deadline": ["is", "set"],
            "first_response_at": ["is", "not set"],
        },
        pluck="name",
    )
    for name in rows:
        doc = frappe.get_doc("CRM Issue", name)
        old = (getattr(doc, "sla_status", None) or "").strip() or "On track"
        new = _recompute_sla_state(doc)
        if new != old:
            doc.save(ignore_permissions=True)
        if new in ("Warning", "Breached") and _should_push_today(doc.name):
            _push_sla_notification(doc, new)
    frappe.db.commit()
