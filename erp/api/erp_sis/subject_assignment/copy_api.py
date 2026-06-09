# Copyright (c) 2026, Wellspring International School and contributors
# Sao chép phân công giảng dạy từ năm học nguồn sang năm học đích.

import json
from typing import Dict, List, Optional

import frappe
from frappe import _

from erp.utils.api_response import error_response, success_response
from erp.utils.campus_utils import get_current_campus_from_context

from .utils import validate_school_year_matches_class


def _build_class_map(
	campus_id: str,
	source_school_year_id: str,
	target_school_year_id: str,
) -> Dict[str, str]:
	"""
	Map class_id nguồn → class_id đích theo title + education_grade trong cùng campus.
	"""
	source_classes = frappe.get_all(
		"SIS Class",
		filters={
			"campus_id": campus_id,
			"school_year_id": source_school_year_id,
		},
		fields=["name", "title", "education_grade"],
	)
	target_classes = frappe.get_all(
		"SIS Class",
		filters={
			"campus_id": campus_id,
			"school_year_id": target_school_year_id,
		},
		fields=["name", "title", "education_grade"],
	)

	target_by_key = {
		(f"{c.education_grade}::{c.title}"): c.name
		for c in target_classes
		if c.get("title")
	}

	class_map: Dict[str, str] = {}
	for sc in source_classes:
		key = f"{sc.education_grade}::{sc.title}"
		if key in target_by_key:
			class_map[sc.name] = target_by_key[key]

	return class_map


@frappe.whitelist(allow_guest=False, methods=["POST"])
def copy_subject_assignments():
	"""
	Sao chép phân công từ năm học nguồn sang năm học đích.

	Body:
		source_school_year_id (required)
		target_school_year_id (required)
		teacher_ids (optional list)
		class_ids (optional list — lọc theo lớp nguồn)
	"""
	try:
		data = {}
		if frappe.request.data:
			try:
				data = json.loads(frappe.request.data) or {}
			except (json.JSONDecodeError, TypeError):
				data = dict(frappe.form_dict)
		else:
			data = dict(frappe.form_dict)

		source_school_year_id = data.get("source_school_year_id")
		target_school_year_id = data.get("target_school_year_id")
		teacher_ids = data.get("teacher_ids") or []
		class_ids = data.get("class_ids") or []

		if isinstance(teacher_ids, str):
			teacher_ids = json.loads(teacher_ids)
		if isinstance(class_ids, str):
			class_ids = json.loads(class_ids)

		if not source_school_year_id or not target_school_year_id:
			return error_response(_("source_school_year_id and target_school_year_id are required"))

		if source_school_year_id == target_school_year_id:
			return error_response(_("Source and target school year must be different"))

		campus_id = get_current_campus_from_context() or "campus-1"

		class_map = _build_class_map(
			campus_id,
			source_school_year_id,
			target_school_year_id,
		)

		filters = {
			"campus_id": campus_id,
			"school_year_id": source_school_year_id,
		}
		if teacher_ids:
			filters["teacher_id"] = ["in", teacher_ids]
		if class_ids:
			filters["class_id"] = ["in", class_ids]

		source_assignments = frappe.get_all(
			"SIS Subject Assignment",
			filters=filters,
			fields=[
				"name",
				"teacher_id",
				"class_id",
				"actual_subject_id",
				"application_type",
				"start_date",
				"end_date",
				"weekdays",
			],
		)

		created: List[str] = []
		skipped: List[Dict] = []
		unmapped_classes: List[str] = []

		for sa in source_assignments:
			src_class = sa.get("class_id")
			if not src_class:
				skipped.append({"source": sa.name, "reason": "no_class_id"})
				continue

			tgt_class = class_map.get(src_class)
			if not tgt_class:
				if src_class not in unmapped_classes:
					unmapped_classes.append(src_class)
				skipped.append({"source": sa.name, "reason": "unmapped_class", "class_id": src_class})
				continue

			validate_school_year_matches_class(target_school_year_id, tgt_class)

			dup_filters = {
				"teacher_id": sa.teacher_id,
				"class_id": tgt_class,
				"actual_subject_id": sa.actual_subject_id,
				"campus_id": campus_id,
				"school_year_id": target_school_year_id,
			}
			if frappe.db.exists("SIS Subject Assignment", dup_filters):
				skipped.append({"source": sa.name, "reason": "duplicate"})
				continue

			doc = frappe.get_doc({
				"doctype": "SIS Subject Assignment",
				"teacher_id": sa.teacher_id,
				"class_id": tgt_class,
				"actual_subject_id": sa.actual_subject_id,
				"campus_id": campus_id,
				"school_year_id": target_school_year_id,
				"application_type": sa.application_type or "full_year",
				"start_date": sa.start_date,
				"end_date": sa.end_date,
				"weekdays": sa.weekdays,
			})
			doc.insert(ignore_permissions=True)
			created.append(doc.name)

		frappe.db.commit()

		return success_response(
			data={
				"created_count": len(created),
				"skipped_count": len(skipped),
				"unmapped_class_count": len(unmapped_classes),
				"created": created,
				"skipped": skipped[:50],
				"unmapped_classes": unmapped_classes[:50],
			},
			message=_("Copied {0} assignment(s)").format(len(created)),
		)

	except Exception as e:
		frappe.db.rollback()
		frappe.log_error(f"copy_subject_assignments: {e}")
		return error_response(str(e))
