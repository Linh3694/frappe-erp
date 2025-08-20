# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
import json


@frappe.whitelist()
def debug_403_error():
    """Debug lỗi 403 Education Stage API"""
    result = {
        "debug_info": {},
        "errors": [],
        "success": True
    }
    
    try:
        # Set user
        user = "linh.nguyenhai@wellspring.edu.vn"
        frappe.set_user(user)
        result["debug_info"]["user"] = user
        
        # 1. Check user roles
        user_roles = frappe.get_roles(user)
        result["debug_info"]["user_roles"] = user_roles
        
        # 2. Check doctype permissions
        doctype = "SIS Education Stage"
        
        has_read = frappe.has_permission(doctype, "read")
        has_create = frappe.has_permission(doctype, "create")
        has_write = frappe.has_permission(doctype, "write")
        
        result["debug_info"]["permissions"] = {
            "read": has_read,
            "create": has_create,
            "write": has_write
        }
        
        # 3. Check doctype definition
        try:
            doc_meta = frappe.get_meta(doctype)
            permissions = []
            for perm in doc_meta.permissions:
                permissions.append({
                    "role": perm.role,
                    "create": perm.create,
                    "read": perm.read,
                    "write": perm.write
                })
            result["debug_info"]["doctype_permissions"] = permissions
        except Exception as e:
            result["errors"].append(f"Error getting doctype meta: {str(e)}")
        
        # 4. Test campus utils
        try:
            from erp.utils.campus_utils import get_current_campus_from_context, get_campus_id_from_user_roles
            result["debug_info"]["campus_utils_import"] = "OK"
            
            campus_id = get_campus_id_from_user_roles(user)
            result["debug_info"]["campus_id_from_roles"] = campus_id
            
        except Exception as e:
            result["errors"].append(f"Campus utils error: {str(e)}")
            import traceback
            result["errors"].append(traceback.format_exc())
        
        # 5. Test API function directly
        try:
            from erp.api.erp_sis.education_stage import get_all_education_stages
            api_result = get_all_education_stages()
            result["debug_info"]["get_all_education_stages"] = api_result
            
        except Exception as e:
            result["errors"].append(f"get_all_education_stages error: {str(e)}")
            import traceback
            result["errors"].append(traceback.format_exc())
            
        # 6. Test create function
        try:
            # Set form data
            frappe.local.form_dict = {
                'title_vn': 'Test Debug',
                'title_en': 'Test Debug EN', 
                'short_title': 'DEBUG'
            }
            
            from erp.api.erp_sis.education_stage import create_education_stage
            create_result = create_education_stage()
            result["debug_info"]["create_education_stage"] = create_result
            
        except Exception as e:
            result["errors"].append(f"create_education_stage error: {str(e)}")
            import traceback
            result["errors"].append(traceback.format_exc())
            
        if result["errors"]:
            result["success"] = False
            
        return result
        
    except Exception as e:
        return {
            "success": False,
            "errors": [f"MAIN ERROR: {str(e)}"],
            "debug_info": result.get("debug_info", {})
        }


@frappe.whitelist()
def quick_perm_check():
    """Quick permission check"""
    try:
        user = "linh.nguyenhai@wellspring.edu.vn"
        frappe.set_user(user)
        
        doctype = "SIS Education Stage"
        has_perm = frappe.has_permission(doctype, "create")
        
        return {
            "success": True,
            "user": user,
            "doctype": doctype,
            "has_create_permission": has_perm,
            "user_roles": frappe.get_roles(user)
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }
