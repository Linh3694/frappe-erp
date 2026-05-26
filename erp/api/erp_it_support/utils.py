# Copyright (c) 2026, Wellspring International School and contributors
# Helpers chung cho API ticket IT Support

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional

import frappe
from frappe import _
from frappe.utils import get_files_path, now_datetime

from erp.it_support.doctype.erp_it_support_team_member.erp_it_support_team_member import (
	SUPPORT_ROLES,
)

DOCTYPE = "ERP IT Support Ticket"
COMMENT_DOCTYPE = "ERP IT Support Ticket Comment"
SUBTASK_DOCTYPE = "ERP IT Support Ticket Sub Task"
HISTORY_DOCTYPE = "ERP IT Support Ticket History"
CATEGORY_DOCTYPE = "ERP IT Support Category"
TEAM_DOCTYPE = "ERP IT Support Team Member"

_STAFF_ROLES = ("System Manager", "SIS IT", "SIS BOD")

# Map category FE (Mongo) → support role
CATEGORY_TO_ROLE = {
	"Overall": "Overall",
	"Vấn đề chung": "Overall",
	"Camera": "Camera System",
	"Camera System": "Camera System",
	"Hệ thống camera": "Camera System",
	"Network": "Network System",
	"Network System": "Network System",
	"Hệ thống mạng": "Network System",
	"Bell System": "Bell System",
	"Hệ thống chuông báo": "Bell System",
	"Software": "Software",
	"Hệ thống phần mềm": "Software",
	"Account": "Account",
	"Tài khoản": "Account",
	"Email Ticket": "Email Ticket",
}

CATEGORY_LABELS = {
	"Overall": "Vấn đề chung",
	"Camera": "Hệ thống camera",
	"Network": "Hệ thống mạng",
	"Bell System": "Hệ thống chuông báo",
	"Software": "Hệ thống phần mềm",
	"Account": "Tài khoản",
	"Email Ticket": "Email Ticket",
}

FEEDBACK_BADGES = (
	"Nhiệt Huyết",
	"Chu Đáo",
	"Vui Vẻ",
	"Tận Tình",
	"Chuyên Nghiệp",
)

ACTIVE_ASSIGN_STATUSES = ("Assigned", "Processing")


def _parse_json_body() -> dict:
	raw = frappe.request.data
	if raw:
		try:
			if isinstance(raw, bytes):
				data = json.loads(raw.decode("utf-8"))
			elif isinstance(raw, str):
				data = json.loads(raw)
			else:
				data = json.loads(raw)
		except (json.JSONDecodeError, TypeError, ValueError):
			data = dict(frappe.local.form_dict or {})
	else:
		data = dict(frappe.local.form_dict or {})
	return data


def _ticket_id_from_request(data=None, ticket_id=None, name=None) -> str:
	"""Gom ticket_id từ kwargs, JSON body và form_dict (GET/POST)."""
	data = data or {}
	return (
		(ticket_id or "").strip()
		or (name or "").strip()
		or str(data.get("ticket_id") or data.get("ticketId") or data.get("name") or "").strip()
		or str(frappe.form_dict.get("ticket_id") or frappe.form_dict.get("name") or "").strip()
	)


def _resolve_ticket_name(ref: Optional[str]) -> Optional[str]:
	"""Map mã ticket (name hoặc ticket_code) → doc name Frappe."""
	key = (ref or "").strip()
	if not key:
		return None
	if frappe.db.exists(DOCTYPE, key):
		return key
	# FE có thể gửi ticketCode thay vì name (migrate Mongo giữ OVR-0001, ...)
	doc_name = frappe.db.get_value(DOCTYPE, {"ticket_code": key}, "name")
	return doc_name or None


def _session_email() -> str:
	return (frappe.db.get_value("User", frappe.session.user, "email") or "").strip()


def _is_it_staff() -> bool:
	roles = frappe.get_roles(frappe.session.user) or []
	return any(r in roles for r in _STAFF_ROLES)


