# Copyright (c) 2026, Wellspring International School and contributors
# Push + email + realtime cho ticket IT Support

from __future__ import annotations

from typing import Any, Dict, Optional

import frappe
from frappe import _

from erp.api.erp_it_support.utils import (
	DOCTYPE,
	TEAM_DOCTYPE,
	_category_title,
	_session_email,
	_ticket_to_dict,
)


def _normalize_email(value: Optional[str]) -> str:
	return (value or "").strip().lower()


def _get_assignee_email(doc) -> str:
	"""Lấy email của assignee theo User name."""
	if not doc.assigned_to:
		return ""
	return _normalize_email(frappe.db.get_value("User", doc.assigned_to, "email"))


def _get_support_team_emails() -> list:
	"""Email của tất cả member IT đang active — fan-out theo legacy."""
	rows = frappe.get_all(
		TEAM_DOCTYPE,
		filters={"is_active": 1},
		fields=["email"],
	)
	emails = set()
	for r in rows:
		em = _normalize_email(r.get("email"))
		if em and "@" in em:
			emails.add(em)
	return list(emails)


def _collect_status_recipients(doc, sender_email: str = "", *, include_creator: bool = False) -> list:
	"""Recipients chuẩn cho fan-out status: assignee + IT support team, loại sender."""
	recipients = set()
	ae = _get_assignee_email(doc)
	if ae:
		recipients.add(ae)
	for em in _get_support_team_emails():
		recipients.add(em)
	if include_creator:
		ce = _normalize_email(doc.creator_email)
		if ce:
			recipients.add(ce)
	sender = _normalize_email(sender_email)
	if sender:
		recipients.discard(sender)
	return [em for em in recipients if em]


def _notification_channel() -> str:
	return str(frappe.conf.get("NOTIFICATION_STREAM_CHANNEL") or "frappe_notifications")


def _it_status_label_vn(status_key: str) -> str:
	"""Nhãn TV cho trạng thái ticket IT — không đưa khoá tiếng Anh vào câu tiếng Việt.

	`Done` ở luồng IT chưa phải kết thúc: người tạo còn phải chấp nhận kết quả mới sang
	`Closed` (xem TicketProcessingV2), nên nhãn phải nói rõ là còn chờ xác nhận.
	"""
	s = (status_key or "").strip()
	m = {
		"Open": _("Mở"),
		"Assigned": _("Đã phân công"),
		"Processing": _("Đang xử lý"),
		"In Progress": _("Đang xử lý"),
		"Waiting for Customer": _("Chờ phản hồi từ người tạo"),
		"Done": _("Hoàn thành (chờ xác nhận)"),
		"Resolved": _("Đã xử lý (chờ xác nhận)"),
		"Closed": _("Đã đóng"),
		"Cancelled": _("Đã hủy"),
	}
	return m.get(s, s) if s else ""


def _it_status_to_push_action(new_status: str) -> str:
	"""Trạng thái đích -> action push (khớp whitelist deep-link của mobile)."""
	s = (new_status or "").strip()
	m = {
		"Processing": "ticket_processing",
		"In Progress": "ticket_processing",
		"Waiting for Customer": "ticket_waiting",
		"Done": "ticket_done",
		"Resolved": "ticket_done",
		"Closed": "ticket_closed",
		"Cancelled": "ticket_cancelled",
	}
	return m.get(s) or "ticket_status_changed"


def _shorten(value: str, max_len: int = 70) -> str:
	"""Cắt tiêu đề ticket cho vừa một dòng banner push / dòng tiêu đề trong danh sách."""
	s = " ".join((value or "").split())
	return s if len(s) <= max_len else s[: max_len - 1].rstrip() + "…"


def _it_full_name(email: str) -> str:
	"""Họ tên hiển thị của một email; rỗng nếu không tra được."""
	em = _normalize_email(email)
	if not em:
		return ""
	return (frappe.db.get_value("User", {"email": em}, "full_name") or "").strip()


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
		"statusLabel": _it_status_label_vn(doc.status or ""),
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


