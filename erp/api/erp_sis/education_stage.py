# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import nowdate, get_datetime
import json


@frappe.whitelist()
def get_all_education_stages():
    """Get all education stages with basic information"""
    try:
        # Get current user's campus information
        user = frappe.session.user
        campus_name = frappe.db.get_value("User", user, "campus")
        
        filters = {}
        if campus_name:
            filters["campus"] = campus_name
            
        education_stages = frappe.get_all(
            "SIS Education Stage",
            fields=[
                "name",
                "stage_name_vn",
                "stage_name_en", 
                "stage_code",
                "campus",
                "is_active",
                "creation",
                "modified"
            ],
            filters=filters,
            order_by="stage_name_vn asc"
        )
        
        return {
            "success": True,
            "data": {
                "education_stages": education_stages,
                "total_count": len(education_stages)
            },
            "message": "Education stages fetched successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error fetching education stages: {str(e)}")
        return {
            "success": False,
            "message": "Error fetching education stages",
            "error": str(e)
        }


@frappe.whitelist()
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


@frappe.whitelist()
def create_education_stage():
    """Create a new education stage"""
    try:
        # Get data from request
        data = frappe.local.form_dict
        
        # Validate required fields - updated field names
        required_fields = ["title_vn", "title_en", "short_title"]
        for field in required_fields:
            if not data.get(field):
                return {
                    "success": False,
                    "message": f"Field '{field}' is required"
                }
        
        # Get current user's campus from campus_id if provided, else from user profile
        campus_id = data.get("campus_id")
        if not campus_id:
            user = frappe.session.user
            campus_id = frappe.db.get_value("User", user, "campus")
        
        if not campus_id:
            return {
                "success": False,
                "message": "Campus not found"
            }
        
        # Check if short_title already exists for this campus
        existing_stage = frappe.db.exists("SIS Education Stage", {
            "short_title": data.get("short_title"),
            "campus_id": campus_id
        })
        
        if existing_stage:
            return {
                "success": False,
                "message": "Ký hiệu đã tồn tại cho trường học này"
            }
        
        # Create new education stage
        stage_doc = frappe.new_doc("SIS Education Stage")
        stage_doc.update({
            "title_vn": data.get("title_vn"),
            "title_en": data.get("title_en"),
            "short_title": data.get("short_title"),
            "campus_id": campus_id
        })
        
        stage_doc.insert(ignore_permissions=True)
        
        return {
            "success": True,
            "data": {
                "education_stage": stage_doc.as_dict()
            },
            "message": "Education stage created successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error creating education stage: {str(e)}")
        return {
            "success": False,
            "message": "Error creating education stage",
            "error": str(e)
        }


@frappe.whitelist()
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
        
        # Check if stage code already exists for this campus (excluding current stage)
        if data.get("stage_code") and data.get("stage_code") != stage_doc.stage_code:
            existing_stage = frappe.db.exists("SIS Education Stage", {
                "stage_code": data.get("stage_code"),
                "campus": stage_doc.campus,
                "name": ["!=", stage_id]
            })
            
            if existing_stage:
                return {
                    "success": False,
                    "message": "Ký hiệu đã tồn tại cho trường học này"
                }
        
        # Update fields
        updatable_fields = ["stage_name_vn", "stage_name_en", "stage_code", "is_active"]
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


@frappe.whitelist()
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


@frappe.whitelist()
def check_stage_code_availability(stage_code, stage_id=None):
    """Check if a stage code is available for the current campus"""
    try:
        if not stage_code:
            return {
                "success": False,
                "message": "Stage code is required"
            }
        
        # Get current user's campus
        user = frappe.session.user
        campus_name = frappe.db.get_value("User", user, "campus")
        
        if not campus_name:
            return {
                "success": False,
                "message": "User campus not found"
            }
        
        filters = {
            "stage_code": stage_code,
            "campus": campus_name
        }
        
        # Exclude current stage if updating
        if stage_id:
            filters["name"] = ["!=", stage_id]
        
        existing_stage = frappe.db.exists("SIS Education Stage", filters)
        
        return {
            "success": True,
            "data": {
                "is_available": not bool(existing_stage),
                "stage_code": stage_code
            },
            "message": "Stage code availability checked"
        }
        
    except Exception as e:
        frappe.log_error(f"Error checking stage code availability: {str(e)}")
        return {
            "success": False,
            "message": "Error checking stage code availability",
            "error": str(e)
        }