def _user_dict(user_id: Optional[str]) -> Optional[dict]:
	if not user_id:
		return None
	row = frappe.db.get_value(
		"User",
		user_id,
		["full_name", "email", "user_image", "department"],
		as_dict=True,
	)
	if not row:
		return None
	job = ""
	try:
		if frappe.get_meta("User").has_field("job_title"):
			job = frappe.db.get_value("User", user_id, "job_title") or ""
	except Exception:
		job = ""
	return {
		"_id": user_id,
		"fullname": row.get("full_name") or user_id,
		"email": row.get("email") or "",
		"avatarUrl": row.get("user_image") or "",
		"department": row.get("department") or "",
		"jobTitle": job,
	}


def _parse_json_field(raw) -> list:
	if raw is None:
		return []
	if isinstance(raw, list):
		return raw
	if isinstance(raw, str):
		try:
			parsed = json.loads(raw)
			return parsed if isinstance(parsed, list) else []
		except Exception:
			return []
	return []


def _category_title(doc) -> str:
	if not doc.category:
		return ""
	title = frappe.db.get_value(CATEGORY_DOCTYPE, doc.category, "title") or doc.category
	return title


def _resolve_category_doc(category_input: str) -> Optional[str]:
	"""Tìm name DocType category từ title / alias FE."""
	cat = (category_input or "").strip()
	if not cat:
		return None
	if frappe.db.exists(CATEGORY_DOCTYPE, cat):
		return cat
	by_title = frappe.db.get_value(CATEGORY_DOCTYPE, {"title": cat}, "name")
	if by_title:
		return by_title
	role = CATEGORY_TO_ROLE.get(cat) or cat
	by_role = frappe.db.get_value(CATEGORY_DOCTYPE, {"support_role": role}, "name")
	return by_role


def _resolve_pic_from_category_role(category_input: str) -> Optional[str]:
	"""Auto-assign theo role — load balancing số ticket đang xử lý."""
	cat_name = _resolve_category_doc(category_input)
	if not cat_name:
		return None
	support_role = frappe.db.get_value(CATEGORY_DOCTYPE, cat_name, "support_role") or ""
	if not support_role:
		support_role = CATEGORY_TO_ROLE.get(category_input) or category_input

	members = frappe.get_all(
		TEAM_DOCTYPE,
		filters={"is_active": 1},
		fields=["name", "user", "roles_json"],
	)
	candidates = []
	for m in members:
		roles = _parse_json_field(m.get("roles_json"))
		if support_role in roles:
			candidates.append(m.get("user"))

	if not candidates:
		return None
	if len(candidates) == 1:
		return candidates[0]

	stats = []
	for uid in candidates:
		cnt = frappe.db.count(
			DOCTYPE,
			{
				"assigned_to": uid,
				"status": ["in", list(ACTIVE_ASSIGN_STATUSES)],
			},
		)
		stats.append((cnt, uid))
	stats.sort(key=lambda x: x[0])
	return stats[0][1]


def _append_history(ticket_id: str, action: str, user=None, detail=None):
	"""Ghi lịch sử ticket."""
	user = user or frappe.session.user
	uemail = _session_email()
	if user and user != "Guest" and not uemail:
		uemail = frappe.db.get_value("User", user, "email") or ""
	ufn = frappe.db.get_value("User", user, "full_name") if user and user != "Guest" else ""
	if not ufn and uemail:
		ufn = frappe.db.get_value("User", {"email": uemail}, "full_name") or uemail
	uav = ""
	if user and user != "Guest":
		uav = frappe.db.get_value("User", user, "user_image") or ""
	row = frappe.get_doc(
		{
			"doctype": HISTORY_DOCTYPE,
			"ticket": ticket_id,
			"action": action,
			"detail": (detail or "").strip() or None,
			"user_email": uemail,
			"user_fullname": ufn or uemail,
			"user_avatar": uav,
		}
	)
	row.insert(ignore_permissions=True)


def _can_read_ticket(doc) -> bool:
	if _is_it_staff():
		return True
	email = _session_email()
	if doc.creator_email and doc.creator_email == email:
		return True
	if doc.assigned_to == frappe.session.user:
		return True
	return False


