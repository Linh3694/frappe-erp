# Copyright (c) 2026, Wellspring International School and contributors
# Migrate dữ liệu MongoDB ticket-service → Frappe (idempotent + dry-run)
#
# Chạy (dry-run — tự đọc MONGODB_URI từ ticket-service/config.env nếu có):
#   bench --site <site> execute erp.api.erp_it_support.migration_mongo.run --kwargs '{"dry_run": 1}'
#
# Hoặc truyền trực tiếp:
#   bench --site <site> execute erp.api.erp_it_support.migration_mongo.run --kwargs '{"dry_run": 1, "mongo_uri": "mongodb://host:27017/wellspring_tickets"}'

from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime
from typing import Any, Optional
from urllib.parse import urlparse

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


def _parse_env_file(path: str) -> dict:
	"""Đọc file KEY=VALUE (config.env ticket-service) — không cần python-dotenv."""
	out = {}
	if not path or not os.path.isfile(path):
		return out
	try:
		with open(path, encoding="utf-8") as fh:
			for line in fh:
				line = line.strip()
				if not line or line.startswith("#") or "=" not in line:
					continue
				key, _, val = line.partition("=")
				key = key.strip()
				val = val.strip().strip('"').strip("'")
				if key:
					out[key] = val
	except Exception:
		frappe.logger().warning(f"migration_mongo: không đọc được {path}", exc_info=True)
	return out


def _ticket_service_config_candidates() -> list:
	"""Các đường dẫn config.env ticket-service trên dev/prod."""
	candidates = []
	bench_path = frappe.utils.get_bench_path()
	site_path = frappe.utils.get_site_path()
	app_root = os.path.dirname(bench_path)  # thường /srv/app

	for p in (
		frappe.conf.get("TICKET_SERVICE_CONFIG_PATH"),
		os.environ.get("TICKET_SERVICE_CONFIG_PATH"),
		os.path.join(app_root, "ticket-service", "config.env"),
		os.path.join(bench_path, "ticket-service", "config.env"),
		os.path.join(bench_path, "apps", "ticket-service", "config.env"),
		os.path.join(site_path, "..", "..", "ticket-service", "config.env"),
		"/srv/app/ticket-service/config.env",
		"/srv/app/frappe-backend/ticket-service/config.env",
	):
		if p:
			candidates.append(os.path.abspath(os.path.expanduser(str(p))))
	# unique, giữ thứ tự
	seen = set()
	unique = []
	for p in candidates:
		if p not in seen:
			seen.add(p)
			unique.append(p)
	return unique


def _build_mongo_uri_from_parts(env: dict) -> str:
	"""Ghép URI từ MONGODB_HOST/PORT/DATABASE như ticket-service config/database.js."""
	host = (env.get("MONGODB_HOST") or "").strip()
	port = (env.get("MONGODB_PORT") or "27017").strip()
	db = (env.get("MONGODB_DATABASE") or env.get("MONGODB_DB") or "wellspring_tickets").strip()
	user = (env.get("MONGODB_USER") or "").strip()
	password = (env.get("MONGODB_PASSWORD") or "").strip()
	if not host:
		return ""
	if user and password:
		return f"mongodb://{user}:{password}@{host}:{port}/{db}?authSource=admin"
	return f"mongodb://{host}:{port}/{db}"


def _database_name_from_uri(uri: str) -> str:
	"""Lấy tên DB từ MongoDB URI (mongodb://host:port/dbname)."""
	if not uri:
		return ""
	try:
		parsed = urlparse(uri.strip())
		# path dạng /wellspring_tickets hoặc /wellspring_tickets/
		segment = (parsed.path or "").strip("/").split("/")[0].strip()
		# Chỉ chấp nhận tên DB hợp lệ (không chứa / : @ ...)
		if segment and re.match(r"^[A-Za-z0-9_\-]+$", segment):
			return segment
	except Exception:
		pass
	return ""


