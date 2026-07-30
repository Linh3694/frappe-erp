# Copyright (c) 2026, Wellspring International School and contributors
"""
Wave 3: Push + ERP Notification cho chat Trao đổi (social-service → Frappe).
Nhận webhook từ social-service, enqueue RQ short, debounce Expo theo (conversation, recipient).

Ba đích đến, đừng bỏ sót cái nào khi thêm loại sự kiện mới:
  1. ERP Notification (MariaDB) — parent-portal WEB đọc.
  2. Realtime socket Frappe — badge + toast khi app đang mở.
  3. Hộp thư notification-service (Postgres) — parent-portal-mobile và workspace-mobile đọc
     màn Thông báo từ đây kể từ Phase 3. Xem `_mirror_to_notification_service`.
"""

import json

import frappe
from frappe import _

from erp.api.parent_portal.realtime_notification import (
	emit_notification_to_user,
	emit_unread_count_update,
)
from erp.common.doctype.erp_notification.erp_notification import create_notification, get_unread_count
from erp.common.notification_emit import (
	emit_inbox_mirror_bulk,
	push_delivered_by_notification_service,
)
from erp.api.erp_sis.mobile_push_notification import send_mobile_notifications_bulk
from erp.utils.bilingual_notification import bi


# Debounce giữa các lần Expo push cho cùng hội thoại + người nhận (tránh spam khi chat liên tục)
CHAT_TITLE = bi("Trao đổi", "Chat")
POLL_TITLE = bi("Bình chọn", "Poll")
RECALL_TITLE = bi("Tin nhắn đã thu hồi", "Message recalled")
ATTACHMENT_PREVIEW = bi("[Tệp đính kèm]", "[Attachment]")
NEW_MESSAGE_BODY = bi("Tin nhắn mới", "New message")
SOMEONE = bi("Ai đó", "Someone")
DEFAULT_SENDER = bi("Trao đổi", "Chat")

# Debounce giữa các lần Expo push cho cùng hội thoại + người nhận (tránh spam khi chat liên tục)
CHAT_EXPO_DEBOUNCE_SECONDS = 5


def _preview_bilingual(preview_raw, has_attachment=False):
	"""Chuẩn hoá preview tin nhắn — nội dung người gửi giữ nguyên, placeholder có bản EN."""
	if preview_raw:
		text = preview_raw[:200]
		return bi(text, text)
	if has_attachment:
		return ATTACHMENT_PREVIEW
	return NEW_MESSAGE_BODY


def _reaction_body(sender_name):
	name = (sender_name or "").strip() or SOMEONE["vi"]
	name_en = (sender_name or "").strip() or SOMEONE["en"]
	return bi(
		_("%(name)s đã thả cảm xúc tin nhắn") % {"name": name},
		f"{name_en} reacted to a message",
	)


def _debounce_cache_key(conversation_id, recipient_email):
	return f"chat_noti_debounce:{conversation_id}:{recipient_email}"


def _should_skip_expo_push(conversation_id, recipient_email):
	"""Trả True nếu vừa mới gửi Expo cho cặp (conversation, recipient) trong CHAT_EXPO_DEBOUNCE_SECONDS."""
	try:
		return bool(frappe.cache().get_value(_debounce_cache_key(conversation_id, recipient_email)))
	except Exception:
		return False


def _set_expo_debounce(conversation_id, recipient_email):
	try:
		frappe.cache().set_value(
			_debounce_cache_key(conversation_id, recipient_email),
			"1",
			expires_in_sec=CHAT_EXPO_DEBOUNCE_SECONDS,
		)
	except Exception as e:
		frappe.logger().warning(f"💬 [Exchange] Debounce set failed: {e}")


def _mirror_to_notification_service(targets, title, body, notif_type, log_tag):
	"""Ghi hộp thư notification-service cho những người push KHÔNG đi qua service đó.

	Từ Phase 3 app đọc màn Thông báo ở notification-service, không đọc ERP Notification nữa.
	Debounce chỉ được phép chặn PUSH — mọi tin nhắn vẫn phải có bản ghi trong hộp thư,
	nếu không danh sách thông báo sẽ trống dù push vẫn về máy.
	"""
	if not targets:
		return
	try:
		ok = emit_inbox_mirror_bulk(targets, title, body, notification_type=notif_type)
		frappe.logger().info(f"📥 [Exchange] {log_tag} inbox mirror: {ok}/{len(targets)}")
	except Exception as me:
		frappe.logger().error(f"❌ [Exchange] {log_tag} inbox mirror failed: {me}")


