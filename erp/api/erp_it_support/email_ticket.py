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
	_creator_profile_from_email,
	_merge_attachments,
	_parse_json_body,
	_resolve_category_doc,
	_resolve_ticket_name,
	_ticket_id_from_request,
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
		# Display name từ email-service (fallback khi User không tồn tại trong Frappe)
		creator_fullname_fallback = (
			data.get("creatorFullname")
			or data.get("creator_fullname")
			or data.get("fromName")
			or ""
		).strip()
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

		# Lookup User → profile đầy đủ (avatar, jobtitle, department) như web
		creator = _creator_profile_from_email(creator_email, creator_fullname_fallback)

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
			"creator_email": creator["email"],
			"creator_fullname": creator["fullname"],
			"creator_avatar": creator["avatar"],
			"creator_department": creator["department"],
			"creator_jobtitle": creator["jobtitle"],
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
		data = _parse_json_body()
		tid = _resolve_ticket_name(_ticket_id_from_request(data, ticket_id))
		if not tid:
			return not_found_response(_("Ticket not found"))
		doc = frappe.get_doc(DOCTYPE, tid)
		return success_response(ticket_info_for_email(doc), "OK")
	except Exception as e:
		return error_response(str(e))


def backfill_creator_profiles(dry_run: int = 0):
	"""Backfill creator_avatar / creator_jobtitle cho ticket cũ tạo từ email.

	Chạy bằng:
	    bench --site <site> execute erp.api.erp_it_support.email_ticket.backfill_creator_profiles
	    bench --site <site> execute erp.api.erp_it_support.email_ticket.backfill_creator_profiles --kwargs '{"dry_run": 1}'
	"""
	dry = bool(int(dry_run or 0))
	tickets = frappe.get_all(
		DOCTYPE,
		filters={"source": "email"},
		fields=[
			"name",
			"creator_email",
			"creator_avatar",
			"creator_jobtitle",
			"creator_department",
			"creator_fullname",
		],
	)
	stats = {"checked": len(tickets), "updated": 0, "skipped_no_user": 0, "already_full": 0}
	for t in tickets:
		em = (t.get("creator_email") or "").strip().lower()
		if not em:
			stats["skipped_no_user"] += 1
			continue
		if t.get("creator_avatar") and t.get("creator_jobtitle"):
			stats["already_full"] += 1
			continue
		profile = _creator_profile_from_email(em, t.get("creator_fullname") or "")
		if not profile.get("avatar") and not profile.get("jobtitle"):
			stats["skipped_no_user"] += 1
			continue
		if dry:
			stats["updated"] += 1
			continue
		frappe.db.set_value(
			DOCTYPE,
			t["name"],
			{
				"creator_fullname": profile["fullname"],
				"creator_avatar": profile["avatar"] or t.get("creator_avatar") or "",
				"creator_department": profile["department"] or t.get("creator_department") or "",
				"creator_jobtitle": profile["jobtitle"] or t.get("creator_jobtitle") or "",
			},
			update_modified=False,
		)
		stats["updated"] += 1
	if not dry:
		frappe.db.commit()
	frappe.logger().info(f"[it_support.backfill_creator_profiles] {stats}")
	return stats


# Phase 2: Redis stream consumer `support_ticket_inbound` — placeholder
# def consume_support_ticket_inbound(event):
#     """XADD support_ticket_inbound → bench worker gọi create_from_email logic."""
#     pass
