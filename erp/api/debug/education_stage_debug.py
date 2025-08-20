# Copyright (c) 2024, Wellspring International School and contributors  
# For license information, please see license.txt

import frappe
from frappe import _


@frappe.whitelist(allow_guest=False)
def debug_education_stages():
    """Debug SIS Education Stage data"""
    try:
        result = {
            "success": True,
            "debug_info": {}
        }
        
        # 1. Get all education stages with campus_id
        all_stages = frappe.get_all(
            "SIS Education Stage",
            fields=["name", "title_vn", "title_en", "short_title", "campus_id"],
            limit=20
        )
        result["debug_info"]["all_education_stages"] = all_stages
        
        # 2. Get unique campus_ids in education stages
        campus_ids = frappe.db.sql("""
            SELECT DISTINCT campus_id, COUNT(*) as count
            FROM `tabSIS Education Stage`
            GROUP BY campus_id
            ORDER BY count DESC
        """, as_dict=True)
        result["debug_info"]["campus_id_distribution"] = campus_ids
        
        # 3. Total count
        total_count = frappe.db.count("SIS Education Stage")
        result["debug_info"]["total_education_stages"] = total_count
        
        # 4. Check if any stages have empty/null campus_id
        empty_campus_count = frappe.db.sql("""
            SELECT COUNT(*) as count
            FROM `tabSIS Education Stage`
            WHERE campus_id IS NULL OR campus_id = ''
        """, as_dict=True)[0]["count"]
        result["debug_info"]["stages_with_empty_campus_id"] = empty_campus_count
        
        return result
        
    except Exception as e:
        frappe.logger().error(f"Error in debug_education_stages: {str(e)}")
        import traceback
        frappe.logger().error(traceback.format_exc())
        
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }
