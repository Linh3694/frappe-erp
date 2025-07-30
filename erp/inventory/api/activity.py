# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import cint
import json


@frappe.whitelist()
def get_activities(entity_type, entity_id, page=1, limit=20):
    """Get activities for an entity - equivalent to getActivities in old system"""
    try:
        page = cint(page) or 1
        limit = cint(limit) or 20
        start = (page - 1) * limit
        
        activities = frappe.get_list(
            "ERP IT Inventory Activity",
            filters={
                "entity_type": entity_type,
                "entity_id": entity_id
            },
            fields=[
                "name", "activity_type", "description", "details", 
                "activity_date", "updated_by"
            ],
            start=start,
            limit=limit,
            order_by="activity_date desc"
        )
        
        # Get user full names
        for activity in activities:
            if activity.updated_by:
                activity.updated_by_name = frappe.get_value("User", activity.updated_by, "full_name")
        
        # Get total count
        total_count = frappe.db.count(
            "ERP IT Inventory Activity",
            filters={
                "entity_type": entity_type,
                "entity_id": entity_id
            }
        )
        
        return {
            "activities": activities,
            "pagination": {
                "current_page": page,
                "total_pages": (total_count + limit - 1) // limit,
                "total_items": total_count,
                "items_per_page": limit
            }
        }
        
    except Exception as e:
        frappe.log_error(f"Error in get_activities: {str(e)}", "Activity API Error")
        frappe.throw(_("Error fetching activities: {0}").format(str(e)))


@frappe.whitelist()
def add_activity(entity_type, entity_id, activity_type, description, details=None):
    """Add new activity - equivalent to addActivity in old system"""
    try:
        # Validation
        if not entity_type or not entity_id:
            frappe.throw(_("Entity Type and Entity ID are required"))
            
        valid_types = ["repair", "update", "assign", "revoke", "create", "delete"]
        if activity_type not in valid_types:
            frappe.throw(_("Activity type must be one of: {0}").format(", ".join(valid_types)))
            
        if not description or not description.strip():
            frappe.throw(_("Description is required"))
        
        # Create activity
        activity = frappe.get_doc({
            "doctype": "ERP IT Inventory Activity",
            "entity_type": entity_type,
            "entity_id": entity_id,
            "activity_type": activity_type,
            "description": description.strip(),
            "details": details.strip() if details else "",
            "updated_by": frappe.session.user
        })
        
        activity.insert()
        
        return {
            "status": "success",
            "message": _("Activity added successfully"),
            "activity": activity.as_dict()
        }
        
    except Exception as e:
        frappe.log_error(f"Error in add_activity: {str(e)}", "Activity API Error")
        frappe.throw(_("Error adding activity: {0}").format(str(e)))


@frappe.whitelist()
def update_activity(activity_id, description=None, details=None, activity_date=None):
    """Update activity - equivalent to updateActivity in old system"""
    try:
        activity = frappe.get_doc("ERP IT Inventory Activity", activity_id)
        
        if description:
            activity.description = description
        if details is not None:  # Allow empty string
            activity.details = details
        if activity_date:
            activity.activity_date = activity_date
            
        activity.save()
        
        return {
            "status": "success",
            "message": _("Activity updated successfully"),
            "activity": activity.as_dict()
        }
        
    except Exception as e:
        frappe.log_error(f"Error in update_activity: {str(e)}", "Activity API Error")
        frappe.throw(_("Error updating activity: {0}").format(str(e)))


@frappe.whitelist()
def delete_activity(activity_id):
    """Delete activity - equivalent to deleteActivity in old system"""
    try:
        frappe.delete_doc("ERP IT Inventory Activity", activity_id)
        
        return {
            "status": "success",
            "message": _("Activity deleted successfully")
        }
        
    except Exception as e:
        frappe.log_error(f"Error in delete_activity: {str(e)}", "Activity API Error")
        frappe.throw(_("Error deleting activity: {0}").format(str(e)))


@frappe.whitelist()
def get_activity_stats(entity_type=None, days=30):
    """Get activity statistics"""
    try:
        from frappe.utils import add_days, nowdate
        
        filters = {}
        if entity_type:
            filters["entity_type"] = entity_type
            
        # Activities in last N days
        if days:
            date_filter = add_days(nowdate(), -cint(days))
            filters["activity_date"] = [">=", date_filter]
        
        # Total activities
        total_activities = frappe.db.count("ERP IT Inventory Activity", filters)
        
        # Activities by type
        activity_types = frappe.db.sql("""
            SELECT activity_type, COUNT(*) as count
            FROM `tabERP IT Inventory Activity`
            WHERE {conditions}
            GROUP BY activity_type
            ORDER BY count DESC
        """.format(
            conditions=" AND ".join([f"{k} = '{v}'" for k, v in filters.items()]) if filters else "1=1"
        ), as_dict=True)
        
        # Recent activities
        recent_activities = frappe.get_list(
            "ERP IT Inventory Activity",
            filters=filters,
            fields=[
                "name", "entity_type", "entity_id", "activity_type", 
                "description", "activity_date", "updated_by"
            ],
            limit=10,
            order_by="activity_date desc"
        )
        
        # Get user names for recent activities
        for activity in recent_activities:
            if activity.updated_by:
                activity.updated_by_name = frappe.get_value("User", activity.updated_by, "full_name")
        
        return {
            "total_activities": total_activities,
            "by_type": {item.activity_type: item.count for item in activity_types},
            "recent_activities": recent_activities,
            "period_days": days
        }
        
    except Exception as e:
        frappe.log_error(f"Error in get_activity_stats: {str(e)}", "Activity API Error")
        frappe.throw(_("Error fetching activity statistics: {0}").format(str(e)))


@frappe.whitelist()
def get_entity_activity_summary(entity_type, entity_id):
    """Get activity summary for a specific entity"""
    try:
        # Total activities
        total = frappe.db.count("ERP IT Inventory Activity", {
            "entity_type": entity_type,
            "entity_id": entity_id
        })
        
        # Activities by type
        by_type = frappe.db.sql("""
            SELECT activity_type, COUNT(*) as count
            FROM `tabERP IT Inventory Activity`
            WHERE entity_type = %s AND entity_id = %s
            GROUP BY activity_type
        """, (entity_type, entity_id), as_dict=True)
        
        # Latest activity
        latest = frappe.get_list(
            "ERP IT Inventory Activity",
            filters={
                "entity_type": entity_type,
                "entity_id": entity_id
            },
            fields=["activity_type", "description", "activity_date", "updated_by"],
            limit=1,
            order_by="activity_date desc"
        )
        
        latest_activity = None
        if latest:
            latest_activity = latest[0]
            latest_activity.updated_by_name = frappe.get_value("User", latest_activity.updated_by, "full_name")
        
        return {
            "total_activities": total,
            "by_type": {item.activity_type: item.count for item in by_type},
            "latest_activity": latest_activity
        }
        
    except Exception as e:
        frappe.log_error(f"Error in get_entity_activity_summary: {str(e)}", "Activity API Error")
        frappe.throw(_("Error fetching activity summary: {0}").format(str(e)))