def _subtask_to_dict(row) -> dict:
	assigned = _user_dict(row.get("assigned_to")) if row.get("assigned_to") else None
	return {
		"_id": row.get("name"),
		"title": row.get("title") or "",
		"description": row.get("description") or "",
		"assignedTo": assigned,
		"status": row.get("status") or "In Progress",
		"createdAt": row.get("creation"),
		"updatedAt": row.get("modified"),
	}


def _history_to_dict(row) -> dict:
	user = None
	if row.get("user_email") or row.get("user_fullname"):
		user = {
			"_id": row.get("user_email") or "",
			"fullname": row.get("user_fullname") or "",
			"email": row.get("user_email") or "",
			"avatarUrl": row.get("user_avatar") or "",
		}
	return {
		"_id": row.get("name"),
		"timestamp": row.get("creation"),
		"action": row.get("action") or "",
		"user": user,
	}


def _ticket_to_dict(doc, include_relations=False) -> dict:
	"""Chuyển DocType → payload FE (giữ shape Mongo cũ)."""
	cat_title = _category_title(doc)
	creator = {
		"_id": doc.creator_email or "",
		"fullname": doc.creator_fullname or "",
		"email": doc.creator_email or "",
		"avatarUrl": doc.creator_avatar or "",
		"department": doc.creator_department or "",
		"jobTitle": getattr(doc, "creator_jobtitle", None) or "",
	}
	assigned = _user_dict(doc.assigned_to) if doc.assigned_to else None

	feedback = None
	if (doc.feedback_rating or 0) > 0:
		badges = _parse_json_field(doc.feedback_badges)
		feedback = {
			"assignedTo": doc.assigned_to,
			"rating": doc.feedback_rating,
			"comment": doc.feedback_comment or "",
			"badges": badges,
		}

	attachments = _parse_json_field(doc.attachments_json)
	if attachments and isinstance(attachments[0], dict):
		pass
	else:
		attachments = []

	out = {
		"_id": doc.name,
		"title": doc.title or "",
		"description": doc.description or "",
		"ticketCode": doc.ticket_code or doc.name,
		"status": doc.status or "Assigned",
		"creator": creator,
		"creatorEmail": doc.creator_email or "",
		"assignedTo": assigned,
		"priority": doc.priority or "Medium",
		"category": cat_title,
		"notes": doc.notes or "",
		"cancellationReason": doc.cancellation_reason or "",
		"feedback": feedback,
		"closedAt": doc.closed_at,
		"createdAt": doc.creation,
		"updatedAt": doc.modified,
		"acceptedAt": doc.accepted_at,
		"source": getattr(doc, "source", None) or "web",
		"emailId": getattr(doc, "email_id", None) or "",
		"attachments": attachments,
	}

	if include_relations:
		out["subTasks"] = _load_subtasks(doc.name)
		out["messages"] = _load_messages(doc.name)
		out["history"] = _load_history(doc.name)
	return out


def _load_subtasks(ticket_id: str) -> list:
	rows = frappe.get_all(
		SUBTASK_DOCTYPE,
		filters={"ticket": ticket_id},
		fields=[
			"name",
			"title",
			"description",
			"assigned_to",
			"assigned_to_fullname",
			"status",
			"creation",
			"modified",
		],
		order_by="creation asc",
	)
	return [_subtask_to_dict(r) for r in rows]


def _load_messages(ticket_id: str) -> list:
	rows = frappe.get_all(
		COMMENT_DOCTYPE,
		filters={"ticket": ticket_id},
		fields=[
			"name",
			"sender_email",
			"sender_fullname",
			"sender_avatar",
			"text",
			"message_type",
			"images_json",
			"creation",
		],
		order_by="creation asc",
	)
	messages = []
	for r in rows:
		imgs = _parse_json_field(r.get("images_json"))
		messages.append(
			{
				"_id": r.get("name"),
				"sender": {
					"_id": r.get("sender_email") or "",
					"fullname": r.get("sender_fullname") or "",
					"email": r.get("sender_email") or "",
					"avatarUrl": r.get("sender_avatar") or "",
				},
				"text": r.get("text") or "",
				"timestamp": r.get("creation"),
				"type": r.get("message_type") or "text",
				"images": imgs,
			}
		)
	return messages


