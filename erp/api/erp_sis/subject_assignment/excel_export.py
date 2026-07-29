# Copyright (c) 2026, Wellspring International School and contributors
# For license information, please see license.txt

"""
Xuất phân công giảng dạy ra Excel (SIS-163).

File xuất ra dùng đúng template của chức năng nhập (excel_template.py), nên quy trình
chuẩn là: xuất ra -> sửa -> nạp lại. Đây cũng là cách duy nhất chống gõ sai tên lớp/môn,
vì ô dữ liệu không đặt được dropdown Excel.
"""

from io import BytesIO
from typing import Dict, List, Optional

import frappe
from frappe.utils import now_datetime

from erp.utils.api_response import error_response, forbidden_response
from erp.utils.campus_utils import get_current_campus_from_context

from .excel_template import (
	COL_CLASS,
	COL_END,
	COL_START,
	COL_SUBJECT,
	COL_TEACHER_CODE,
	COL_TEACHER_NAME,
	build_workbook,
)
from .utils import get_user_code_field


def _get_param(name: str) -> Optional[str]:
	"""Đọc tham số từ query string hoặc form_dict (FE gọi bằng cả GET lẫn POST)."""
	value = None
	if hasattr(frappe, "request") and getattr(frappe.request, "args", None):
		value = frappe.request.args.get(name)
	if not value:
		value = frappe.form_dict.get(name)
	if not value and hasattr(frappe, "local"):
		value = (frappe.local.form_dict or {}).get(name)
	return value or None


def collect_export_rows(
	campus_id: str,
	school_year_id: str,
	education_stage_id: str,
) -> List[Dict]:
	"""
	Các phân công thuộc một cấp học, đã dựng sẵn theo đúng cột của template.

	Cấp học xác định qua LỚP (class -> education_grade -> education_stage), không qua môn:
	một lớp chỉ thuộc đúng một cấp, còn môn có thể thiếu education_stage_id ở dữ liệu cũ.

	Phân công không gắn lớp (class_id để trống) bị loại — không quy được về cấp học nào
	và cũng không biểu diễn được trong file.
	"""
	code_field = get_user_code_field()
	code_select = f"u.`{code_field}`" if code_field else "NULL"

	return frappe.db.sql(
		f"""
		SELECT
			sa.name AS assignment_id,
			sa.application_type,
			sa.start_date,
			sa.end_date,
			COALESCE(NULLIF(u.full_name, ''), u.first_name, t.user_id) AS teacher_name,
			{code_select} AS teacher_code,
			subj.title_vn AS subject_title,
			COALESCE(NULLIF(c.short_title, ''), c.title) AS class_title,
			eg.sort_order AS grade_order
		FROM `tabSIS Subject Assignment` sa
		INNER JOIN `tabSIS Class` c ON c.name = sa.class_id
		INNER JOIN `tabSIS Education Grade` eg ON eg.name = c.education_grade
		LEFT JOIN `tabSIS Teacher` t ON t.name = sa.teacher_id
		LEFT JOIN `tabUser` u ON u.name = t.user_id
		LEFT JOIN `tabSIS Actual Subject` subj ON subj.name = sa.actual_subject_id
		WHERE sa.campus_id = %(campus_id)s
			AND sa.school_year_id = %(school_year_id)s
			AND eg.education_stage_id = %(education_stage_id)s
		ORDER BY teacher_name ASC, eg.sort_order ASC, class_title ASC,
			subject_title ASC, sa.start_date ASC
		""",
		{
			"campus_id": campus_id,
			"school_year_id": school_year_id,
			"education_stage_id": education_stage_id,
		},
		as_dict=True,
	)


