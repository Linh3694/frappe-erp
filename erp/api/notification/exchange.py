# Copyright (c) 2026, Wellspring International School and contributors
"""
Wave 3: Push + ERP Notification cho chat Trao đổi (social-service → Frappe).
Nhận webhook từ social-service, enqueue RQ short, debounce Expo theo (conversation, recipient).
"""

import json

import frappe
from frappe import _

from erp.api.parent_portal.realtime_notification import (
	emit_notification_to_user,
	emit_unread_count_update,
)
from erp.common.doctype.erp_notification.erp_notification import create_notification, get_unread_count
from erp.api.erp_sis.mobile_push_notification import send_mobile_notifications_bulk


# Debounce giữa các lần Expo push cho cùng hội thoại + người nhận (tránh spam khi chat liên tục)
CHAT_EXPO_DEBOUNCE_SECONDS = 5


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
	sender_name = event_data.get("senderName") or _("Trao đổi")
	preview_raw = (event_data.get("messagePreview") or "").strip()
	if not preview_raw and event_data.get("hasAttachment"):
		preview_raw = _("[Tệp đính kèm]")
	title_push = str(sender_name)[:80]
	body_push = preview_raw[:200] if preview_raw else _("Tin nhắn mới")

	base = _base_chat_data(event_data)
	student_id = event_data.get("studentId") or event_data.get("student_id")
	if student_id:
		base["studentId"] = student_id
		base["student_id"] = student_id

	expo_targets = []

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

		if conversation_id and not _should_skip_expo_push(conversation_id, recipient_email):
			expo_targets.append({"email": recipient_email, "data": dict(merged)})
			_set_expo_debounce(conversation_id, recipient_email)

	if expo_targets:
		try:
			res = send_mobile_notifications_bulk(expo_targets, title_push, body_push)
			frappe.logger().info(
				f"💬 [Exchange] Bulk Expo: {res.get('success_count', 0)}/{res.get('total_messages', 0)}"
			)
		except Exception as be:
			frappe.logger().error(f"❌ [Exchange] Bulk Expo failed: {be}")


def _handle_chat_message_reaction(event_data):
	recipient_emails = event_data.get("recipientEmails") or []
	if not isinstance(recipient_emails, list):
		recipient_emails = []
	recipient_emails = [e for e in recipient_emails if e]
	if not recipient_emails:
		return

	sender_name = event_data.get("senderName") or _("Ai đó")
	body = _("%(name)s đã thả cảm xúc tin nhắn") % {"name": sender_name}

	base = _base_chat_data(event_data)
	base["type"] = "chat_message_reaction"

	for recipient_email in recipient_emails:
		try:
			create_notification(
				title="Trao đổi",
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
					"title": "Trao đổi",
					"message": body,
					"status": "unread",
					"priority": "low",
					"created_at": frappe.utils.now(),
					"data": base,
				},
			)
			unread = get_unread_count(recipient_email)
			emit_unread_count_update(recipient_email, unread)
		except Exception as e:
			frappe.logger().error(f"❌ [Exchange] reaction notify {recipient_email}: {e}")


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
					"title": _("Tin nhắn đã thu hồi"),
					"message": "",
					"status": "read",
					"priority": "low",
					"created_at": frappe.utils.now(),
					"data": base,
				},
			)
		except Exception as e:
			frappe.logger().error(f"❌ [Exchange] recall emit {recipient_email}: {e}")
