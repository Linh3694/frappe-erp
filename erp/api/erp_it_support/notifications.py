# Copyright (c) 2026, Wellspring International School and contributors
# Push + email + realtime cho ticket IT Support

from __future__ import annotations

from typing import Any, Dict, Optional

import frappe
from frappe import _

from erp.api.erp_it_support.utils import (
	DOCTYPE,
	_category_title,
	_session_email,
	_ticket_to_dict,
)


def _notification_channel() -> str:
	return str(frappe.conf.get("NOTIFICATION_STREAM_CHANNEL") or "frappe_notifications")


def _it_ticket_payload(doc, event_type: str, extra: Optional[dict] = None) -> dict:
	code = doc.ticket_code or doc.name
	data = {
		"type": event_type,
		"ticket_kind": "it",
		"ticketId": doc.name,
		"ticket_id": doc.name,
		"ticketCode": code,
		"ticket_code": code,
		"status": doc.status,
		"title": doc.title or "",
		"category": _category_title(doc),
	}
	if extra:
		data.update(extra)
	return data


def _emit_it_unified(
	recipient_email: str,
	title: str,
	body: str,
	push_data: dict,
	*,
	notification_type: str = "it_support_ticket",
	include_email: bool = True,
	reference_name: Optional[str] = None,
):
	"""Một envelope push (+ email notify-ticket-* qua notification-service)."""
	from erp.common.notification_emit import publish

	em = (recipient_email or "").strip().lower()
	if not em or "@" not in em:
		return False
	chans = ["push", "email"] if include_email else ["push"]
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
		"data": push_data,
		"reference_doctype": DOCTYPE,
		"reference_name": reference_name or push_data.get("ticketId"),
	}
	try:
		return bool(publish(_notification_channel(), envelope))
	except Exception:
		frappe.logger().error("it_support notifications publish failed", exc_info=True)
		return False


def _it_send_emails_on_ticket_create(doc):
	"""Thông báo ticket mới — creator + assignee."""
	code = doc.ticket_code or doc.name
	title = (doc.title or "").strip() or code
	cat = _category_title(doc)
	body = _("{0} · {1}: {2}").format(f"#{code}", cat, title) if cat else _("{0}: {1}").format(f"#{code}", title)

	creator = (doc.creator_email or "").strip()
	if creator:
		_emit_it_unified(
			creator,
			_("Ticket IT đã gửi"),
			_("{0}: {1}. Đội IT sẽ phản hồi sớm.").format(f"#{code}", title),
			_it_ticket_payload(doc, "ticket_creation_confirmation"),
			notification_type="it_support_ticket_created",
			include_email=True,
		)

	if doc.assigned_to:
		assignee_email = frappe.db.get_value("User", doc.assigned_to, "email")
		if assignee_email and assignee_email.lower() != (creator or "").lower():
			_emit_it_unified(
				assignee_email,
				_("Ticket IT mới"),
				body,
				_it_ticket_payload(doc, "new_ticket"),
				notification_type="it_support_ticket_new",
			)


def _notify_it_status_changed(doc, old_status: str, new_status: str, message_extras: Optional[dict] = None):
	"""Đổi trạng thái — notify creator."""
	creator = (doc.creator_email or "").strip()
	if not creator:
		return
	code = doc.ticket_code or doc.name
	title = (doc.title or "").strip() or code
	body = _("Ticket {0} chuyển sang «{1}»").format(f"#{code}", new_status)
	pdata = _it_ticket_payload(
		doc,
		"ticket_status_changed",
		{"oldStatus": old_status, "newStatus": new_status, **(message_extras or {})},
	)
	_emit_it_unified(
		creator,
		_("Cập nhật ticket IT"),
		body,
		pdata,
		notification_type="it_support_ticket_status",
	)