@frappe.whitelist(allow_guest=True, methods=["POST"])
def handle_chat_event():
	"""
	Wave 3: Webhook từ social-service cho chat 1-1 / nhóm lớp.
	POST /api/method/erp.api.notification.exchange.handle_chat_event
	"""
	try:
		service_name = frappe.get_request_header("X-Service-Name", "")
		request_source = frappe.get_request_header("X-Request-Source", "")

		if service_name == "social-service" and request_source == "service-to-service":
			frappe.logger().info("💬 [Exchange Event] Valid service-to-service from social-service")
		else:
			frappe.logger().warning(
				f"💬 [Exchange Event] Unknown source service={service_name} source={request_source}"
			)

		if frappe.request.method != "POST":
			frappe.throw(_("Method not allowed"), frappe.PermissionError)

		data = frappe.form_dict
		if not data:
			data = json.loads(frappe.local.request.get_data() or "{}")

		event_type = data.get("event_type")
		event_data = data.get("event_data") or {}

		if not event_type:
			frappe.throw(_("Missing event_type"), frappe.ValidationError)

		frappe.logger().info(f"💬 [Exchange Event] Received: {event_type}")

		try:
			frappe.enqueue(
				"erp.api.notification.exchange._handle_chat_event_async",
				queue="short",
				timeout=120,
				event_type=event_type,
				event_data=event_data,
			)
			return {"success": True, "message": f"Queued {event_type}", "queued": True}
		except Exception as enqueue_err:
			frappe.logger().error(f"❌ [Exchange Event] Enqueue failed, sync fallback: {enqueue_err}")
			_handle_chat_event_async(event_type, event_data)
			return {"success": True, "message": f"Processed {event_type} sync (fallback)", "queued": False}

	except Exception as e:
		frappe.logger().error(f"❌ [Exchange Event] {e}")
		frappe.log_error(message=str(e), title="Exchange Chat Event Error")
		return {"success": False, "message": str(e)}


def _handle_chat_event_async(event_type, event_data):
	try:
		if event_type == "new_message":
			_handle_new_chat_message(event_data)
		elif event_type == "message_reaction":
			_handle_chat_message_reaction(event_data)
		elif event_type == "message_recalled":
			_handle_chat_message_recalled(event_data)
		elif event_type == "poll_reminder":
			_handle_chat_poll_lifecycle(event_data, kind="reminder")
		elif event_type == "poll_closed":
			_handle_chat_poll_lifecycle(event_data, kind="closed")
		else:
			frappe.logger().warning(f"⚠️ [Exchange Async] Unknown event_type: {event_type}")
	except Exception as e:
		frappe.logger().error(f"❌ [Exchange Async] {event_type}: {e}")
		frappe.log_error(message=str(e), title=f"Exchange Async Error - {event_type}")


def _base_chat_data(event_data):
	"""Trường chung cho payload push + ERP Notification (mobile deep link)."""
	conv_id = str(event_data.get("conversationId") or "")
	return {
		"type": "chat_message",
		"conversationId": conv_id,
		"conversation_id": conv_id,
		"conversationType": event_data.get("conversationType"),
		"messageId": str(event_data.get("messageId") or ""),
		"senderName": event_data.get("senderName") or "",
		"senderEmail": event_data.get("senderEmail") or "",
		# 'text' | 'poll' — client phân biệt tin bình chọn. KHÔNG đổi "type" ở trên: giá trị mới
		# phải được thêm vào map kênh Android ở erp/api/erp_sis/mobile_push_notification.py.
		"messageKind": event_data.get("messageKind") or "text",
		"url": f"/feature/chat?conversation={conv_id}" if conv_id else "/feature/chat",
	}


