# Copyright (c) 2026, Wellspring International School and contributors
# Migrate dữ liệu MongoDB ticket-service → Frappe (idempotent + dry-run)
#
# Chạy: bench --site <site> execute erp.api.erp_it_support.migration_mongo.run --kwargs '{"dry_run": 1}'

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from typing import Any, Optional

import frappe
from frappe.utils import get_datetime, get_files_path

from erp.api.erp_it_support.utils import (
	CATEGORY_TO_ROLE,
	COMMENT_DOCTYPE,
	DOCTYPE,
	HISTORY_DOCTYPE,
	SUBTASK_DOCTYPE,
	TEAM_DOCTYPE,
	_merge_attachments,
	_resolve_category_doc,
)

# Map category Mongo → title category Frappe
MONGO_CATEGORY_MAP = {
	"Overall": "Overall",
	"Camera": "Camera",
	"Network": "Network",
	"Bell System": "Bell System",
	"Software": "Software",
	"Account": "Account",
	"Email Ticket": "Email Ticket",
}


def _get_mongo_client(mongo_uri: str):
	try:
		from pymongo import MongoClient
	except ImportError as e:
		frappe.throw("Cần cài pymongo: thêm vào pyproject.toml và bench setup requirements")
	raise e
	return MongoClient(mongo_uri)


def _mongo_user_email(db, user_id) -> Optional[str]:
	if not user_id:
		return None
	from bson import ObjectId

	uid = user_id
	if isinstance(uid, str):
		try:
			uid = ObjectId(uid)
		except Exception:
			pass
	row = db.users.find_one({"_id": uid}) or db.Users.find_one({"_id": uid})
	if not row:
		return None
	return (row.get("email") or "").strip().lower()


def _frappe_user_by_email(email: str) -> Optional[str]:
	if not email:
		return None
	return frappe.db.get_value("User", {"email": email}, "name")


def _log(msg: str, dry_run: bool = False):
	prefix = "[DRY-RUN] " if dry_run else "[MIGRATE] "
	print(prefix + msg)
	frappe.logger().info(prefix + msg)


def migrate_support_team(db, dry_run: bool = False) -> dict:
	stats = {"created": 0, "skipped": 0, "errors": 0}
	coll = db.supportteammembers if "supportteammembers" in db.list_collection_names() else db.SupportTeamMember
	for row in coll.find({}):
		email = (row.get("email") or "").strip().lower()
		user_id = row.get("userId") or row.get("user")
		frappe_user = None
		if user_id:
			em = _mongo_user_email(db, user_id) or email
			frappe_user = _frappe_user_by_email(em)
		if not frappe_user and email:
			frappe_user = _frappe_user_by_email(email)
		if not frappe_user:
			stats["skipped"] += 1
			_log(f"Skip team member — chưa có User Frappe: {email}", dry_run)
			continue
		if frappe.db.exists(TEAM_DOCTYPE, frappe_user):
			stats["skipped"] += 1
			continue
		roles = row.get("roles") or []
		doc = {
			"doctype": TEAM_DOCTYPE,
			"user": frappe_user,
			"roles_json": json.dumps(roles, separators=(",", ":")),
			"is_active": 1 if row.get("isActive", row.get("active", True)) else 0,
			"notes": row.get("notes") or "",
		}
		if dry_run:
			stats["created"] += 1
			continue
		try:
			frappe.get_doc(doc).insert(ignore_permissions=True)
			stats["created"] += 1
		except Exception as e:
			stats["errors"] += 1
			_log(f"Error team member {frappe_user}: {e}", dry_run)
	if not dry_run:
		frappe.db.commit()
	return stats


def _copy_ticket_attachments(ticket_code: str, uploads_root: str, dry_run: bool) -> list:
	src = os.path.join(uploads_root, "Tickets", ticket_code)
	if not os.path.isdir(src):
		return []
	dest_dir = os.path.join(get_files_path(), "it_support", ticket_code)
	attachments = []
	for fname in os.listdir(src):
		src_path = os.path.join(src, fname)
		if not os.path.isfile(src_path):
			continue
		if not dry_run:
			os.makedirs(dest_dir, exist_ok=True)
			shutil.copy2(src_path, os.path.join(dest_dir, fname))
		attachments.append({"filename": fname, "url": f"/files/it_support/{ticket_code}/{fname}"})
	return attachments


