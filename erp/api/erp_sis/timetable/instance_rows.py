# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

"""
Timetable Instance Row Operations

Handles CRUD operations for individual timetable instance rows.
These endpoints allow direct editing of specific periods in the timetable.
"""

import frappe
from frappe import _
from erp.utils.api_response import (
    error_response,
    forbidden_response,
    not_found_response,
    single_item_response,
    validation_error_response,
)
from .helpers import _get_request_arg


@frappe.whitelist(allow_guest=False)
def get_instance_row_details(row_id: str = None):
    """Get detailed information for a specific timetable instance row for editing"""
    try:
        row_id = row_id or _get_request_arg("row_id")
        if not row_id:
            return validation_error_response("Validation failed", {"row_id": ["Row ID is required"]})

        # Get the instance row
        row = frappe.get_doc("SIS Timetable Instance Row", row_id)

        # Get related data for dropdowns/edit options
        subjects = frappe.get_all(
            "SIS Subject",
            fields=["name", "title"],
            filters={"is_active": 1},
            order_by="title asc"
        )

        # Get available teachers for this period/class combination
        teachers = frappe.get_all(
            "SIS Teacher",
            fields=["name", "user_id", "first_name", "last_name", "full_name"],
            filters={"status": "Active"},
            order_by="full_name asc"
        )

        # Get available rooms (if room assignment is supported)
        rooms = frappe.get_all(
            "SIS Room",
            fields=["name", "room_name", "capacity"],
            filters={"is_active": 1},
            order_by="room_name asc"
        ) if frappe.db.has_table("SIS Room") else []

        # Get instance information
        instance = frappe.get_doc("SIS Timetable Instance", row.parent)

        # Check if instance is locked
        is_locked = instance.get("is_locked", False)

        result_data = {
            "row": {
                "name": row.name,
                "day_of_week": row.day_of_week,
                "timetable_column_id": row.timetable_column_id,
                "subject_id": row.subject_id,
                "subject_title": row.subject_id and frappe.db.get_value("SIS Subject", row.subject_id, "title"),
                "teacher_1_id": row.teacher_1_id,
                "teacher_2_id": row.teacher_2_id,
                "parent": row.parent,
                "parent_timetable_instance": row.parent_timetable_instance
            },
            "instance": {
                "name": instance.name,
                "class_id": instance.class_id,
                "timetable_id": instance.timetable_id,
                "start_date": str(instance.start_date),
                "end_date": str(instance.end_date),
                "is_locked": is_locked
            },
            "options": {
                "subjects": subjects,
                "teachers": teachers,
                "rooms": rooms
            }
        }

        return single_item_response(result_data, "Instance row details fetched successfully")

    except frappe.DoesNotExistError:
        return not_found_response("Instance row not found")
    except Exception as e:

        return error_response(f"Error fetching instance row details: {str(e)}")


