"""
Thông báo quy trình duyệt generic (ERP Approval Step) → hộp thư nhân viên.

Mọi hàm ở đây xếp lịch gửi SAU khi giao dịch commit (`frappe.db.after_commit`):
engine mutate doc rồi caller mới `doc.save()` + `frappe.db.commit()`, nên gửi ngay
trong lúc mutate sẽ báo nhầm nếu về sau rollback.

Lỗi gửi KHÔNG bao giờ được làm hỏng nghiệp vụ duyệt — mọi thứ bọc try/except.
"""

import frappe

from erp.common.notification_emit import emit_staff_notify

# Route web SIS theo doctype đích. Doctype chưa khai báo -> không gắn deep link
# (frontend rơi về trung tâm thông báo thay vì điều hướng sai trang).
DOC_URLS = {
    "ERP Purchase Request": "/operation/procurement",
    "ERP Purchase Order": "/operation/procurement",
}

# Nhãn tiếng Việt cho doctype đích; thiếu thì dùng luôn tên doctype.
DOC_LABELS = {
    "ERP Purchase Request": "Đề nghị mua sắm",
    "ERP Purchase Order": "Đơn mua",
}


def _doc_label(doc):
    """'Đề nghị mua sắm "Mua laptop" (ERP-PR-0001)' — đủ để nhận ra phiếu trong noti."""
    kind = DOC_LABELS.get(doc.doctype, doc.doctype)
    title = str(doc.get("title") or "").strip()
    return f'{kind} "{title}" ({doc.name})' if title else f"{kind} {doc.name}"


def _queue(emails, title, body, event_type, doc, extra=None):
    targets = sorted(
        {
            str(e).strip().lower()
            for e in (emails or [])
            if e and "@" in str(e)
        }
    )
    if not targets:
        return

    data = {
        "doc_doctype": doc.doctype,
        "doc_name": doc.name,
        "workflow_state": doc.get("workflow_state"),
    }
    url = DOC_URLS.get(doc.doctype)
    if url:
        data["url"] = url
    if extra:
        data.update(extra)

    doctype, name = doc.doctype, doc.name

    def _send():
        try:
            emit_staff_notify(
                targets,
                title,
                body,
                event_type,
                data,
                reference_doctype=doctype,
                reference_name=name,
            )
        except Exception:
            frappe.log_error(
                title="approval.notify send fail",
                message=f"{doctype} {name} event={event_type}",
            )

    try:
        frappe.db.after_commit.add(_send)
    except Exception:
        # Frappe không có after_commit (test/context lạ) -> gửi thẳng, thà thừa còn hơn im.
        _send()


def step_activated(doc, step):
    """Bước chuyển Waiting -> Pending: báo người duyệt của bước đó."""
    try:
        from . import principals

        emails = principals.assignee_emails(step)
        step_label = str(step.get("label") or "").strip()
        body = f"{_doc_label(doc)} đang chờ bạn duyệt"
        body = f"{body} ở bước {step_label}." if step_label else f"{body}."
        _queue(
            emails,
            "Phiếu chờ bạn duyệt",
            body,
            "approval_step_pending",
            doc,
            {"node_id": step.get("node_id"), "step_label": step_label},
        )
    except Exception:
        frappe.log_error(title="approval.notify.step_activated", message=frappe.get_traceback())


def decided(doc, state, reason=None):
    """Phiếu chốt trạng thái (Approved / Rejected / Returned): báo người nộp."""
    try:
        titles = {
            "Approved": "Phiếu đã được duyệt",
            "Rejected": "Phiếu bị từ chối",
            "Returned": "Phiếu bị trả lại",
        }
        verbs = {
            "Approved": "đã được duyệt",
            "Rejected": "đã bị từ chối",
            "Returned": "đã bị trả lại để chỉnh sửa",
        }
        if state not in titles:
            return
        body = f"{_doc_label(doc)} {verbs[state]}"
        reason = str(reason or "").strip()
        body = f"{body}. Lý do: {reason}" if reason else f"{body}."
        _queue(
            [doc.get("submitted_by")],
            titles[state],
            body,
            f"approval_{state.lower()}",
            doc,
            {"reason": reason} if reason else None,
        )
    except Exception:
        frappe.log_error(title="approval.notify.decided", message=frappe.get_traceback())
