# Copyright (c) 2026, Wellspring và contributors
"""Phase 4 — phát tin qua Redis (Pub/Sub + Streams) sang notification-service.

Khi `site_config.json` bật `MOBILE_NOTIFY_VIA_REDIS_STREAM_ONLY`, Frappe route qua đây
thay vì gửi Expo trực tiếp (xem `mobile_push_notification.py`).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import frappe

from erp.common.redis_events import publish


def _notification_channel(default: str = "frappe_notifications") -> str:
    return str(frappe.conf.get("NOTIFICATION_STREAM_CHANNEL") or default)


def emit_notify(
    channel: str,
    recipients: List[str],
    title: str,
    body: str,
    data: Optional[Dict[str, Any]] = None,
    notification_type: str = "general",
) -> bool:
    """Gửi envelope chuẩn `notify.send` lên Redis (dual-write theo EVENT_BUS_MODE)."""
    emails = [
        str(e).strip().lower()
        for e in (recipients or [])
        if e and isinstance(e, str) and "@" in e
    ]
    if not emails:
        return False

    envelope: Dict[str, Any] = {
        "service": "erp",
        "event": notification_type,
        "type": notification_type,
        "kind": "notify.send",
        "deliver": True,
        "deliverFromStream": True,
        "recipients": emails,
        "title": str(title or "").strip(),
        "body": str(body or "").strip(),
        "data": data if isinstance(data, dict) else {},
        "channel": "push",
    }
    try:
        return bool(publish(channel, envelope))
    except Exception:
        frappe.logger().error("notification_emit.emit_notify failed", exc_info=True)
        return False


def emit_notify_bulk(
    channel: str,
    targets: List[Dict[str, Any]],
    title: str,
    body: str,
    notification_type: str = "general",
) -> Dict[str, Any]:
    """
    targets: [{"email": str, "data": {...}}, ...] như `send_mobile_notifications_bulk`.
    Mỗi user một publish để không trộn `data` deep link giữa người nhận.
    """
    if not targets:
        return {
            "success": False,
            "success_count": 0,
            "failed_count": 0,
            "total_messages": 0,
            "message": "No targets",
        }

    ok = 0
    fail = 0
    for t in targets:
        em = (t or {}).get("email")
        d = (t or {}).get("data") or {}
        if not em:
            fail += 1
            continue
        ntype = str((d.get("type") if isinstance(d, dict) else None) or notification_type)
        if emit_notify(channel, [em], title, body, data=d, notification_type=ntype):
            ok += 1
        else:
            fail += 1

    total = ok + fail
    return {
        "success": ok > 0,
        "success_count": ok,
        "failed_count": fail,
        "total_messages": total,
        "message": f"Redis stream: {ok} OK / {fail} fail",
    }


def emit_standard_parent_notification(
    emails: List[str],
    title: str,
    body: str,
    event_type: str,
    data: Optional[Dict[str, Any]] = None,
    channel: Optional[str] = None,
) -> bool:
    """Tiện ích gọn cho module nghiệp vụ chỉ có list email."""
    ch = channel or _notification_channel()
    return emit_notify(ch, emails, title, body, data=dict(data or {}), notification_type=event_type)


def emit_notify_hc_email(
    channel: str,
    recipient_email: str,
    title: str,
    body: str,
    administrative_email_payload: Dict[str, Any],
    notification_type: str = "administrative_ticket_email",
) -> bool:
    """
    Ticket Hành chính (Frappe): envelope chỉ kênh email — notification-service đọc
    `administrativeEmailPayload` và POST /notify-administrative-ticket (cùng tuyến tích hợp như ticket IT).
    """
    em = str(recipient_email or "").strip().lower()
    if not em or "@" not in em:
        return False
    pay = dict(administrative_email_payload or {})
    pay["recipientEmail"] = em
    envelope: Dict[str, Any] = {
        "service": "erp",
        "event": notification_type,
        "type": notification_type,
        "kind": "notify.send",
        "deliver": True,
        "deliverFromStream": True,
        "recipients": [em],
        "title": str(title or "").strip(),
        "body": str(body or "").strip(),
        "channel": "email",
        "channels": ["email"],
        "data": {
            "ticket_kind": "administrative",
            "administrativeEmailPayload": pay,
            "type": "administrative_ticket_email",
        },
    }
    try:
        return bool(publish(channel, envelope))
    except Exception:
        frappe.logger().error("notification_emit.emit_notify_hc_email failed", exc_info=True)
        return False


def emit_notify_hc_unified(
    channel: str,
    recipient_email: str,
    title: str,
    body: str,
    push_data: Dict[str, Any],
    administrative_email_payload: Optional[Dict[str, Any]] = None,
    notification_type: str = "administrative_ticket",
    *,
    reference_doctype: Optional[str] = None,
    reference_name: Optional[str] = None,
) -> bool:
    """
    Ticket HC: một envelope push (+ email tùy chọn) → notification-service (giống luồng ticket IT).
    """
    em = str(recipient_email or "").strip().lower()
    if not em or "@" not in em:
        return False
    pdata = dict(push_data or {})
    chans = ["push", "email"] if administrative_email_payload else ["push"]
    data: Dict[str, Any] = {**pdata, "ticket_kind": "administrative"}
    if administrative_email_payload:
        pay = dict(administrative_email_payload)
        pay["recipientEmail"] = em
        data["administrativeEmailPayload"] = pay
    envelope: Dict[str, Any] = {
        "service": "erp",
        "event": notification_type,
        "type": notification_type,
        "kind": "notify.send",
        "deliver": True,
        "deliverFromStream": True,
        "recipients": [em],
        "title": str(title or "").strip(),
        "body": str(body or "").strip(),
        "channel": "push",
        "channels": chans,
        "data": data,
    }
    if reference_doctype:
        envelope["reference_doctype"] = reference_doctype
    if reference_name:
        envelope["reference_name"] = reference_name
    try:
        return bool(publish(channel, envelope))
    except Exception:
        frappe.logger().error("notification_emit.emit_notify_hc_unified failed", exc_info=True)
        return False