@frappe.whitelist(allow_guest=False, methods=["GET", "POST", "PUT"])
def update_instance_row(row_id: str = None, subject_id: str = None, teacher_1_id: str = None,
                       teacher_2_id: str = None, room_id: str = None):
    """Update a specific timetable instance row"""

    try:
        # Get parameters
        row_id = row_id or _get_request_arg("row_id")
        subject_id = subject_id or _get_request_arg("subject_id")
        teacher_1_id = teacher_1_id or _get_request_arg("teacher_1_id")
        teacher_2_id = teacher_2_id or _get_request_arg("teacher_2_id")
        room_id = room_id or _get_request_arg("room_id")

        if not row_id:
            return validation_error_response("Validation failed", {"row_id": ["Row ID is required"]})

        # Get the instance row (ignore permissions to bypass framework-level checks)
        try:
            row = frappe.get_doc("SIS Timetable Instance Row", row_id, ignore_permissions=True)

            # Store old teacher values BEFORE any updates (get from database, not from current object)
            old_teacher_1_id = frappe.db.get_value("SIS Timetable Instance Row", row_id, "teacher_1_id")
            old_teacher_2_id = frappe.db.get_value("SIS Timetable Instance Row", row_id, "teacher_2_id")

        except Exception as e:
            raise

        # Check if parent instance is locked
        try:
            instance = frappe.get_doc("SIS Timetable Instance", row.parent, ignore_permissions=True)
        except Exception as e:
            raise

        if instance.get("is_locked"):
            return validation_error_response("Validation failed", {
                "instance_locked": ["Cannot edit a locked instance"]
            })

        # Temporarily bypass campus check for debugging
        # if user_campus and user_campus != instance.campus_id:
        #     return forbidden_response("Access denied: Campus mismatch")

        # Validate subject exists (SIS Subject doesn't have is_active field)
        if subject_id:
            # SIS Subject doctype doesn't have is_active field, so just check if exists
            subject_exists = frappe.db.exists("SIS Subject", {"name": subject_id})

            if not subject_exists:
                return validation_error_response("Validation failed", {
                    "subject_id": ["Subject does not exist"]
                })

        # Validate teachers exist (SIS Teacher doesn't have status field)
        for teacher_id in [teacher_1_id, teacher_2_id]:
            if teacher_id:
                teacher_exists = frappe.db.exists("SIS Teacher", {"name": teacher_id})

                if not teacher_exists:
                    return validation_error_response("Validation failed", {
                        "teacher_id": [f"Teacher does not exist: {teacher_id}"]
                    })

        # Check for teacher conflicts if teachers are assigned
        if teacher_1_id or teacher_2_id:
            conflict_check = _check_teacher_conflicts(
                [tid for tid in [teacher_1_id, teacher_2_id] if tid],
                row.day_of_week,
                row.timetable_column_id,
                instance.start_date,
                instance.end_date,
                row.name  # Exclude current row from conflict check
            )

            if conflict_check.get("has_conflict"):
                return validation_error_response("Validation failed", {
                    "teacher_conflict": conflict_check["conflicts"]
                })

        # Update the row
        update_data = {}
        if subject_id is not None:
            update_data["subject_id"] = subject_id
        if teacher_1_id is not None:
            update_data["teacher_1_id"] = teacher_1_id
        if teacher_2_id is not None:
            update_data["teacher_2_id"] = teacher_2_id
        if room_id is not None and frappe.db.has_table("SIS Room"):
            update_data["room_id"] = room_id

        if update_data:
            for field, value in update_data.items():
                setattr(row, field, value)
            row.save(ignore_permissions=True)
            frappe.db.commit()

            # Note: Không sync related timetables để cell edit chỉ ảnh hưởng đúng 1 cell
            # _sync_related_timetables(row, instance, old_teacher_1_id, old_teacher_2_id)

        result_data = {
            "row_id": row.name,
            "updated_fields": list(update_data.keys()),
            "instance_id": instance.name,
            "class_id": instance.class_id
        }

        return single_item_response(result_data, "Instance row updated successfully")

    except frappe.DoesNotExistError:
        return not_found_response("Instance row not found")
    except frappe.PermissionError as e:
        return forbidden_response(f"Permission denied: {str(e)}")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Error updating instance row: {str(e)}")


def _check_teacher_conflicts(teacher_ids: list, day_of_week: str, timetable_column_id: str,
                           start_date, end_date, exclude_row_id: str = None):
    """Check for teacher scheduling conflicts"""
    try:
        conflicts = []

        for teacher_id in teacher_ids:
            # Find other instances where this teacher is assigned at the same time
            conflict_rows = frappe.get_all(
                "SIS Timetable Instance Row",
                fields=["name", "parent", "day_of_week", "timetable_column_id"],
                filters={
                    "day_of_week": day_of_week,
                    "timetable_column_id": timetable_column_id,
                    "teacher_1_id": teacher_id
                }
            )

            # Also check teacher_2_id
            conflict_rows_2 = frappe.get_all(
                "SIS Timetable Instance Row",
                fields=["name", "parent", "day_of_week", "timetable_column_id"],
                filters={
                    "day_of_week": day_of_week,
                    "timetable_column_id": timetable_column_id,
                    "teacher_2_id": teacher_id
                }
            )

            conflict_rows.extend(conflict_rows_2)

            # Exclude current row if updating
            if exclude_row_id:
                conflict_rows = [r for r in conflict_rows if r["name"] != exclude_row_id]

            if conflict_rows:
                # Get instance and class info for conflicts
                for conflict in conflict_rows:
                    instance = frappe.get_doc("SIS Timetable Instance", conflict["parent"])
                    conflicts.append({
                        "teacher_id": teacher_id,
                        "conflicting_class": instance.class_id,
                        "day_of_week": day_of_week,
                        "period": timetable_column_id
                    })

        return {
            "has_conflict": len(conflicts) > 0,
            "conflicts": conflicts
        }

    except Exception as e:

        return {"has_conflict": False, "conflicts": []}