def _load_history(ticket_id: str) -> list:
	rows = frappe.get_all(
		HISTORY_DOCTYPE,
		filters={"ticket": ticket_id},
		fields=[
			"name",
			"creation",
			"action",
			"detail",
			"user_email",
			"user_fullname",
			"user_avatar",
		],
		order_by="creation asc",
	)
	return [_history_to_dict(r) for r in rows]


def _save_uploaded_attachments(ticket_code: str) -> list:
	"""Lưu file multipart vào public/files/it_support/{ticketCode}/."""
	attachments = []
	if not frappe.request or not getattr(frappe.request, "files", None):
		return attachments
	files = frappe.request.files
	file_list = []
	if hasattr(files, "getlist"):
		file_list = files.getlist("attachments") or files.getlist("files") or []
	if not file_list and files.get("attachments"):
		file_list = [files.get("attachments")]
	if not file_list and files.get("files"):
		file_list = [files.get("files")]

	if not file_list:
		return attachments

	dest_dir = os.path.join(get_files_path(), "it_support", ticket_code)
	os.makedirs(dest_dir, exist_ok=True)

	for f in file_list:
		if not f or not getattr(f, "filename", None):
			continue
		safe_name = re.sub(r"[^\w.\-]", "_", f.filename)
		dest_path = os.path.join(dest_dir, safe_name)
		f.save(dest_path)
		url = f"/files/it_support/{ticket_code}/{safe_name}"
		attachments.append({"filename": safe_name, "url": url})
	return attachments


def _merge_attachments(existing_raw, new_items: list) -> str:
	existing = _parse_json_field(existing_raw)
	if existing and isinstance(existing[0], dict):
		merged = list(existing)
	else:
		merged = []
	for item in new_items or []:
		if item not in merged:
			merged.append(item)
	return json.dumps(merged, separators=(",", ":")) if merged else None


def _creator_profile_from_session() -> dict:
	user = frappe.session.user
	email = _session_email()
	ufn = frappe.db.get_value("User", user, "full_name") or user
	uimg = frappe.db.get_value("User", user, "user_image") or ""
	udept = frappe.db.get_value("User", user, "department") or ""
	ujob = ""
	try:
		if frappe.get_meta("User").has_field("job_title"):
			ujob = frappe.db.get_value("User", user, "job_title") or ""
	except Exception:
		pass
	return {
		"email": email,
		"fullname": ufn,
		"avatar": uimg,
		"department": udept,
		"jobtitle": ujob,
	}


def _team_member_to_dict(doc) -> dict:
	roles = _parse_json_field(doc.roles_json)
	return {
		"_id": doc.name,
		"userId": doc.user,
		"fullname": doc.full_name or doc.user,
		"email": doc.email or "",
		"avatarUrl": doc.avatar_url or "",
		"department": doc.department or "",
		"roles": roles,
		"isActive": bool(doc.is_active),
		"stats": {
			"totalTickets": doc.total_tickets or 0,
			"resolvedTickets": doc.resolved_tickets or 0,
			"averageRating": doc.average_rating or 0,
		},
		"notes": doc.notes or "",
		"createdAt": doc.creation,
		"updatedAt": doc.modified,
	}


def get_available_roles_list() -> list:
	return [{"value": r, "label": r} for r in SUPPORT_ROLES if r != "Email Ticket"]


def ticket_info_for_email(doc) -> dict:
	"""Payload cho email-service (tương thích ticket-service internal/info)."""
	creator = {
		"fullname": doc.creator_fullname or "",
		"email": doc.creator_email or "",
	}
	assigned = None
	if doc.assigned_to:
		assigned = {
			"fullname": doc.assigned_to_fullname
			or frappe.db.get_value("User", doc.assigned_to, "full_name")
			or doc.assigned_to,
			"email": frappe.db.get_value("User", doc.assigned_to, "email") or "",
		}
	return {
		"_id": doc.name,
		"ticketCode": doc.ticket_code or doc.name,
		"title": doc.title or "",
		"description": doc.description or "",
		"status": doc.status or "",
		"category": _category_title(doc),
		"priority": doc.priority or "Medium",
		"creator": creator,
		"assignedTo": assigned,
		"createdAt": doc.creation,
		"updatedAt": doc.modified,
		"closedAt": doc.closed_at,
	}
