"""Lưu trữ file LMS — 100% MinIO bucket lms-files (không Frappe File)."""

import json
import re
from uuid import uuid4

import frappe

from erp.lms.services.media_client import MediaServiceError, presign_file_download, presign_file_upload
from erp.lms.utils.enrollment import validate_section_enrollment
from erp.lms.utils.permissions import is_lms_staff, require_lms_staff

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
DEFAULT_BUCKET = "lms-files"
OBJECT_KEY_RE = re.compile(
	r"^files/(?P<course>[^/]+)/(?P<section>[^/]+)/(?P<file_id>[^/]+)/.+$"
)


def _parse_object_key(object_key: str) -> dict | None:
	m = OBJECT_KEY_RE.match(object_key or "")
	if not m:
		return None
	return m.groupdict()


def _assert_can_access_object(user: str, object_key: str, bucket: str) -> None:
	"""Kiểm tra quyền đọc object — theo course/section trong key."""
	if bucket and bucket != DEFAULT_BUCKET:
		frappe.throw("Bucket không hợp lệ", frappe.PermissionError)

	parsed = _parse_object_key(object_key)
	if not parsed:
		frappe.throw("object_key không hợp lệ", frappe.PermissionError)

	section_id = parsed["section"]
	if section_id == "general":
		return

	validate_section_enrollment(section_id, user, min_role="observer")


def presign_upload(
	course_id: str,
	section_id: str,
	filename: str,
	content_type: str,
	file_size: int,
	user: str | None = None,
) -> dict:
	"""Học sinh/GV upload — trả URL PUT cho browser."""
	user = user or frappe.session.user
	validate_section_enrollment(section_id, user, min_role="student")

	if not course_id:
		frappe.throw("course_id bắt buộc", frappe.ValidationError)
	if file_size <= 0 or file_size > MAX_FILE_SIZE:
		frappe.throw(f"Kích thước file tối đa {MAX_FILE_SIZE // (1024*1024)}MB")

	file_id = str(uuid4())[:12]
	try:
		data = presign_file_upload(
			course_id=course_id,
			section_id=section_id,
			filename=filename,
			content_type=content_type or "application/octet-stream",
			file_size=file_size,
			file_id=file_id,
		)
	except MediaServiceError as exc:
		frappe.throw(str(exc))

	return {
		"bucket": data.get("bucket") or DEFAULT_BUCKET,
		"object_key": data.get("object_key"),
		"file_id": data.get("file_id") or file_id,
		"upload_url": data.get("upload_url"),
		"method": data.get("method") or "PUT",
		"content_type": data.get("content_type") or content_type,
		"file_name": filename,
		"max_size": MAX_FILE_SIZE,
		"expires_in": data.get("expires_in") or 3600,
	}


def get_download_url(
	object_key: str,
	bucket: str | None = None,
	user: str | None = None,
) -> dict:
	user = user or frappe.session.user
	bucket = bucket or DEFAULT_BUCKET
	_assert_can_access_object(user, object_key, bucket)

	try:
		data = presign_file_download(object_key=object_key, bucket=bucket)
	except MediaServiceError as exc:
		frappe.throw(str(exc))

	return {
		"download_url": data.get("download_url"),
		"object_key": object_key,
		"bucket": bucket,
		"expires_in": data.get("expires_in") or 900,
	}


def normalize_attachments(attachments: list | None) -> list:
	"""Chuẩn hóa metadata đính kèm trước khi lưu submission."""
	if not attachments:
		return []
	out = []
	for att in attachments:
		if not isinstance(att, dict):
			continue
		object_key = att.get("object_key")
		if not object_key:
			# Legacy Frappe file_url — không còn khuyến nghị
			if att.get("file_url"):
				out.append(att)
			continue
		out.append(
			{
				"bucket": att.get("bucket") or DEFAULT_BUCKET,
				"object_key": object_key,
				"file_name": att.get("file_name") or att.get("filename"),
				"content_type": att.get("content_type"),
				"file_size": att.get("file_size"),
			}
		)
	return out


def parse_file_url_field(file_url: str | None) -> dict | None:
	"""
	Đọc field file_url của LMS File — JSON MinIO hoặc legacy path/URL.
	Trả metadata { bucket, object_key, file_name, file_url? } hoặc None.
	"""
	if not file_url:
		return None
	raw = file_url.strip()
	if raw.startswith("{"):
		try:
			data = json.loads(raw)
			if isinstance(data, dict) and data.get("object_key"):
				return {
					"bucket": data.get("bucket") or DEFAULT_BUCKET,
					"object_key": data["object_key"],
					"file_name": data.get("file_name") or data.get("filename"),
					"content_type": data.get("content_type"),
					"file_size": data.get("file_size"),
				}
		except json.JSONDecodeError:
			pass
	if raw.startswith("files/"):
		parts = raw.split("/")
		name = parts[-1] if parts else "file"
		return {
			"bucket": DEFAULT_BUCKET,
			"object_key": raw,
			"file_name": name,
		}
	return {"file_url": raw, "file_name": raw.rsplit("/", 1)[-1]}


def get_lms_file(file_id: str, user: str | None = None) -> dict:
	"""Chi tiết LMS File + metadata MinIO (nếu có)."""
	user = user or frappe.session.user
	if not frappe.db.exists("LMS File", file_id):
		frappe.throw("Không tìm thấy file", frappe.DoesNotExistError)

	doc = frappe.get_doc("LMS File", file_id)
	section_id = doc.section
	if section_id:
		validate_section_enrollment(section_id, user, min_role="observer")
	elif doc.course:
		from erp.lms.utils.permissions import user_enrolled_in_course

		if not is_lms_staff(user) and not user_enrolled_in_course(user, doc.course):
			frappe.throw("Không có quyền", frappe.PermissionError)

	row = doc.as_dict()
	row["file"] = parse_file_url_field(doc.file_url)
	return row


def _file_url_from_metadata(meta: dict) -> str:
	"""Lưu metadata MinIO vào field file_url (JSON)."""
	return json.dumps(
		{
			"bucket": meta.get("bucket") or DEFAULT_BUCKET,
			"object_key": meta["object_key"],
			"file_name": meta.get("file_name") or meta.get("filename"),
			"content_type": meta.get("content_type"),
			"file_size": meta.get("file_size"),
		},
		ensure_ascii=False,
	)


def create_lms_file(data: dict, user: str | None = None) -> dict:
	"""GV tạo LMS File sau khi upload MinIO."""
	user = user or frappe.session.user
	require_lms_staff()

	course_id = data.get("course") or data.get("course_id")
	section_id = data.get("section") or data.get("section_id")
	title = (data.get("title") or "").strip()
	object_key = data.get("object_key")

	if not course_id or not section_id or not title:
		frappe.throw("course, section, title bắt buộc", frappe.ValidationError)
	if not object_key:
		frappe.throw("object_key bắt buộc (upload MinIO trước)", frappe.ValidationError)

	validate_section_enrollment(section_id, user, min_role="teacher")

	file_url = _file_url_from_metadata(data)
	doc = frappe.get_doc(
		{
			"doctype": "LMS File",
			"course": course_id,
			"section": section_id,
			"title": title,
			"file_url": file_url,
			"folder": data.get("folder"),
		}
	)
	doc.insert()
	row = doc.as_dict()
	row["file"] = parse_file_url_field(doc.file_url)
	return row


def list_lms_files(section_id: str, user: str | None = None) -> list:
	"""Danh sách tài liệu khóa học trong section."""
	user = user or frappe.session.user
	validate_section_enrollment(section_id, user, min_role="observer")

	rows = frappe.get_all(
		"LMS File",
		filters={"section": section_id},
		fields=["name", "title", "course", "section", "file_url", "folder", "modified"],
		order_by="modified desc",
		limit=200,
	)
	for row in rows:
		row["file"] = parse_file_url_field(row.get("file_url"))
	return rows