def _handle_new_chat_message(event_data):
	recipient_emails = event_data.get("recipientEmails") or []
	if not isinstance(recipient_emails, list):
		recipient_emails = []
	recipient_emails = [e for e in recipient_emails if e]

	if not recipient_emails:
		frappe.logger().info("💬 [Exchange] new_message: no recipients")
		return

	conversation_id = str(event_data.get("conversationId") or "")
	sender_name = event_data.get("senderName") or DEFAULT_SENDER["vi"]
	preview_raw = (event_data.get("messagePreview") or "").strip()
	title_push = bi(str(sender_name)[:80], str(sender_name)[:80])
	body_push = _preview_bilingual(preview_raw, event_data.get("hasAttachment"))

	base = _base_chat_data(event_data)
	student_id = event_data.get("studentId") or event_data.get("student_id")
	if student_id:
		base["studentId"] = student_id
		base["student_id"] = student_id

	# Cờ bật ⇒ envelope của send_mobile_notifications_bulk đã tạo sẵn bản ghi hộp thư.
	push_via_service = push_delivered_by_notification_service()
	expo_targets = []
	mirror_targets = []

	for recipient_email in recipient_emails:
		merged = {**base}
		try:
			notif_doc = create_notification(
				title=title_push,
				message=body_push,
				recipient_user=recipient_email,
				notification_type="system",
				priority="medium",
				data=merged,
				channel="push",
				event_timestamp=frappe.utils.now(),
			)
			nid = notif_doc.name if hasattr(notif_doc, "name") else None
		except Exception as ne:
			frappe.logger().error(f"❌ [Exchange] ERP Notification failed {recipient_email}: {ne}")
			nid = None

		try:
			emit_notification_to_user(
				recipient_email,
				{
					"id": nid or f"CHAT-{frappe.generate_hash(length=8)}",
					"type": "chat_message",
					"title": title_push,
					"message": body_push,
					"status": "unread",
					"priority": "medium",
					"created_at": frappe.utils.now(),
					"data": merged,
				},
			)
			unread = get_unread_count(recipient_email)
			emit_unread_count_update(recipient_email, unread)
		except Exception as re:
			frappe.logger().error(f"❌ [Exchange] Realtime failed {recipient_email}: {re}")

		pushed_by_service = False
		if conversation_id and not _should_skip_expo_push(conversation_id, recipient_email):
			expo_targets.append({"email": recipient_email, "data": dict(merged)})
			_set_expo_debounce(conversation_id, recipient_email)
			pushed_by_service = push_via_service

		if not pushed_by_service:
			mirror_targets.append({"email": recipient_email, "data": dict(merged)})

	if expo_targets:
		try:
			res = send_mobile_notifications_bulk(expo_targets, title_push, body_push)
			frappe.logger().info(
				f"💬 [Exchange] Bulk Expo: {res.get('success_count', 0)}/{res.get('total_messages', 0)}"
			)
		except Exception as be:
			frappe.logger().error(f"❌ [Exchange] Bulk Expo failed: {be}")

	_mirror_to_notification_service(mirror_targets, title_push, body_push, "chat_message", "new_message")


