# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import nowdate, get_datetime
import json
from erp.utils.campus_utils import get_current_campus_from_context, get_campus_id_from_user_roles
from erp.utils.jwt_auth import jwt_auth_middleware


@frappe.whitelist(allow_guest=False)
def get_all_education_stages():
    """Get all education stages with basic information - SIMPLE VERSION"""
    try:
        # Try JWT authentication first
        jwt_auth_middleware()
        # Get current user's campus information from roles
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            # Fallback to default if no campus found
            campus_id = "campus-1"
            frappe.logger().warning(f"No campus found for user {frappe.session.user}, using default: {campus_id}")
        
        filters = {"campus_id": campus_id}
            
        education_stages = frappe.get_all(
            "SIS Education Stage",
            fields=[
                "name",
                "title_vn",
                "title_en", 
                "short_title",
                "campus_id",
                "creation",
                "modified"
            ],
            filters=filters,
            order_by="title_vn asc"
        )
        
        return {
            "success": True,
            "data": education_stages,
            "total_count": len(education_stages),
            "message": "Education stages fetched successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error fetching education stages: {str(e)}")
        return {
            "success": False,
            "data": [],
            "message": f"Error fetching education stages: {str(e)}",
            "error": str(e)
        }


@frappe.whitelist(allow_guest=False)
def get_education_stage_by_id(stage_id):
    """Get education stage details by ID"""
    try:
        if not stage_id:
            return {
                "success": False,
                "message": "Stage ID is required"
            }
            
        stage = frappe.get_doc("SIS Education Stage", stage_id)
        
        if not stage:
            return {
                "success": False,
                "message": "Education stage not found"
            }
            
        return {
            "success": True,
            "data": {
                "education_stage": stage.as_dict()
            },
            "message": "Education stage fetched successfully"
        }
        
    except frappe.DoesNotExistError:
        return {
            "success": False,
            "message": "Education stage not found"
        }
    except Exception as e:
        frappe.log_error(f"Error fetching education stage {stage_id}: {str(e)}")
        return {
            "success": False,
            "message": "Error fetching education stage",
            "error": str(e)
        }


@frappe.whitelist(allow_guest=False)
def create_education_stage():
    """Create a new education stage - SIMPLE VERSION"""
    try:
        # Try JWT authentication first
        jwt_auth_middleware()
        # Get data from request
        data = frappe.local.form_dict
        
        frappe.logger().info(f"Received data for create_education_stage: {data}")
        
        # Validate required fields
        required_fields = ["title_vn", "title_en", "short_title"]
        for field in required_fields:
            if not data.get(field):
                frappe.throw(_(f"Field '{field}' is required"))
        
        # Get campus from user roles or form data
        campus_id = data.get("campus_id")
        if not campus_id:
            campus_id = get_current_campus_from_context()
            if not campus_id:
                # Fallback to default if no campus found
                campus_id = "campus-1"
                frappe.logger().warning(f"No campus found for user {frappe.session.user}, using default: {campus_id}")
        
        frappe.logger().info(f"Using campus_id: {campus_id}")
        
        # Check if short_title already exists for this campus
        existing_stage = frappe.db.exists("SIS Education Stage", {
            "short_title": data.get("short_title"),
            "campus_id": campus_id
        })
        
        if existing_stage:
            frappe.throw(_("Ký hiệu đã tồn tại cho trường học này"))
        
        # Create new education stage
        stage_doc = frappe.get_doc({
            "doctype": "SIS Education Stage",
            "title_vn": data.get("title_vn"),
            "title_en": data.get("title_en"),
            "short_title": data.get("short_title"),
            "campus_id": campus_id
        })
        
        stage_doc.insert(ignore_permissions=True)
        
        frappe.logger().info(f"Created education stage: {stage_doc.name}")
        
        return {
            "success": True,
            "data": stage_doc.as_dict(),
            "message": "Education stage created successfully"
        }
        
    except Exception as e:
        frappe.logger().error(f"Error creating education stage: {str(e)}")
        return {
            "success": False,
            "message": f"Error creating education stage: {str(e)}",
            "error": str(e)
        }