def migrate_tickets(
	db,
	uploads_root: str,
	dry_run: bool = False,
	limit: int = 0,
) -> dict:
	stats = {"created": 0, "skipped": 0, "errors": 0, "comments": 0, "history": 0, "subtasks": 0}
	coll = db.tickets if "tickets" in db.list_collection_names() else db.Ticket
	cursor = coll.find({}).sort("createdAt", 1)
	if limit:
		cursor = cursor.limit(int(limit))

	for row in cursor:
		ticket_code = (row.get("ticketCode") or "").strip()
		if not ticket_code:
			stats["errors"] += 1
			continue
		if frappe.db.exists(DOCTYPE, ticket_code):
			stats["skipped"] += 1
			continue
		email_id = (row.get("emailId") or "").strip()
		if email_id and frappe.db.exists(DOCTYPE, {"email_id": email_id}):
			stats["skipped"] += 1
			continue

		cat_raw = row.get("category") or "Overall"
		cat_title = MONGO_CATEGORY_MAP.get(cat_raw, cat_raw)
		category_doc = _resolve_category_doc(cat_title)
		if not category_doc:
			_log(f"Skip {ticket_code} — không có category {cat_title}", dry_run)
			stats["errors"] += 1
			continue

		creator_email = _mongo_user_email(db, row.get("creator")) or ""
		creator_user = _frappe_user_by_email(creator_email)
		creator_doc = db.users.find_one({"_id": row.get("creator")}) if row.get("creator") else None
		if not creator_doc and row.get("creator"):
			creator_doc = db.Users.find_one({"_id": row.get("creator")})

		assigned_email = _mongo_user_email(db, row.get("assignedTo"))
		assigned_user = _frappe_user_by_email(assigned_email) if assigned_email else None

		feedback = row.get("feedback") or {}
		badges = feedback.get("badges") or []

		attachments = row.get("attachments") or []
		frappe_attachments = []
		for a in attachments:
			if isinstance(a, dict) and a.get("url"):
				url = a["url"]
				if url.startswith("uploads/"):
					url = "/" + url.replace("uploads/", "files/", 1)
				frappe_attachments.append({"filename": a.get("filename") or "", "url": url})

		copied = _copy_ticket_attachments(ticket_code, uploads_root, dry_run)
		frappe_attachments.extend(copied)

		doc_dict = {
			"doctype": DOCTYPE,
			"name": ticket_code,
			"title": row.get("title") or ticket_code,
			"description": row.get("description") or "",
			"ticket_code": ticket_code,
			"category": category_doc,
			"status": row.get("status") or "Assigned",
			"priority": row.get("priority") or "Medium",
			"notes": row.get("notes") or "",
			"cancellation_reason": row.get("cancellationReason") or "",
			"creator_email": creator_email,
			"creator_fullname": (creator_doc or {}).get("fullname") or creator_email,
			"creator_avatar": (creator_doc or {}).get("avatarUrl") or "",
			"creator_department": (creator_doc or {}).get("department") or "",
			"assigned_to": assigned_user,
			"assigned_to_fullname": frappe.db.get_value("User", assigned_user, "full_name") if assigned_user else "",
			"source": row.get("source") or "web",
			"email_id": email_id or None,
			"email_message_id": row.get("emailMessageId") or "",
			"waiting_for_customer_email_sent": 1 if row.get("waitingForCustomerEmailSent") else 0,
			"feedback_rating": feedback.get("rating") or 0,
			"feedback_comment": feedback.get("comment") or "",
			"feedback_badges": json.dumps(badges, separators=(",", ":")) if badges else None,
			"attachments_json": json.dumps(frappe_attachments, separators=(",", ":")) if frappe_attachments else None,
			"escalate_level": row.get("escalateLevel") or 0,
		}
		if row.get("sla"):
			doc_dict["sla_deadline"] = get_datetime(row["sla"])
		if row.get("acceptedAt"):
			doc_dict["accepted_at"] = get_datetime(row["acceptedAt"])
		if row.get("closedAt"):
			doc_dict["closed_at"] = get_datetime(row["closedAt"])
		if row.get("createdAt"):
			doc_dict["creation"] = get_datetime(row["createdAt"])
		if row.get("updatedAt"):
			doc_dict["modified"] = get_datetime(row["updatedAt"])

		if dry_run:
			stats["created"] += 1
			continue

		try:
			doc = frappe.get_doc(doc_dict)
			doc.insert(ignore_permissions=True, set_name=ticket_code)

			for msg in row.get("messages") or []:
				sender_email = _mongo_user_email(db, msg.get("sender")) or ""
				sender_doc = None
				if msg.get("sender"):
					sender_doc = db.users.find_one({"_id": msg.get("sender")}) or db.Users.find_one({"_id": msg.get("sender")})
				imgs = msg.get("images") or []
				frappe.get_doc(
					{
						"doctype": COMMENT_DOCTYPE,
						"ticket": ticket_code,
						"sender_email": sender_email,
						"sender_fullname": (sender_doc or {}).get("fullname") or sender_email,
						"sender_avatar": (sender_doc or {}).get("avatarUrl") or "",
						"text": msg.get("text") or "",
						"message_type": msg.get("type") or "text",
						"images_json": json.dumps(imgs, separators=(",", ":")) if imgs else None,
						"creation": get_datetime(msg.get("timestamp")) if msg.get("timestamp") else None,
					}
				).insert(ignore_permissions=True)
				stats["comments"] += 1

			for h in row.get("history") or []:
				hemail = _mongo_user_email(db, h.get("user")) or ""
				hdoc = None
				if h.get("user"):
					hdoc = db.users.find_one({"_id": h.get("user")}) or db.Users.find_one({"_id": h.get("user")})
				frappe.get_doc(
					{
						"doctype": HISTORY_DOCTYPE,
						"ticket": ticket_code,
						"action": h.get("action") or "",
						"user_email": hemail,
						"user_fullname": (hdoc or {}).get("fullname") or hemail,
						"user_avatar": (hdoc or {}).get("avatarUrl") or "",
						"creation": get_datetime(h.get("timestamp")) if h.get("timestamp") else None,
					}
				).insert(ignore_permissions=True)
				stats["history"] += 1

			for st in row.get("subTasks") or []:
				st_assigned = _frappe_user_by_email(_mongo_user_email(db, st.get("assignedTo")))
				frappe.get_doc(
					{
						"doctype": SUBTASK_DOCTYPE,
						"ticket": ticket_code,
						"title": st.get("title") or "",
						"description": st.get("description") or "",
						"assigned_to": st_assigned,
						"assigned_to_fullname": frappe.db.get_value("User", st_assigned, "full_name") if st_assigned else "",
						"status": st.get("status") or "In Progress",
						"creation": get_datetime(st.get("createdAt")) if st.get("createdAt") else None,
						"modified": get_datetime(st.get("updatedAt")) if st.get("updatedAt") else None,
					}
				).insert(ignore_permissions=True)
				stats["subtasks"] += 1

			stats["created"] += 1
		except Exception as e:
			stats["errors"] += 1
			frappe.db.rollback()
			_log(f"Error ticket {ticket_code}: {e}", dry_run)

	if not dry_run:
		frappe.db.commit()
	return stats