def _handle_chat_poll_lifecycle(event_data, kind):
	"""Nhắc trước hạn / báo kết thúc bình chọn — in-app (ERP Notification + realtime) + push.

	Đi cùng đường với _handle_new_chat_message để phụ huynh và nhân viên đều nhận được;
	`data.type` phải nằm trong map kênh Android ở erp/api/erp_sis/mobile_push_notification.py,
	nếu không push sẽ rơi khỏi kênh "chat".
	"""
	recipient_emails = event_data.get("recipientEmails") or []
	if not isinstance(recipient_emails, list):
		recipient_emails = []
	recipient_emails = [e for e in recipient_emails if e]
	if not recipient_emails:
		frappe.logger().info(f"🗳️ [Exchange] poll_{kind}: no recipients")
		return

	question = (event_data.get("messagePreview") or "").strip()
	title_push = POLL_TITLE
	if kind == "reminder":
		notif_type = "chat_poll_reminder"
		if question:
			body_push = bi(
				_('Sắp hết hạn: "%(q)s" — bạn chưa bình chọn') % {"q": question},
				f'Closing soon: "{question}" — you have not voted yet',
			)
		else:
			body_push = bi(
				_("Một bình chọn sắp hết hạn — bạn chưa bình chọn"),
				"A poll is closing soon — you have not voted yet",
			)
	else:
		notif_type = "chat_poll_closed"
		if question:
			body_push = bi(
				_('Đã kết thúc: "%(q)s"') % {"q": question},
				f'Closed: "{question}"',
			)
		else:
			body_push = bi(_("Một bình chọn đã kết thúc"), "A poll has closed")

	base = _base_chat_data(event_data)
	base["type"] = notif_type
	base["messageKind"] = "poll"

	push_via_service = push_delivered_by_notification_service()
	expo_targets = []
	mirror_targets = []

	for recipient_email in recipient_emails:
		merged = {**base}
		try:
			notif_doc = create_notification(
				title=title_push,
				message=body_push,
				recipient_user=recipient_email,
				notification_type="system",
				priority="medium",
				data=merged,
				channel="push",
				event_timestamp=frappe.utils.now(),
			)
			nid = notif_doc.name if hasattr(notif_doc, "name") else None
		except Exception as ne:
			frappe.logger().error(f"❌ [Exchange] poll_{kind} notification {recipient_email}: {ne}")
			nid = None

		try:
			emit_notification_to_user(
				recipient_email,
				{
					"id": nid or f"POLL-{frappe.generate_hash(length=8)}",
					"type": notif_type,
					"title": title_push,
					"message": body_push,
					"status": "unread",
					"priority": "medium",
					"created_at": frappe.utils.now(),
					"data": merged,
				},
			)
			unread = get_unread_count(recipient_email)
			emit_unread_count_update(recipient_email, unread)
		except Exception as re:
			frappe.logger().error(f"❌ [Exchange] poll_{kind} realtime {recipient_email}: {re}")

		expo_targets.append({"email": recipient_email, "data": dict(merged)})
		if not push_via_service:
			mirror_targets.append({"email": recipient_email, "data": dict(merged)})

	if expo_targets:
		try:
			res = send_mobile_notifications_bulk(expo_targets, title_push, body_push)
			frappe.logger().info(
				f"🗳️ [Exchange] poll_{kind} bulk Expo: {res.get('success_count', 0)}/{res.get('total_messages', 0)}"
			)
		except Exception as be:
			frappe.logger().error(f"❌ [Exchange] poll_{kind} bulk Expo failed: {be}")

	_mirror_to_notification_service(mirror_targets, title_push, body_push, notif_type, f"poll_{kind}")


def _handle_chat_message_reaction(event_data):
	recipient_emails = event_data.get("recipientEmails") or []
	if not isinstance(recipient_emails, list):
		recipient_emails = []
	recipient_emails = [e for e in recipient_emails if e]
	if not recipient_emails:
		return

	sender_name = event_data.get("senderName")
	body = _reaction_body(sender_name)

	base = _base_chat_data(event_data)
	base["type"] = "chat_message_reaction"

	mirror_targets = []

	for recipient_email in recipient_emails:
		try:
			create_notification(
				title=CHAT_TITLE,
				message=body,
				recipient_user=recipient_email,
				notification_type="system",
				priority="low",
				data=base,
				channel="push",
				event_timestamp=frappe.utils.now(),
			)
			emit_notification_to_user(
				recipient_email,
				{
					"id": f"CHAT-REACT-{frappe.generate_hash(length=8)}",
					"type": "chat_message_reaction",
					"title": CHAT_TITLE,
					"message": body,
					"status": "unread",
					"priority": "low",
					"created_at": frappe.utils.now(),
					"data": base,
				},
			)
			unread = get_unread_count(recipient_email)
			emit_unread_count_update(recipient_email, unread)
			# Thả cảm xúc không gửi push — hộp thư luôn cần envelope mirror.
			mirror_targets.append({"email": recipient_email, "data": dict(base)})
		except Exception as e:
			frappe.logger().error(f"❌ [Exchange] reaction notify {recipient_email}: {e}")

	_mirror_to_notification_service(
		mirror_targets, CHAT_TITLE, body, "chat_message_reaction", "reaction"
	)


def _handle_chat_message_recalled(event_data):
	recipient_emails = event_data.get("recipientEmails") or []
	if not isinstance(recipient_emails, list):
		recipient_emails = []
	recipient_emails = [e for e in recipient_emails if e]
	if not recipient_emails:
		return

	base = _base_chat_data(event_data)
	base["type"] = "chat_message_recalled"

	for recipient_email in recipient_emails:
		try:
			emit_notification_to_user(
				recipient_email,
				{
					"id": f"CHAT-RECALL-{frappe.generate_hash(length=8)}",
					"type": "chat_message_recalled",
					"title": RECALL_TITLE,
					"message": bi("", ""),
					"status": "read",
					"priority": "low",
					"created_at": frappe.utils.now(),
					"data": base,
				},
			)
		except Exception as e:
			frappe.logger().error(f"❌ [Exchange] recall emit {recipient_email}: {e}")