def _resolve_mongo_config(mongo_uri: str = "", mongo_db: str = "") -> tuple:
	"""
	Tìm Mongo URI + DB name — ưu tiên kwargs → site_config → env → ticket-service/config.env.
	"""
	# Gộp env từ ticket-service config files
	file_env = {}
	config_source = None
	for cfg_path in _ticket_service_config_candidates():
		parsed = _parse_env_file(cfg_path)
		if parsed:
			file_env = parsed
			config_source = cfg_path
			break

	def pick(*keys):
		for k in keys:
			if mongo_uri and k.endswith("URI"):
				continue
			val = (frappe.conf.get(k) or os.environ.get(k) or file_env.get(k) or "").strip()
			if val:
				return val, k
		return "", ""

	uri = (mongo_uri or "").strip()
	uri_source = "kwargs.mongo_uri" if uri else ""

	if not uri:
		uri, key = pick("TICKET_MONGO_URI", "MONGODB_URI", "MONGO_URI")
		if uri:
			uri_source = key

	if not uri:
		uri = _build_mongo_uri_from_parts({**file_env, **dict(os.environ)})
		if uri:
			uri_source = config_source or "MONGODB_HOST/PORT"

	db_name = (mongo_db or "").strip()
	if not db_name:
		db_name, _ = pick("TICKET_MONGO_DB", "MONGODB_DATABASE", "MONGODB_DB")
	if not db_name:
		db_name = "wellspring_tickets"

	# Ưu tiên db name trong URI (parse đúng cả mongodb:// không có @)
	uri_db = _database_name_from_uri(uri)
	if uri_db:
		db_name = uri_db

	return uri, db_name, uri_source, config_source


def _resolve_uploads_root(uploads_root: str = "") -> str:
	if (uploads_root or "").strip():
		return os.path.abspath(uploads_root.strip())
	if (frappe.conf.get("TICKET_UPLOADS_ROOT") or os.environ.get("TICKET_UPLOADS_ROOT") or "").strip():
		return os.path.abspath(
			(frappe.conf.get("TICKET_UPLOADS_ROOT") or os.environ.get("TICKET_UPLOADS_ROOT")).strip()
		)
	bench_path = frappe.utils.get_bench_path()
	app_root = os.path.dirname(bench_path)
	for p in (
		os.path.join(app_root, "ticket-service", "uploads"),
		os.path.join(bench_path, "ticket-service", "uploads"),
		"/srv/app/ticket-service/uploads",
	):
		if os.path.isdir(p):
			return p
	return os.path.join(app_root, "ticket-service", "uploads")


def _get_mongo_client(mongo_uri: str):
	try:
		from pymongo import MongoClient
	except ImportError:
		frappe.throw(
			"Thiếu package pymongo. Chạy: bench setup requirements "
			"hoặc: ./env/bin/pip install pymongo"
		)
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
	mongo_db: str = "",
):
	"""
	Entry point bench execute.
	dry_run=1 — chỉ log, không ghi DB.
	mongo_uri — tùy chọn; mặc định đọc ticket-service/config.env (MONGODB_URI).
	"""
	dry = bool(int(dry_run)) if isinstance(dry_run, (int, str)) else bool(dry_run)
	uri, db_name, uri_source, config_path = _resolve_mongo_config(mongo_uri, mongo_db)

	if not uri:
		searched = _ticket_service_config_candidates()
		frappe.throw(
			"Thiếu MongoDB URI. Cách 1 — thêm vào site_config.json: "
			'"TICKET_MONGO_URI": "mongodb://<host>:27017/wellspring_tickets". '
			"Cách 2 — truyền --kwargs "
			'\'{"dry_run": 1, "mongo_uri": "mongodb://<host>:27017/wellspring_tickets"}\'. '
			f"Đã tìm config.env tại: {searched}"
		)

	root = _resolve_uploads_root(uploads_root)

	client = _get_mongo_client(uri)
	db = client[db_name]

	_log(f"Bắt đầu migrate (dry_run={dry}) mongo_db={db_name} uri_source={uri_source}", dry)
	if config_path:
		_log(f"Đọc config ticket-service: {config_path}", dry)
	_log(f"Uploads root: {root} (exists={os.path.isdir(root)})", dry)

	team_stats = migrate_support_team(db, dry_run=dry)
	ticket_stats = migrate_tickets(db, root, dry_run=dry, limit=int(limit or 0))
	result = {
		"team": team_stats,
		"tickets": ticket_stats,
		"dry_run": dry,
		"mongo_db": db_name,
		"uri_source": uri_source,
		"config_path": config_path,
		"uploads_root": root,
	}
	_log(f"Hoàn tất: {json.dumps(result)}", dry)
	return result