def _notify_it_status_changed(
	doc,
	old_status: str,
	new_status: str,
	message_extras: Optional[dict] = None,
	*,
	actor_email: str = "",
):
	"""Đổi trạng thái — notify creator + assignee + support team (parity legacy fan-out).

	- Creator luôn nhận khi đổi trạng thái (creator-driven UX hiện tại).
	- Assignee + IT support team nhận thêm để theo dõi (loại actor).
	- Status final (Done/Closed/Cancelled): bật email cho cả nhóm support; ngược lại chỉ push.

	Nội dung tách hai phía: người tạo cần biết việc phải làm tiếp, đội IT cần biết ai
	vừa thao tác. Tiêu đề mang tên ticket vì đó là thứ người dùng nhận ra được — mã
	ticket một mình thì mọi dòng thông báo trông giống nhau.
	"""
	code = doc.ticket_code or doc.name
	title = _shorten((doc.title or "").strip() or code)
	new_label = _it_status_label_vn(new_status)
	action = _it_status_to_push_action(new_status)
	actor = _normalize_email(actor_email)
	actor_name = _it_full_name(actor)

	pdata = _it_ticket_payload(
		doc,
		action,
		{
			"oldStatus": old_status,
			"newStatus": new_status,
			"oldStatusLabel": _it_status_label_vn(old_status),
			"newStatusLabel": new_label,
			"actorName": actor_name,
			**(message_extras or {}),
		},
	)

	# Người tạo: nói rõ chuyện gì xảy ra và có phải làm gì tiếp không.
	if action == "ticket_processing":
		creator_title = _("Ticket IT đang được xử lý")
		creator_body = _("«{0}» đã được tiếp nhận và đang xử lý.").format(title)
	elif action == "ticket_waiting":
		creator_title = _("Ticket IT chờ phản hồi của bạn")
		creator_body = _("«{0}» cần thêm thông tin từ bạn để tiếp tục xử lý.").format(title)
	elif action == "ticket_done":
		creator_title = _("Ticket IT đã xử lý xong")
		creator_body = _("«{0}» đã xử lý xong. Vui lòng kiểm tra và xác nhận kết quả.").format(title)
	elif action == "ticket_closed":
		creator_title = _("Ticket IT đã đóng")
		creator_body = _("«{0}» đã được đóng.").format(title)
	elif action == "ticket_cancelled":
		creator_title = _("Ticket IT đã hủy")
		creator_body = _("«{0}» đã được hủy.").format(title)
	else:
		creator_title = _("Cập nhật ticket IT")
		creator_body = _("«{0}» chuyển sang trạng thái {1}.").format(title, new_label)

	# Đội IT theo dõi: nhấn vào người thao tác + trạng thái, kèm mã để tra cứu.
	team_title = f"{title} · {new_label}"
	if actor_name:
		team_body = _("{0} chuyển {1} sang {2}.").format(actor_name, f"#{code}", new_label)
	else:
		team_body = _("{0} chuyển sang {1}.").format(f"#{code}", new_label)

	creator = _normalize_email(doc.creator_email)

	if creator and creator != actor:
		_emit_it_unified(
			creator,
			creator_title,
			creator_body,
			pdata,
			notification_type="it_support_ticket_status",
		)

	# Status final → fan-out có email cho assignee + support team
	final_states = ("Done", "Closed", "Cancelled")
	include_email_for_team = new_status in final_states

	for em in _collect_status_recipients(doc, sender_email=actor):
		if em == creator:
			continue
		_emit_it_unified(
			em,
			team_title,
			team_body,
			pdata,
			notification_type="it_support_ticket_status",
			include_email=include_email_for_team,
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


def _notify_it_feedback(doc, actor_email: str = ""):
	"""Đánh giá mới — notify assignee (chính), creator (xác nhận) + IT support team theo dõi.

	Bật email cho assignee + creator để lưu hồ sơ; team chỉ push (tránh spam mailbox).
	"""
	code = doc.ticket_code or doc.name
	rating = doc.feedback_rating or 0
	body = _("Ticket {0} được đánh giá {1}/5 sao").format(f"#{code}", rating)
	payload = _it_ticket_payload(doc, "ticket_feedback", {"rating": rating})

	actor = _normalize_email(actor_email)
	notified = set()

	# Assignee — bật email để lưu hồ sơ đánh giá
	assignee_email = _get_assignee_email(doc)
	if assignee_email and assignee_email != actor:
		_emit_it_unified(
			assignee_email,
			_("Đánh giá ticket IT"),
			body,
			payload,
			notification_type="it_support_ticket_feedback",
			include_email=True,
		)
		notified.add(assignee_email)

	# Creator (người vừa đánh giá xong) → push xác nhận, không email
	creator = _normalize_email(doc.creator_email)
	if creator and creator != actor and creator not in notified:
		_emit_it_unified(
			creator,
			_("Đánh giá ticket IT"),
			_("Cảm ơn bạn đã đánh giá ticket {0}").format(f"#{code}"),
			payload,
			notification_type="it_support_ticket_feedback",
			include_email=False,
		)
		notified.add(creator)

	# IT support team — push để team thấy reputation update
	for em in _get_support_team_emails():
		if em == actor or em in notified:
			continue
		_emit_it_unified(
			em,
			_("Đánh giá ticket IT"),
			body,
			payload,
			notification_type="it_support_ticket_feedback",
			include_email=False,
		)
		notified.add(em)


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