def run(
	dry_run: bool = False,
	mongo_uri: str = "",
	uploads_root: str = "",
	limit: int = 0,
):
	"""
	Entry point bench execute.
	dry_run=1 — chỉ log, không ghi DB.
	"""
	dry = bool(int(dry_run)) if isinstance(dry_run, (int, str)) else bool(dry_run)
	uri = mongo_uri or frappe.conf.get("TICKET_MONGO_URI") or os.environ.get("TICKET_MONGO_URI", "")
	if not uri:
		frappe.throw("Thiếu TICKET_MONGO_URI (site_config hoặc --kwargs)")

	root = uploads_root or frappe.conf.get("TICKET_UPLOADS_ROOT") or ""
	if not root:
		# Mặc định: frappe-backend/ticket-service/uploads
		bench_path = frappe.utils.get_bench_path()
		root = os.path.join(os.path.dirname(bench_path), "ticket-service", "uploads")
		if not os.path.isdir(root):
			root = os.path.join(bench_path, "ticket-service", "uploads")

	client = _get_mongo_client(uri)
	db_name = frappe.conf.get("TICKET_MONGO_DB") or os.environ.get("TICKET_MONGO_DB", "ticket-service")
	db = client[db_name]

	_log(f"Bắt đầu migrate (dry_run={dry}) DB={db_name}", dry)
	team_stats = migrate_support_team(db, dry_run=dry)
	ticket_stats = migrate_tickets(db, root, dry_run=dry, limit=int(limit or 0))
	result = {"team": team_stats, "tickets": ticket_stats, "dry_run": dry}
	_log(f"Hoàn tất: {json.dumps(result)}", dry)
	return result
