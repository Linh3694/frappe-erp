# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

"""
Utility functions for Subject Assignment module
"""

import frappe


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