@frappe.whitelist(allow_guest=False)
def update_education_stage(stage_id):
    """Update an existing education stage"""
    try:
        if not stage_id:
            return {
                "success": False,
                "message": "Stage ID is required"
            }
        
        # Get data from request
        data = frappe.local.form_dict
        
        # Get existing stage
        stage_doc = frappe.get_doc("SIS Education Stage", stage_id)
        
        if not stage_doc:
            return {
                "success": False,
                "message": "Education stage not found"
            }
        
        # Check if short_title already exists for this campus (excluding current stage)
        if data.get("short_title") and data.get("short_title") != stage_doc.short_title:
            existing_stage = frappe.db.exists("SIS Education Stage", {
                "short_title": data.get("short_title"),
                "campus_id": stage_doc.campus_id,
                "name": ["!=", stage_id]
            })
            
            if existing_stage:
                return {
                    "success": False,
                    "message": "Ký hiệu đã tồn tại cho trường học này"
                }
        
        # Update fields
        updatable_fields = ["title_vn", "title_en", "short_title"]
        for field in updatable_fields:
            if field in data:
                setattr(stage_doc, field, data.get(field))
        
        stage_doc.save(ignore_permissions=True)
        
        return {
            "success": True,
            "data": {
                "education_stage": stage_doc.as_dict()
            },
            "message": "Education stage updated successfully"
        }
        
    except frappe.DoesNotExistError:
        return {
            "success": False,
            "message": "Education stage not found"
        }
    except Exception as e:
        frappe.log_error(f"Error updating education stage {stage_id}: {str(e)}")
        return {
            "success": False,
            "message": "Error updating education stage",
            "error": str(e)
        }


@frappe.whitelist(allow_guest=False)
def delete_education_stage(stage_id):
    """Delete an education stage"""
    try:
        if not stage_id:
            return {
                "success": False,
                "message": "Stage ID is required"
            }
        
        # Check if stage exists
        stage_doc = frappe.get_doc("SIS Education Stage", stage_id)
        
        if not stage_doc:
            return {
                "success": False,
                "message": "Education stage not found"
            }
        
        # TODO: Add validation to check if stage is being used by other documents
        # before deleting
        
        # Delete the stage
        frappe.delete_doc("SIS Education Stage", stage_id, ignore_permissions=True)
        
        return {
            "success": True,
            "message": "Education stage deleted successfully"
        }
        
    except frappe.DoesNotExistError:
        return {
            "success": False,
            "message": "Education stage not found"
        }
    except Exception as e:
        frappe.log_error(f"Error deleting education stage {stage_id}: {str(e)}")
        return {
            "success": False,
            "message": "Error deleting education stage",
            "error": str(e)
        }


@frappe.whitelist(allow_guest=False)
def check_short_title_availability(short_title, stage_id=None):
    """Check if a short title is available for the current campus"""
    try:
        if not short_title:
            return {
                "success": False,
                "message": "Short title is required"
            }
        
        # Get current user's campus from roles
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            return {
                "success": False,
                "message": "User campus not found in roles"
            }
        
        filters = {
            "short_title": short_title,
            "campus_id": campus_id
        }
        
        # Exclude current stage if updating
        if stage_id:
            filters["name"] = ["!=", stage_id]
        
        existing_stage = frappe.db.exists("SIS Education Stage", filters)
        
        return {
            "success": True,
            "data": {
                "is_available": not bool(existing_stage),
                "short_title": short_title
            },
            "message": "Short title availability checked"
        }
        
    except Exception as e:
        frappe.log_error(f"Error checking short title availability: {str(e)}")
        return {
            "success": False,
            "message": "Error checking short title availability",
            "error": str(e)
        }