def _sync_related_timetables(row, instance, old_teacher_1_id=None, old_teacher_2_id=None):
    """
    Sync changes to related teacher and student timetables.
    
    Note: Currently disabled in update_instance_row() to ensure cell edits
    only affect the specific cell, not related timetables.
    """
    try:
        # Get current teachers from row
        new_teacher_1_id = getattr(row, 'teacher_1_id', None)
        new_teacher_2_id = getattr(row, 'teacher_2_id', None)

        # 1. Remove old teacher timetable entries
        teachers_to_remove = []
        if old_teacher_1_id and old_teacher_1_id != new_teacher_1_id:
            teachers_to_remove.append(old_teacher_1_id)
        if old_teacher_2_id and old_teacher_2_id != new_teacher_2_id:
            teachers_to_remove.append(old_teacher_2_id)

        # Debug: Log what we're doing
        if teachers_to_remove:
            frappe.logger().info(f"DEBUG: Removing teacher timetable entries for teachers: {teachers_to_remove}")
            frappe.logger().info(f"DEBUG: Old teachers: teacher_1={old_teacher_1_id}, teacher_2={old_teacher_2_id}")
            frappe.logger().info(f"DEBUG: New teachers: teacher_1={new_teacher_1_id}, teacher_2={new_teacher_2_id}")

        for teacher_id in teachers_to_remove:
            if teacher_id:
                # Comprehensive deletion strategy to handle both manual and Excel-imported entries

                # Strategy 1: Exact match with all filters (for manual edits)
                existing_entries = frappe.get_all(
                    "SIS Teacher Timetable",
                    filters={
                        "teacher_id": teacher_id,
                        "timetable_instance_id": instance.name,
                        "day_of_week": row.day_of_week,
                        "timetable_column_id": row.timetable_column_id,
                        "class_id": instance.class_id
                    }
                )

                # Strategy 2: If no exact match, get all entries for this teacher in this instance
                # This handles Excel-imported entries that might have different date formats
                if len(existing_entries) == 0:
                    instance_entries = frappe.get_all(
                        "SIS Teacher Timetable",
                        filters={
                            "teacher_id": teacher_id,
                            "timetable_instance_id": instance.name,
                            "class_id": instance.class_id  # Ensure same class
                        }
                    )

                    # Filter by day_of_week and timetable_column_id in memory
                    for entry in instance_entries:
                        if (entry.get("day_of_week") == row.day_of_week and
                            entry.get("timetable_column_id") == row.timetable_column_id):
                            existing_entries.append(entry)

                # Strategy 3: Fallback - find any entries for this teacher on this day/week
                # This handles edge cases where entries might be created with different logic
                if len(existing_entries) == 0:
                    # Get entries by teacher and day_of_week only, then filter by instance
                    day_entries = frappe.get_all(
                        "SIS Teacher Timetable",
                        filters={
                            "teacher_id": teacher_id,
                            "day_of_week": row.day_of_week,
                            "class_id": instance.class_id
                        }
                    )

                    # Filter by timetable_instance_id to ensure we're only deleting from current instance
                    for entry in day_entries:
                        if entry.get("timetable_instance_id") == instance.name:
                            existing_entries.append(entry)

                # Strategy 4: Last resort - delete ALL entries for this teacher in this instance
                # This ensures no orphaned entries remain, especially for Excel-imported data
                if len(existing_entries) == 0:
                    all_instance_entries = frappe.get_all(
                        "SIS Teacher Timetable",
                        filters={
                            "teacher_id": teacher_id,
                            "timetable_instance_id": instance.name
                        }
                    )
                    existing_entries.extend(all_instance_entries)

                # Delete all found entries
                for entry in existing_entries:
                    try:
                        frappe.delete_doc("SIS Teacher Timetable", entry.name, ignore_permissions=True)
                    except Exception:
                        pass  # Ignore delete errors for individual entries

        # 2. Create new teacher timetable entries
        teachers_to_add = []
        if new_teacher_1_id:
            teachers_to_add.append(new_teacher_1_id)
        if new_teacher_2_id:
            teachers_to_add.append(new_teacher_2_id)

        for teacher_id in teachers_to_add:
            if teacher_id:
                # Check if entry already exists with comprehensive filters
                existing_entries = frappe.get_all(
                    "SIS Teacher Timetable",
                    filters={
                        "teacher_id": teacher_id,
                        "timetable_instance_id": instance.name,
                        "day_of_week": row.day_of_week,
                        "timetable_column_id": row.timetable_column_id,
                        "class_id": instance.class_id
                    },
                    limit=1
                )

                if len(existing_entries) > 0:
                    continue  # Entry already exists, skip creation

                try:
                    # Create new teacher timetable entry
                    teacher_timetable = frappe.get_doc({
                        "doctype": "SIS Teacher Timetable",
                        "teacher_id": teacher_id,
                        "timetable_instance_id": instance.name,
                        "day_of_week": row.day_of_week,
                        "timetable_column_id": row.timetable_column_id,
                        "subject_id": getattr(row, 'subject_id', None),
                        "class_id": instance.class_id,
                        "room_id": getattr(row, 'room_id', None),
                        "date": getattr(row, 'date', None)
                    })

                    teacher_timetable.insert(ignore_permissions=True)

                except Exception:
                    pass  # Continue if teacher entry creation fails

    except Exception:
        pass  # Continue if sync fails