def _notify_it_assignment_changed(doc, assignee_user: str):
	assignee_email = frappe.db.get_value("User", assignee_user, "email")
	if not assignee_email:
		return
	code = doc.ticket_code or doc.name
	_emit_it_unified(
		assignee_email,
		_("Ticket IT được phân công"),
		_("Bạn được giao ticket {0}: {1}").format(f"#{code}", doc.title or ""),
		_it_ticket_payload(doc, "ticket_assigned"),
		notification_type="it_support_ticket_assigned",
	)


def _notify_it_ticket_pickup(doc):
	"""Nhân viên nhận ticket."""
	creator = (doc.creator_email or "").strip()
	if not creator:
		return
	code = doc.ticket_code or doc.name
	assignee_name = doc.assigned_to_fullname or doc.assigned_to or ""
	_emit_it_unified(
		creator,
		_("Ticket IT đang được xử lý"),
		_("{0} đã tiếp nhận ticket {1}").format(assignee_name, f"#{code}"),
		_it_ticket_payload(doc, "ticket_pickup"),
		notification_type="it_support_ticket_pickup",
	)


def _notify_it_user_reply(doc, sender_email: str, message_snippet: str = ""):
	"""Trao đổi mới — notify phía còn lại."""
	creator = (doc.creator_email or "").strip().lower()
	sender = (sender_email or "").strip().lower()
	assignee_email = ""
	if doc.assigned_to:
		assignee_email = (frappe.db.get_value("User", doc.assigned_to, "email") or "").strip().lower()

	recipients = []
	if sender == creator and assignee_email:
		recipients.append(assignee_email)
	elif sender == assignee_email and creator:
		recipients.append(creator)
	elif _is_staff_sender(sender):
		if creator and creator != sender:
			recipients.append(creator)
	else:
		if assignee_email and assignee_email != sender:
			recipients.append(assignee_email)

	code = doc.ticket_code or doc.name
	body = message_snippet or _("Có tin nhắn mới")
	for em in recipients:
		_emit_it_unified(
			em,
			_("Trao đổi ticket {0}").format(f"#{code}"),
			body,
			_it_ticket_payload(doc, "ticket_user_reply", {"messageSnippet": message_snippet}),
			notification_type="it_support_ticket_reply",
		)


def _is_staff_sender(email: str) -> bool:
	if not email:
		return False
	user = frappe.db.get_value("User", {"email": email}, "name")
	if not user:
		return False
	roles = frappe.get_roles(user) or []
	return any(r in roles for r in ("System Manager", "SIS IT", "SIS BOD"))


def _notify_it_feedback(doc):
	"""Đánh giá mới — notify assignee."""
	if not doc.assigned_to:
		return
	assignee_email = frappe.db.get_value("User", doc.assigned_to, "email")
	if not assignee_email:
		return
	code = doc.ticket_code or doc.name
	rating = doc.feedback_rating or 0
	_emit_it_unified(
		assignee_email,
		_("Đánh giá ticket IT"),
		_("Ticket {0} được đánh giá {1}/5 sao").format(f"#{code}", rating),
		_it_ticket_payload(doc, "ticket_feedback", {"rating": rating}),
		notification_type="it_support_ticket_feedback",
		include_email=False,
	)


def _emit_it_new_message_realtime(doc, message_data: dict, sender_email: str):
	"""Socket cho FE — room ticket."""
	try:
		frappe.publish_realtime(
			"it_support_ticket_new_message",
			{
				"ticketId": doc.name,
				"ticketCode": doc.ticket_code or doc.name,
				"message": message_data,
				"senderEmail": sender_email,
				"status": doc.status,
			},
			after_commit=True,
		)
	except Exception:
		frappe.logger().error("it_support realtime publish failed", exc_info=True)


def _notify_it_user_reply_job(ticket_id: str, sender_email: str, message_snippet: str = ""):
	doc = frappe.get_doc(DOCTYPE, ticket_id)
	_notify_it_user_reply(doc, sender_email, message_snippet)
