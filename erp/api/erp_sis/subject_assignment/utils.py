# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

"""
Utility functions for Subject Assignment module
"""

from typing import Optional

import frappe
from frappe import _


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

