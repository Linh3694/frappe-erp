# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

"""
Timetable Date-Specific Overrides

Handles PRIORITY 3 operations - date-specific timetable overrides for individual cell edits.
These overrides allow temporary changes to specific dates without affecting the pattern rows.
"""

import frappe
from frappe import _
from erp.utils.campus_utils import get_current_campus_from_context
from erp.utils.api_response import (
    error_response,
    not_found_response,
    single_item_response,
    validation_error_response,
)
from .helpers import _get_request_arg
from erp.api.erp_sis.utils.cache_utils import clear_teacher_dashboard_cache


@frappe.whitelist(allow_guest=False, methods=["GET", "POST", "PUT"])
def create_or_update_timetable_override(date: str = None, timetable_column_id: str = None,
                                       target_type: str = None, target_id: str = None,
                                       subject_id: str = None, teacher_1_id: str = None,
                                       teacher_2_id: str = None, room_id: str = None,
                                       override_id: str = None):
    """
    PRIORITY 3: Create or update a date-specific timetable override for individual cell edits.
    
    This handles direct changes on WeeklyGrid cells and only affects that specific date/period.
    Does NOT modify timetable instance rows - those are handled by Priority 2 (Subject Assignment sync).
    """
    try:
        # Get parameters from request
        date = date or _get_request_arg("date")
        timetable_column_id = timetable_column_id or _get_request_arg("timetable_column_id")
        target_type = target_type or _get_request_arg("target_type")
        target_id = target_id or _get_request_arg("target_id")
        subject_id = subject_id or _get_request_arg("subject_id")
        teacher_1_id = teacher_1_id or _get_request_arg("teacher_1_id")
        teacher_2_id = teacher_2_id or _get_request_arg("teacher_2_id")
        room_id = room_id or _get_request_arg("room_id")
        override_id = override_id or _get_request_arg("override_id")
        
        
        # Convert "none" strings to None
        if teacher_1_id == "none" or teacher_1_id == "":
            teacher_1_id = None
        if teacher_2_id == "none" or teacher_2_id == "":
            teacher_2_id = None
        if subject_id == "none" or subject_id == "":
            subject_id = None
        if room_id == "none" or room_id == "":
            room_id = None

        # Validate required fields
        if not all([date, timetable_column_id, target_type, target_id]):
            return validation_error_response("Validation failed", {
                "required_fields": ["date", "timetable_column_id", "target_type", "target_id"]
            })

        # Validate target_type
        if target_type not in ["Student", "Teacher", "Class"]:
            return validation_error_response("Validation failed", {
                "target_type": ["Target type must be Student, Teacher, or Class"]
            })

        # Get campus from user context for permission checking
        campus_id = get_current_campus_from_context()
        if not campus_id:
            campus_id = "campus-1"  # Default fallback

        # Validate target exists before proceeding
        if target_type == "Class":
            if not frappe.db.exists("SIS Class", target_id):
                return not_found_response(f"Class {target_id} not found")
        elif target_type == "Teacher":
            if not frappe.db.exists("SIS Teacher", target_id):
                return not_found_response(f"Teacher {target_id} not found")
        elif target_type == "Student":
            if not frappe.db.exists("SIS Student", target_id):
                return not_found_response(f"Student {target_id} not found")

        # Create a custom table for date-specific overrides to avoid SIS Event dependency
        # We'll create this as a simple storage without going through Frappe doctype system
        virtual_event = f"manual-edit-{frappe.generate_hash()[:8]}"
        
        # Create custom override table if it doesn't exist
        try:
            frappe.db.sql("""
                CREATE TABLE IF NOT EXISTS `tabTimetable_Date_Override` (
                    `name` varchar(140) NOT NULL,
                    `date` date NOT NULL,
                    `timetable_column_id` varchar(140) NOT NULL,
                    `target_type` varchar(50) NOT NULL,
                    `target_id` varchar(140) NOT NULL,
                    `subject_id` varchar(140) NULL,
                    `teacher_1_id` varchar(140) NULL,
                    `teacher_2_id` varchar(140) NULL,
                    `room_id` varchar(140) NULL,
                    `override_type` varchar(50) DEFAULT 'replace',
                    `created_by` varchar(140) NOT NULL,
                    `creation` datetime NOT NULL,
                    `modified` datetime NOT NULL,
                    `modified_by` varchar(140) NOT NULL,
                    PRIMARY KEY (`name`),
                    UNIQUE KEY `unique_override` (`date`, `timetable_column_id`, `target_type`, `target_id`)
                )
            """)
        except Exception as create_error:
            # Table might already exist, which is fine
            pass

        # Check if override already exists in custom table
        existing_override = frappe.db.sql("""
            SELECT name FROM `tabTimetable_Date_Override`
            WHERE date = %s AND timetable_column_id = %s AND target_type = %s AND target_id = %s
            LIMIT 1
        """, (date, timetable_column_id, target_type, target_id), as_dict=True)
        
        if existing_override:
            # Update existing override
            override_name = existing_override[0].name
            frappe.db.sql("""
                UPDATE `tabTimetable_Date_Override`
                SET subject_id = %s, teacher_1_id = %s, teacher_2_id = %s, room_id = %s,
                    override_type = %s, modified = %s, modified_by = %s
                WHERE name = %s
            """, (subject_id, teacher_1_id, teacher_2_id, room_id, 'replace',
                  frappe.utils.now(), frappe.session.user, override_name))
            
            action = "updated"
        else:
            # Create new override
            override_name = f"OVERRIDE-{frappe.generate_hash()[:8]}"
            frappe.db.sql("""
                INSERT INTO `tabTimetable_Date_Override`
                (name, date, timetable_column_id, target_type, target_id, subject_id, teacher_1_id, teacher_2_id, room_id, override_type, created_by, creation, modified, modified_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (override_name, date, timetable_column_id, target_type, target_id, subject_id, teacher_1_id, teacher_2_id, room_id, 'replace',
                  frappe.session.user, frappe.utils.now(), frappe.utils.now(), frappe.session.user))
            
            action = "created"
        
        frappe.db.commit()
        
        # ⚡ INVALIDATE CACHE: Clear Redis cache for affected timetables
        # This ensures frontend gets fresh data after override
        clear_teacher_dashboard_cache()
        
        # ⚡ SYNC MATERIALIZED VIEW: Update Teacher Timetable for override
        try:
            # Sync Teacher Timetable for the affected date/teachers
            _sync_teacher_timetable_for_override(
                date=date,
                timetable_column_id=timetable_column_id,
                target_type=target_type,
                target_id=target_id,
                old_teacher_1_id=None,  # We don't track old values
                old_teacher_2_id=None,
                new_teacher_1_id=teacher_1_id,
                new_teacher_2_id=teacher_2_id,
                subject_id=subject_id,
                room_id=room_id
            )
            frappe.logger().info(f"✅ Synced Teacher Timetable for override on {date}")
        except Exception as sync_error:
            # Don't fail the override if sync fails - log warning only
            frappe.logger().warning(f"⚠️ Teacher Timetable sync failed for override: {str(sync_error)}")
            frappe.log_error(f"Teacher Timetable sync failed: {str(sync_error)}", "Override Sync Warning")
        
        # Get subject and teacher names for response
        subject_title = ""
        if subject_id:
            subject_title = frappe.db.get_value("SIS Subject", subject_id, "title") or ""
            
        teacher_names = []
        if teacher_1_id:
            try:
                teacher1 = frappe.get_doc("SIS Teacher", teacher_1_id)
                if teacher1.user_id:
                    user1 = frappe.get_doc("User", teacher1.user_id)
                    display_name1 = user1.full_name or f"{user1.first_name or ''} {user1.last_name or ''}".strip()
                    if display_name1:
                        teacher_names.append(display_name1)
            except Exception:
                pass  # Skip if teacher not found
        if teacher_2_id:
            try:
                teacher2 = frappe.get_doc("SIS Teacher", teacher_2_id)
                if teacher2.user_id:
                    user2 = frappe.get_doc("User", teacher2.user_id)
                    display_name2 = user2.full_name or f"{user2.first_name or ''} {user2.last_name or ''}".strip()
                    if display_name2:
                        teacher_names.append(display_name2)
            except Exception:
                pass  # Skip if teacher not found
        
        return single_item_response({
            "name": override_name,
            "date": date,
            "timetable_column_id": timetable_column_id,
            "target_type": target_type,
            "target_id": target_id,
            "subject_id": subject_id,
            "subject_title": subject_title,
            "teacher_1_id": teacher_1_id,
            "teacher_2_id": teacher_2_id,
            "teacher_names": ", ".join(teacher_names),
            "room_id": room_id,
            "override_type": "replace",
            "action": action
        }, f"Timetable override {action} successfully for {date}")

    except Exception as e:
        frappe.log_error(f"Error creating/updating timetable override: {str(e)}")
        return error_response(f"Error creating timetable override: {str(e)}")




@frappe.whitelist(allow_guest=False, methods=["DELETE"])
def delete_timetable_override(override_id: str = None):
    """Delete a specific timetable override"""
    try:
        override_id = override_id or _get_request_arg("override_id")
        
        if not override_id:
            return validation_error_response("Validation failed", {
                "override_id": ["Override ID is required"]
            })
            
        # ⚡ Get override details BEFORE deletion for sync
        override_details = frappe.db.sql("""
            SELECT date, timetable_column_id, target_type, target_id, teacher_1_id, teacher_2_id
            FROM `tabTimetable_Date_Override`
            WHERE name = %s AND created_by = %s
        """, (override_id, frappe.session.user), as_dict=True)
        
        if not override_details:
            return not_found_response("Timetable override not found or access denied")
            
        details = override_details[0]
            
        # Delete from custom table
        deleted_count = frappe.db.sql("""
            DELETE FROM `tabTimetable_Date_Override`
            WHERE name = %s AND created_by = %s
        """, (override_id, frappe.session.user))
        
        if deleted_count:
            frappe.db.commit()
            
            # ⚡ CLEAR CACHE: Invalidate teacher dashboard cache after override deletion
            clear_teacher_dashboard_cache()
            
            # ⚡ SYNC MATERIALIZED VIEW: Clear Teacher Timetable entries for deleted override
            try:
                _sync_teacher_timetable_for_override(
                    date=str(details.date),
                    timetable_column_id=details.timetable_column_id,
                    target_type=details.target_type,
                    target_id=details.target_id,
                    old_teacher_1_id=details.teacher_1_id,
                    old_teacher_2_id=details.teacher_2_id,
                    new_teacher_1_id=None,  # Deleting means no new teachers
                    new_teacher_2_id=None,
                    subject_id=None,
                    room_id=None
                )
                frappe.logger().info(f"✅ Synced Teacher Timetable after override deletion")
            except Exception as sync_error:
                frappe.logger().warning(f"⚠️ Teacher Timetable sync failed after override deletion: {str(sync_error)}")
            
            return single_item_response({"deleted": True}, "Timetable override deleted successfully")
        else:
            return not_found_response("Timetable override not found or access denied")
            
    except Exception as e:
        frappe.log_error(f"Error deleting timetable override: {str(e)}")
        return error_response(f"Error deleting timetable override: {str(e)}")


def _sync_teacher_timetable_for_override(date: str, timetable_column_id: str, target_type: str, target_id: str,
                                        old_teacher_1_id: str = None, old_teacher_2_id: str = None,
                                        new_teacher_1_id: str = None, new_teacher_2_id: str = None,
                                        subject_id: str = None, room_id: str = None):
    """
    PRIORITY 3.5: Sync Teacher Timetable entries for date-specific cell overrides
    
    This ensures attendance/class log systems recognize the teacher change for specific date.
    """
    try:
        if target_type != "Class":
            # Only handle class-based overrides for now
            return
            
        class_id = target_id
        
        # Parse date to get day of week
        from datetime import datetime
        date_obj = datetime.strptime(date, '%Y-%m-%d')
        day_of_week_map = {0: 'mon', 1: 'tue', 2: 'wed', 3: 'thu', 4: 'fri', 5: 'sat', 6: 'sun'}
        day_of_week = day_of_week_map.get(date_obj.weekday())
        
        if not day_of_week:
            return
            
        # 1. Find existing Teacher Timetable entries for this date/period/class
        existing_entries = frappe.get_all(
            "SIS Teacher Timetable",
            fields=["name", "teacher_id", "timetable_instance_id"],
            filters={
                "class_id": class_id,
                "day_of_week": day_of_week,
                "timetable_column_id": timetable_column_id,
                "date": date  # Specific date filter
            }
        )
        
        # 2. Remove existing entries (will be replaced with override teachers)
        old_teachers_removed = []
        for entry in existing_entries:
            old_teachers_removed.append(entry.teacher_id)
            try:
                frappe.delete_doc("SIS Teacher Timetable", entry.name, ignore_permissions=True)
            except Exception as delete_error:
                frappe.log_error(f"Error removing teacher timetable entry: {str(delete_error)}")
        
        # 3. Create new Teacher Timetable entries for override teachers
        new_teachers = []
        if new_teacher_1_id and new_teacher_1_id != "none":
            new_teachers.append(new_teacher_1_id)
        if new_teacher_2_id and new_teacher_2_id != "none":
            new_teachers.append(new_teacher_2_id)
            
        # Find timetable instance for this class/date
        timetable_instance_id = None
        try:
            instances = frappe.get_all(
                "SIS Timetable Instance",
                fields=["name"],
                filters={
                    "class_id": class_id,
                    "start_date": ["<=", date],
                    "end_date": [">=", date]
                },
                limit=1
            )
            if instances:
                timetable_instance_id = instances[0].name
        except Exception:
            pass
            
        if not timetable_instance_id:
            return
            
        # Create new entries
        for teacher_id in new_teachers:
            if not teacher_id:
                continue
                
            try:
                teacher_timetable = frappe.get_doc({
                    "doctype": "SIS Teacher Timetable",
                    "teacher_id": teacher_id,
                    "timetable_instance_id": timetable_instance_id,
                    "class_id": class_id,
                    "day_of_week": day_of_week,
                    "timetable_column_id": timetable_column_id,
                    "subject_id": subject_id,
                    "room_id": room_id,
                    "date": date  # Specific date for override
                })
                
                teacher_timetable.insert(ignore_permissions=True)
                
            except Exception as create_error:
                frappe.log_error(f"Error creating teacher timetable override entry: {str(create_error)}")
                
    except Exception as e:
        frappe.log_error(f"Error syncing teacher timetable for override: {str(e)}")

