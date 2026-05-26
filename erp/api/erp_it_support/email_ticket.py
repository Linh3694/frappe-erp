# Copyright (c) 2026, Wellspring International School and contributors
# Ticket IT từ email — endpoint nội bộ cho email-service

from __future__ import annotations

import json
import os
import re

import frappe
from frappe import _
from frappe.utils import get_files_path, now_datetime

from erp.api.erp_it_support.notifications import _it_send_emails_on_ticket_create
from erp.api.erp_it_support.utils import (
	DOCTYPE,
	_append_history,
	_merge_attachments,
	_parse_json_body,
	_resolve_category_doc,
	_resolve_pic_from_category_role,
	_ticket_to_dict,
	ticket_info_for_email,
)
from erp.utils.api_response import (
	error_response,
	not_found_response,
	success_response,
	validation_error_response,
)


def _verify_internal_request():
	"""Kiểm tra API key nội bộ (tùy chọn — guest whitelist vẫn cần key nếu cấu hình)."""
	expected = (frappe.conf.get("IT_SUPPORT_EMAIL_API_KEY") or "").strip()
	if not expected:
		return True
	got = (
		frappe.get_request_header("X-IT-Support-Key")
		or frappe.get_request_header("X-Internal-Api-Key")
		or ""
	).strip()
	return got == expected


@frappe.whitelist(allow_guest=True)
def create_from_email():
	"""
	Nhận ticket từ email-service (Phase 1 HTTP).
	Payload: { emailId, title, description, creatorEmail, files[], priority }
	"""
	try:
		if not _verify_internal_request():
			return error_response(_("Unauthorized"), code="UNAUTHORIZED")

		data = _parse_json_body()
		email_id = (data.get("emailId") or data.get("id") or data.get("email_id") or "").strip()
		title = (data.get("title") or data.get("subject") or "").strip()
		description = (data.get("description") or data.get("plainContent") or "").strip()
		creator_email = (data.get("creatorEmail") or data.get("from") or "").strip().lower()
		priority = (data.get("priority") or "Medium").strip()
		files = data.get("files") or data.get("attachments") or []

		if not title or not description:
			return validation_error_response(_("Thiếu title hoặc description"))

		# Dedupe theo email_id
		if email_id:
			existing = frappe.db.get_value(DOCTYPE, {"email_id": email_id}, "name")
			if existing:
				doc = frappe.get_doc(DOCTYPE, existing)
				return success_response(
					{
						"ticket": _ticket_to_dict(doc),
						"isDuplicate": True,
						"message": _("Email đã xử lý thành ticket {0}").format(doc.name),
					},
					"OK",
				)

		category_doc = _resolve_category_doc("Email Ticket")
		if not category_doc:
			return validation_error_response(_("Chưa cấu hình danh mục Email Ticket"))

		creator_user = frappe.db.get_value("User", {"email": creator_email}, "name")
		creator_fullname = creator_email.split("@")[0] if creator_email else "Email User"
		creator_dept = ""
		if creator_user:
			creator_fullname = frappe.db.get_value("User", creator_user, "full_name") or creator_fullname
			creator_dept = frappe.db.get_value("User", creator_user, "department") or ""

		pic = _resolve_pic_from_category_role("Email Ticket")
		row = {
			"doctype": DOCTYPE,
			"title": title,
			"description": description,
			"category": category_doc,
			"priority": priority,
			"status": "Assigned",
			"source": "email",
			"email_id": email_id or None,
			"creator_email": creator_email,
			"creator_fullname": creator_fullname,
			"creator_department": creator_dept,
		}
		if pic:
			row["assigned_to"] = pic
			row["assigned_to_fullname"] = frappe.db.get_value("User", pic, "full_name") or pic
			row["accepted_at"] = now_datetime()

		doc = frappe.get_doc(row)
		doc.insert(ignore_permissions=True)

		attachments = _save_email_files(doc.name, files)
		if attachments:
			doc.attachments_json = _merge_attachments(None, attachments)
			doc.save(ignore_permissions=True)

		_append_history(doc.name, _("Tạo ticket từ email"))
		frappe.db.commit()

		doc.reload()
		try:
			_it_send_emails_on_ticket_create(doc)
		except Exception:
			frappe.log_error(frappe.get_traceback(), "it_support.create_from_email.notify")

		return success_response({"ticket": _ticket_to_dict(doc), "isDuplicate": False}, "OK")
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error(frappe.get_traceback(), "it_support.create_from_email")
		return error_response(str(e))


def _save_email_files(ticket_code: str, files: list) -> list:
	"""Lưu file base64/url/data-URL từ email-service."""
	out = []
	if not files:
		return out
	dest_dir = os.path.join(get_files_path(), "it_support", ticket_code)
	os.makedirs(dest_dir, exist_ok=True)
	for item in files:
		if not item:
			continue
		if isinstance(item, dict):
			filename = (item.get("filename") or item.get("name") or "attachment").strip()
			url = (item.get("url") or item.get("path") or "").strip()
			if url.startswith("data:") and ";base64," in url:
				import base64

				safe = re.sub(r"[^\w.\-]", "_", filename)
				path = os.path.join(dest_dir, safe)
				b64 = url.split(";base64,", 1)[1]
				with open(path, "wb") as fh:
					fh.write(base64.b64decode(b64))
				out.append({"filename": safe, "url": f"/files/it_support/{ticket_code}/{safe}"})
				continue
			if url and not url.startswith("data:"):
				out.append({"filename": filename, "url": url})
				continue
			content = item.get("content") or item.get("data")
			if content:
				import base64

				safe = re.sub(r"[^\w.\-]", "_", filename)
				path = os.path.join(dest_dir, safe)
				with open(path, "wb") as fh:
					fh.write(base64.b64decode(content))
				out.append({"filename": safe, "url": f"/files/it_support/{ticket_code}/{safe}"})
	return out


@frappe.whitelist(allow_guest=True)
def get_ticket_info_for_email(ticket_id=None):
	"""Internal — email-service lấy thông tin ticket (thay ticket-service Mongo)."""
	try:
		if not _verify_internal_request():
			return error_response(_("Unauthorized"), code="UNAUTHORIZED")
		tid = ticket_id or frappe.form_dict.get("ticket_id")
		if not tid or not frappe.db.exists(DOCTYPE, tid):
			return not_found_response(_("Ticket not found"))
		doc = frappe.get_doc(DOCTYPE, tid)
		return success_response(ticket_info_for_email(doc), "OK")
	except Exception as e:
		return error_response(str(e))


# Phase 2: Redis stream consumer `support_ticket_inbound` — placeholder
# def consume_support_ticket_inbound(event):
#     """XADD support_ticket_inbound → bench worker gọi create_from_email logic."""
#     pass