def build_catalog(
	campus_id: str,
	school_year_id: str,
	education_stage_id: str,
) -> Dict[str, List[str]]:
	"""Danh mục giá trị hợp lệ để người dùng copy thay vì gõ tay."""
	classes = frappe.db.sql(
		"""
		SELECT COALESCE(NULLIF(c.short_title, ''), c.title) AS title
		FROM `tabSIS Class` c
		INNER JOIN `tabSIS Education Grade` eg ON eg.name = c.education_grade
		WHERE c.campus_id = %(campus_id)s
			AND c.school_year_id = %(school_year_id)s
			AND eg.education_stage_id = %(education_stage_id)s
		ORDER BY eg.sort_order ASC, title ASC
		""",
		{
			"campus_id": campus_id,
			"school_year_id": school_year_id,
			"education_stage_id": education_stage_id,
		},
		as_dict=True,
	)

	subjects = frappe.get_all(
		"SIS Actual Subject",
		filters={"campus_id": campus_id, "education_stage_id": education_stage_id},
		fields=["title_vn"],
		order_by="title_vn asc",
	)

	code_field = get_user_code_field()
	teacher_codes: List[str] = []
	if code_field:
		rows = frappe.db.sql(
			f"""
			SELECT DISTINCT u.`{code_field}` AS code
			FROM `tabSIS Teacher` t
			INNER JOIN `tabUser` u ON u.name = t.user_id
			WHERE t.campus_id = %(campus_id)s AND u.`{code_field}` IS NOT NULL
				AND u.`{code_field}` != ''
			ORDER BY code ASC
			""",
			{"campus_id": campus_id},
			as_dict=True,
		)
		teacher_codes = [r["code"] for r in rows]

	return {
		"Lớp hợp lệ": [c["title"] for c in classes if c.get("title")],
		"Môn học hợp lệ": [s["title_vn"] for s in subjects if s.get("title_vn")],
		"Giáo viên hợp lệ (Mã GV)": teacher_codes,
	}


@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def export_subject_assignments():
	"""
	Xuất phân công giảng dạy của một cấp học ra file Excel.

	Params: campus_id (mặc định lấy theo context), school_year_id, education_stage_id.
	Trả về file nhị phân .xlsx.
	"""
	try:
		campus_id = _get_param("campus_id") or get_current_campus_from_context()
		school_year_id = _get_param("school_year_id")
		education_stage_id = _get_param("education_stage_id")

		if not all([campus_id, school_year_id, education_stage_id]):
			return error_response(
				"Thiếu tham số: cần campus_id, school_year_id và education_stage_id",
				code="VALIDATION_ERROR",
			)

		user_campus = get_current_campus_from_context()
		if user_campus and user_campus != campus_id:
			return forbidden_response("Access denied: Campus mismatch")

		records = collect_export_rows(campus_id, school_year_id, education_stage_id)

		rows = []
		for record in records:
			is_full_year = record.get("application_type") == "full_year"
			rows.append({
				COL_TEACHER_NAME: record.get("teacher_name") or "",
				COL_TEACHER_CODE: record.get("teacher_code") or "",
				COL_SUBJECT: record.get("subject_title") or "",
				COL_CLASS: record.get("class_title") or "",
				# Cả năm thì để trống hai cột ngày, đúng quy ước đọc lại của import.
				COL_START: None if is_full_year else record.get("start_date"),
				COL_END: None if is_full_year else record.get("end_date"),
			})

		meta = {
			"campus": frappe.db.get_value("SIS Campus", campus_id, "title_vn") or campus_id,
			"school_year": frappe.db.get_value("SIS School Year", school_year_id, "title_vn")
			or school_year_id,
			"education_stage": frappe.db.get_value(
				"SIS Education Stage", education_stage_id, "title_vn"
			)
			or education_stage_id,
			"exported_at": now_datetime().strftime("%d/%m/%Y %H:%M"),
		}

		workbook = build_workbook(
			rows,
			meta,
			build_catalog(campus_id, school_year_id, education_stage_id),
		)

		stream = BytesIO()
		workbook.save(stream)

		stamp = now_datetime().strftime("%Y%m%d-%H%M")
		frappe.response["filename"] = f"phan-cong-giang-day-{stamp}.xlsx"
		frappe.response["filecontent"] = stream.getvalue()
		frappe.response["type"] = "binary"

	except Exception as e:
		frappe.log_error(f"Export subject assignments failed: {str(e)}")
		return error_response(f"Lỗi khi xuất file: {str(e)}")
