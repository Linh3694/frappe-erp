# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

"""
Utility functions for Subject Assignment module
"""

from typing import Dict, List, Optional

import frappe
from frappe import _


def get_user_code_field() -> Optional[str]:
	"""
	Tên cột mã nhân viên trên doctype User.

	Mã GV không nằm trên SIS Teacher mà trên User (đồng bộ từ Microsoft `employeeId`).
	Tuỳ cấu hình site, cột có thể là `employee_code`, `employee_id`, hoặc không tồn tại —
	nên phải dò thay vì hardcode, giống cách bulk_import.py đang làm.
	"""
	for field in ("employee_code", "employee_id"):
		try:
			if frappe.db.has_column("User", field):
				return field
		except Exception:
			continue
	return None


def get_teacher_directory(campus_id: str) -> List[Dict]:
	"""
	Danh bạ giáo viên của một campus: teacher_id, họ tên hiển thị, mã GV.

	Dùng chung cho export (điền cột Mã GV) và import (tra mã GV ngược về teacher_id),
	để hai chiều không bao giờ lệch nhau về cách lấy tên/mã.
	"""
	if not campus_id:
		return []

	from erp.api.utils import format_person_display_name

	code_field = get_user_code_field()
	code_select = f"u.`{code_field}`" if code_field else "NULL"

	rows = frappe.db.sql(
		f"""
		SELECT
			t.name AS teacher_id,
			t.user_id,
			u.first_name,
			u.last_name,
			u.full_name AS raw_full_name,
			{code_select} AS teacher_code
		FROM `tabSIS Teacher` t
		LEFT JOIN `tabUser` u ON u.name = t.user_id
		WHERE t.campus_id = %(campus_id)s
		""",
		{"campus_id": campus_id},
		as_dict=True,
	)

	# full_name của Frappe = first_name + last_name nên bị ngược với dữ liệu SSO của trường
	# ('Anh Lê Hoàng' thay vì 'Lê Hoàng Anh') — dựng lại từ hai cột có cấu trúc.
	for row in rows:
		row["full_name"] = format_person_display_name(
			row.get("first_name"),
			row.get("last_name"),
			row.get("raw_full_name"),
			fallback=row.get("user_id"),
		)

	rows.sort(key=lambda r: (r.get("full_name") or "").lower())
	return rows


def build_teacher_code_lookup(campus_id: str) -> Dict[str, str]:
	"""
	Bảng tra mã GV (chuẩn hoá hoa/thường + trim) -> teacher_id.

	Nhận cả user_id (email) làm khoá phụ để file cũ điền email vẫn dùng được.
	Mã xuất hiện ở nhiều giáo viên thì bỏ hẳn khỏi bảng tra — thà báo "không tìm thấy"
	còn hơn gán nhầm phân công cho người khác.
	"""
	lookup: Dict[str, str] = {}
	duplicated = set()

	for row in get_teacher_directory(campus_id):
		for raw in (row.get("teacher_code"), row.get("user_id")):
			if not raw:
				continue
			key = str(raw).strip().lower()
			if not key:
				continue
			if key in lookup and lookup[key] != row["teacher_id"]:
				duplicated.add(key)
			else:
				lookup[key] = row["teacher_id"]

	for key in duplicated:
		lookup.pop(key, None)

	return lookup


def get_active_school_year_for_campus(campus_id: str) -> Optional[str]:
	"""Năm học đang bật (is_enable) của campus, ưu tiên start_date mới nhất."""
	if not campus_id:
		return None
	return frappe.db.get_value(
		"SIS School Year",
		{"is_enable": 1, "campus_id": campus_id},
		"name",
		order_by="start_date desc",
	)


def resolve_school_year_id(
	class_id: Optional[str] = None,
	campus_id: Optional[str] = None,
	explicit_school_year_id: Optional[str] = None,
) -> Optional[str]:
	"""
	Xác định school_year_id khi tạo/sửa phân công.
	Ưu tiên: explicit > từ lớp > năm active của campus.
	"""
	if explicit_school_year_id and frappe.db.exists("SIS School Year", explicit_school_year_id):
		return explicit_school_year_id

	if class_id:
		class_year = frappe.db.get_value("SIS Class", class_id, "school_year_id")
		if class_year:
			return class_year

	if campus_id:
		return get_active_school_year_for_campus(campus_id)

	return None


def validate_school_year_matches_class(
	school_year_id: str,
	class_id: Optional[str],
) -> None:
	"""Dữ liệu mới: school_year_id phải khớp năm học của lớp."""
	if not class_id or not school_year_id:
		return
	class_year = frappe.db.get_value("SIS Class", class_id, "school_year_id")
	if class_year and class_year != school_year_id:
		frappe.throw(
			_("School year does not match the selected class ({0} vs {1})").format(
				school_year_id, class_year
			)
		)


def fix_subject_linkages(campus_id: str):
    """
    Fix SIS Subjects that don't have actual_subject_id linkages.
    
    Tìm các SIS Subject chưa có actual_subject_id và tự động link
    với Actual Subject có cùng title_vn.
    
    Args:
        campus_id: Campus ID to fix subjects for
        
    Returns:
        int: Number of subjects fixed
    """
    try:
        # Find SIS Subjects without actual_subject_id
        unlinked_subjects = frappe.get_all(
            "SIS Subject",
            fields=["name", "title"],
            filters={
                "campus_id": campus_id,
                "actual_subject_id": ["is", "not set"]
            }
        )
        
        fixed_count = 0
        for subj in unlinked_subjects:
            # Try to find matching Actual Subject
            title_to_match = subj.get("title")
            if not title_to_match:
                continue
                
            actual_subjects = frappe.get_all(
                "SIS Actual Subject",
                fields=["name"],
                filters={
                    "title_vn": title_to_match,
                    "campus_id": campus_id
                }
            )
            
            if actual_subjects:
                try:
                    frappe.db.set_value("SIS Subject", subj.name, "actual_subject_id", actual_subjects[0].name)
                    fixed_count += 1
                except Exception:
                    continue
        
        if fixed_count > 0:
            frappe.db.commit()
            frappe.logger().info(f"SUBJECT LINKAGE FIX - Fixed {fixed_count} SIS Subjects with actual_subject_id linkages")
        
        return fixed_count
            
    except Exception as e:
        frappe.logger().error(f"Error fixing subject linkages: {str(e)}")
        return 0

