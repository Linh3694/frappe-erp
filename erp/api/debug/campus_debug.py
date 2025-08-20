# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from erp.utils.campus_utils import get_campus_id_from_user_roles, find_campus_id_by_title, get_current_campus_from_context


@frappe.whitelist(allow_guest=False)
def debug_campus_logic():
    """Debug campus logic để tìm lỗi"""
    try:
        user_email = frappe.session.user
        result = {
            "success": True,
            "user_email": user_email,
            "debug_info": {}
        }
        
        # 1. Get user roles
        user_roles = frappe.get_roles(user_email)
        result["debug_info"]["user_roles"] = user_roles
        
        # 2. Find campus roles
        campus_roles = [role for role in user_roles if role.startswith("Campus ")]
        result["debug_info"]["campus_roles"] = campus_roles
        
        if campus_roles:
            campus_role = campus_roles[0]
            campus_title = campus_role.replace("Campus ", "")
            result["debug_info"]["extracted_campus_title"] = campus_title
            
            # 3. Try to find campus by title
            campus_id = find_campus_id_by_title(campus_title)
            result["debug_info"]["found_campus_id"] = campus_id
            
            # 4. Check all SIS Campus records
            all_campuses = frappe.get_all(
                "SIS Campus", 
                fields=["name", "title_vn", "title_en"],
                limit=20
            )
            result["debug_info"]["all_sis_campuses"] = all_campuses
            
            # 5. Get campus via utils function
            util_campus_id = get_campus_id_from_user_roles(user_email)
            result["debug_info"]["util_campus_id"] = util_campus_id
            
            # 6. Get current campus from context
            context_campus_id = get_current_campus_from_context()
            result["debug_info"]["context_campus_id"] = context_campus_id
        
        # 7. Check SIS Education Stage data with different campus_ids
        test_campus_ids = ["campus-1", "campus-2", "wellspring-95-ai-mo", None]
        stage_counts = {}
        
        for test_id in test_campus_ids:
            if test_id:
                count = frappe.db.count("SIS Education Stage", {"campus_id": test_id})
            else:
                count = frappe.db.count("SIS Education Stage")
            stage_counts[str(test_id)] = count
            
        result["debug_info"]["education_stage_counts_by_campus"] = stage_counts
        
        return result
        
    except Exception as e:
        frappe.logger().error(f"Error in debug_campus_logic: {str(e)}")
        import traceback
        frappe.logger().error(traceback.format_exc())
        
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }
