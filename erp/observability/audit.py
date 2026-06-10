# Copyright (c) 2026, Wellspring ERP
"""Hook audit CRUD/File — thay hooks_handlers.crud_logger + file_logger."""

from __future__ import annotations

import frappe

from erp.observability.helpers import log_crud as _log_crud
from erp.observability.helpers import log_error_audit as _log_error
from erp.observability.helpers import log_file_operation as _log_file


def _get_field_changes(doc, old_doc):
	changes = {}
	if not old_doc:
		return changes
	for field in doc.meta.get_valid_columns():
		old_value = old_doc.get(field)
		new_value = doc.get(field)
		if old_value != new_value:
			changes[field] = {"old": old_value, "new": new_value}
	return changes


def log_create(doc, method=None, **kwargs):
	try:
		user = frappe.session.user
		key_fields = _get_key_fields(doc.doctype)
		details = {field: doc.get(field) for field in key_fields if field in doc}
		details["timestamp"] = frappe.utils.now()

		_log_crud(doc.doctype, "create", doc.name, user, None, details)
	except Exception:
		pass


def log_update(doc, method=None, **kwargs):
	try:
		user = frappe.session.user
		old_doc = doc.get_doc_before_save() if hasattr(doc, "get_doc_before_save") else None
		changes = _get_field_changes(doc, old_doc) if old_doc else {}
		details = {"timestamp": frappe.utils.now(), "modified_at": getattr(doc, "modified", None)}

		_log_crud(doc.doctype, "update", doc.name, user, changes, details)
	except Exception:
		pass


def log_delete(doc, method=None, **kwargs):
	try:
		user = frappe.session.user
		key_fields = _get_key_fields(doc.doctype)
		details = {field: doc.get(field) for field in key_fields if field in doc}
		details["timestamp"] = frappe.utils.now()
		details["deleted_at"] = frappe.utils.now()

		_log_crud(doc.doctype, "delete", doc.name, user, None, details)
	except Exception:
		pass


def log_cancel(doc, method=None, **kwargs):
	try:
		user = frappe.session.user
		details = {"timestamp": frappe.utils.now(), "cancelled_at": frappe.utils.now()}

		_log_crud(doc.doctype, "cancel", doc.name, user, None, details)
	except Exception:
		pass


def log_file_upload(doc, method=None, **kwargs):
	try:
		user = frappe.session.user
		fs = ((doc.file_size or 0) / 1024) if getattr(doc, "file_size", None) is not None else 0.0

		_log_file(
			user=user,
			operation="upload",
			filename=doc.file_name or "",
			filesize_kb=float(fs),
			doctype=doc.attached_to_doctype,
			docname=doc.attached_to_name,
			is_private=bool(doc.is_private),
			details={
				"file_url": doc.file_url,
				"content_type": getattr(doc, "content_type", None),
				"timestamp": frappe.utils.now(),
			},
		)
	except Exception as exc:
		try:
			_log_error(frappe.session.user or "Guest", "log_file_upload", str(exc))
		except Exception:
			pass


def log_file_update(doc, method=None, **kwargs):
	try:
		user = frappe.session.user
		fs = ((doc.file_size or 0) / 1024) if getattr(doc, "file_size", None) is not None else 0.0

		_log_file(
			user=user,
			operation="update",
			filename=doc.file_name or "",
			filesize_kb=float(fs),
			doctype=doc.attached_to_doctype,
			docname=doc.attached_to_name,
			is_private=bool(doc.is_private),
			details={
				"file_url": doc.file_url,
				"content_type": getattr(doc, "content_type", None),
				"timestamp": frappe.utils.now(),
			},
		)
	except Exception as exc:
		_log_error(str(frappe.session.user), "log_file_update", str(exc))


def log_file_delete(doc, method=None, **kwargs):
	try:
		user = frappe.session.user
		fs = ((doc.file_size or 0) / 1024) if getattr(doc, "file_size", None) is not None else 0.0

		_log_file(
			user=user,
			operation="delete",
			filename=doc.file_name or "",
			filesize_kb=float(fs),
			doctype=doc.attached_to_doctype,
			docname=doc.attached_to_name,
			is_private=bool(doc.is_private),
			details={
				"file_url": doc.file_url,
				"content_type": getattr(doc, "content_type", None),
				"timestamp": frappe.utils.now(),
			},
		)
	except Exception as exc:
		_log_error(str(frappe.session.user), "log_file_delete", str(exc))


def _get_key_fields(doctype: str) -> list:
	key_fields_map = {
		"Student": ["name", "student_name", "student_code", "dob", "gender", "campus_id"],
		"Guardian": ["name", "guardian_id", "guardian_name", "phone_number", "email", "family_code"],
		"SIS Class Student": ["name", "campus_id", "class_id", "student_id", "school_year_id"],
		"SIS Class Attendance": ["name", "student_id", "class_id", "date", "status", "remarks"],
		"SIS Event": ["name", "title", "start_time", "end_time", "status", "campus_id"],
		"SIS Class": ["name", "title", "school_year_id", "education_grade", "homeroom_teacher"],
		"SIS Teacher": ["name", "user_id", "campus_id", "education_stage_id", "subject_department_id"],
		"SIS Subject": ["name", "title", "education_stage", "campus_id", "room_id", "is_homeroom"],
		"SIS Curriculum": ["name", "title_vn", "title_en", "campus_id"],
		"SIS Actual Subject": ["name", "title_vn", "title_en", "education_stage_id", "curriculum_id"],
		"SIS Timetable": ["name", "title_vn", "title_en", "school_year_id", "education_stage_id"],
		"SIS Timetable Subject": ["name", "title_vn", "title_en", "education_stage_id", "curriculum_id"],
		"SIS Photo": ["name", "title", "type", "school_year_id", "student_id"],
		"SIS School Year": ["name", "title_vn", "title_en", "start_date", "end_date", "is_enable"],
		"SIS Education Stage": ["name", "title_vn", "title_en", "campus_id"],
		"SIS Education Grade": ["name", "title_vn", "title_en", "education_stage_id", "grade_code"],
		"SIS Academic Program": ["name", "title_vn", "title_en", "campus_id"],
		"SIS Sub Curriculum": ["name", "title_vn", "title_en", "curriculum_id", "campus_id"],
		"SIS Calendar": ["name", "title", "type", "school_year_id", "start_date"],
		"SIS Subject Assignment": ["name", "teacher_id", "actual_subject_id", "class_id", "school_year_id", "application_type"],
		"Feedback": ["name", "guardian", "feedback_type", "status", "title"],
		"SIS Student Leave Request": ["name", "student_id", "start_date", "end_date", "reason", "campus_id"],
		"SIS Announcement": ["name", "title_vn", "title_en", "status", "campus_id"],
		"SIS News Article": ["name", "title_vn", "title_en", "status", "published_at"],
		"Daily Menu": ["name", "date", "campus"],
		"SIS Bus Route": ["name", "route_name", "driver_id", "status", "campus_id"],
		"SIS Bus Student": ["name", "student_code", "route_id", "status", "campus_id"],
		"SIS Bus Daily Trip": ["name", "route_id", "trip_date", "trip_status", "trip_type"],
		"SIS Badge": ["name", "title_vn", "title_en", "is_active"],
	}

	return key_fields_map.get(doctype, ["name"])
