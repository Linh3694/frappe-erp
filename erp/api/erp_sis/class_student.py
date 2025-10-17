# Copyright (c) 2024, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime
from erp.utils.api_response import (
    success_response, error_response, paginated_response,
    single_item_response, validation_error_response,
    not_found_response, forbidden_response
)


def _clear_class_log_student_link(class_student_id):
    """
    Clear class_student_id link in SIS Class Log Student records.
    This prevents "cannot delete because linked" error when unassigning students.
    
    Args:
        class_student_id: The SIS Class Student ID to clear links for
    
    Returns:
        int: Number of records updated
    """
    try:
        result = frappe.db.sql("""
            UPDATE `tabSIS Class Log Student`
            SET class_student_id = NULL
            WHERE class_student_id = %s
        """, (class_student_id,))
        count = result if result else 0
        if count > 0:
            frappe.logger().info(f"Cleared {count} Class Log Student links for {class_student_id}")
        return count
    except Exception as e:
        frappe.logger().warning(f"Failed to clear class_student_id in Class Log Student: {str(e)}")
        return 0


def sync_student_subjects_for_class_change(student_id, new_class_id, school_year_id, campus_id, old_class_id=None):
    """
    Sync SIS Student Subject records when a student changes class.
    This ensures Student Subject table is always in sync with Class Student table.
    
    This function:
    1. Updates existing Student Subject records to new class_id
    2. Creates NEW Student Subject records for subjects in new class timetable
    3. This ensures report cards have all subjects from the new class
    
    Args:
        student_id: Student ID
        new_class_id: New class ID the student is moving to
        school_year_id: School year ID
        campus_id: Campus ID
        old_class_id: Optional old class ID (if known, for optimization)
    
    Returns:
        dict: {"updated_count": int, "created_count": int, "logs": list}
    """
    logs = []
    updated_count = 0
    created_count = 0
    
    try:
        # Step 1: Update existing Student Subject records from old class to new class
        if old_class_id:
            # We know the old class, update directly
            result = frappe.db.sql("""
                UPDATE `tabSIS Student Subject`
                SET class_id = %s, modified = NOW()
                WHERE student_id = %s
                AND school_year_id = %s
                AND campus_id = %s
                AND class_id = %s
            """, (new_class_id, student_id, school_year_id, campus_id, old_class_id))
            updated_count = result
            logs.append(f"✓ Updated {updated_count} existing Student Subject records to class {new_class_id}")
        else:
            # Don't know old class, update all mismatched records for this student
            result = frappe.db.sql("""
                UPDATE `tabSIS Student Subject`
                SET class_id = %s, modified = NOW()
                WHERE student_id = %s
                AND school_year_id = %s
                AND campus_id = %s
                AND class_id != %s
            """, (new_class_id, student_id, school_year_id, campus_id, new_class_id))
            updated_count = result
            logs.append(f"✓ Synced {updated_count} existing Student Subject records to class {new_class_id}")
        
        # 🆕 Step 2: Create NEW Student Subject records for subjects in new class timetable
        # This ensures the student has Subject records for ALL subjects in the new class
        try:
            # Get subjects from timetable of new class
            timetable_instances = frappe.get_all(
                "SIS Timetable Instance",
                fields=["name"],
                filters={
                    "campus_id": campus_id,
                    "class_id": new_class_id
                }
            )
            
            if timetable_instances:
                instance_ids = [t["name"] for t in timetable_instances]
                
                # Get distinct subjects from timetable rows
                timetable_subjects = frappe.db.sql("""
                    SELECT DISTINCT subject_id
                    FROM `tabSIS Timetable Instance Row`
                    WHERE parent IN %s
                    AND subject_id IS NOT NULL
                    AND subject_id != ''
                """, [instance_ids], as_dict=True)
                
                subject_ids = [s["subject_id"] for s in timetable_subjects if s.get("subject_id")]
                logs.append(f"Found {len(subject_ids)} subjects in timetable for class {new_class_id}")
                
                # For each subject, ensure Student Subject record exists
                for subject_id in subject_ids:
                    try:
                        # Get actual_subject_id from SIS Subject
                        actual_subject_id = frappe.db.get_value("SIS Subject", subject_id, "actual_subject_id")
                        
                        if not actual_subject_id:
                            logs.append(f"⚠️ Subject {subject_id} has no actual_subject_id, skipping")
                            continue
                        
                        # Check if Student Subject record already exists
                        existing = frappe.db.exists(
                            "SIS Student Subject",
                            {
                                "campus_id": campus_id,
                                "student_id": student_id,
                                "class_id": new_class_id,
                                "subject_id": subject_id,
                                "school_year_id": school_year_id
                            }
                        )
                        
                        if not existing:
                            # Create new Student Subject record
                            doc = frappe.get_doc({
                                "doctype": "SIS Student Subject",
                                "campus_id": campus_id,
                                "student_id": student_id,
                                "class_id": new_class_id,
                                "subject_id": subject_id,
                                "actual_subject_id": actual_subject_id,
                                "school_year_id": school_year_id
                            })
                            doc.insert(ignore_permissions=True)
                            created_count += 1
                        
                    except Exception as subj_err:
                        logs.append(f"⚠️ Error processing subject {subject_id}: {str(subj_err)}")
                        continue
                
                if created_count > 0:
                    logs.append(f"✓ Created {created_count} NEW Student Subject records for class {new_class_id} subjects")
                else:
                    logs.append(f"✓ All subjects already exist in Student Subject")
                    
            else:
                logs.append(f"⚠️ No timetable found for class {new_class_id}")
                
        except Exception as timetable_err:
            logs.append(f"⚠️ Error creating new Student Subject records: {str(timetable_err)}")
            frappe.log_error(f"Error creating Student Subject from timetable: {str(timetable_err)}")
        
        # Step 3: Verify sync was successful
        mismatched = frappe.db.sql("""
            SELECT COUNT(*) as count
            FROM `tabSIS Student Subject`
            WHERE student_id = %s
            AND school_year_id = %s
            AND campus_id = %s
            AND class_id != %s
        """, (student_id, school_year_id, campus_id, new_class_id), as_dict=True)
        
        if mismatched and mismatched[0]["count"] > 0:
            logs.append(f"⚠️ Warning: {mismatched[0]['count']} Student Subject records still have mismatched class_id")
        else:
            logs.append("✓ All Student Subject records are in sync with Class Student")
        
        frappe.logger().info(
            f"Synced Student Subject for student {student_id} to class {new_class_id}: "
            f"updated={updated_count}, created={created_count}"
        )
        
        return {
            "updated_count": updated_count,
            "created_count": created_count,
            "logs": logs,
            "success": True
        }
        
    except Exception as e:
        error_msg = f"Error syncing Student Subject for student {student_id}: {str(e)}"
        logs.append(f"✗ {error_msg}")
        frappe.log_error(error_msg, "Student Subject Sync Error")
        return {
            "updated_count": updated_count,
            "created_count": created_count,
            "logs": logs,
            "success": False,
            "error": str(e)
        }


@frappe.whitelist(allow_guest=False)
def get_all_class_students(page=1, limit=20, school_year_id=None, class_id=None):
    """Get all class students with pagination and filters"""
    try:
        page = int(page)
        limit = int(limit)

        # Get parameters from request args if not provided as function parameters
        if not school_year_id:
            school_year_id = frappe.request.args.get("school_year_id")
        if not class_id:
            class_id = frappe.request.args.get("class_id")

        # Build filters
        filters = {}
        if school_year_id:
            filters['school_year_id'] = school_year_id
        if class_id:
            filters['class_id'] = class_id

        # Get campus filter from context
        from erp.utils.campus_utils import get_current_campus_from_context
        campus_id = get_current_campus_from_context()
        if campus_id:
            filters['campus_id'] = campus_id



        # Calculate offset
        offset = (page - 1) * limit

        # Get class students
        class_students = frappe.get_all(
            "SIS Class Student",
            filters=filters,
            fields=[
                "name", "class_id", "student_id", "school_year_id",
                "class_type", "campus_id", "creation", "modified"
            ],
            order_by="creation desc",
            limit_start=offset,
            limit_page_length=limit
        )


        
        # Get total count
        total_count = frappe.db.count("SIS Class Student", filters=filters)
        
        # Ensure total_count is not None to avoid arithmetic errors
        if total_count is None:
            total_count = 0
        
        # Calculate pagination
        total_pages = max(1, (total_count + limit - 1) // limit)

        return paginated_response(
            data=class_students,
            current_page=page,
            total_count=total_count,
            per_page=limit,
            message="Class students fetched successfully"
        )
        
    except Exception as e:
        frappe.log_error(f"Error getting class students: {str(e)}")
        return error_response(
            message="Error fetching class students",
            code="FETCH_CLASS_STUDENTS_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def get_all_class_students_no_pagination(school_year_id=None, class_id=None):
    """Get ALL class students without pagination - similar to get_all_students endpoint"""
    try:
        # Get parameters from request args if not provided as function parameters
        if not school_year_id:
            school_year_id = frappe.request.args.get("school_year_id")
        if not class_id:
            class_id = frappe.request.args.get("class_id")

        # Build filters
        filters = {}
        if school_year_id:
            filters['school_year_id'] = school_year_id
        if class_id:
            filters['class_id'] = class_id

        # Get campus filter from context
        from erp.utils.campus_utils import get_current_campus_from_context
        campus_id = get_current_campus_from_context()
        if campus_id:
            filters['campus_id'] = campus_id

        frappe.logger().info(f"get_all_class_students_no_pagination called with filters: {filters}")

        # Get ALL class students - NO PAGINATION!
        class_students = frappe.get_all(
            "SIS Class Student",
            filters=filters,
            fields=[
                "name", "class_id", "student_id", "school_year_id",
                "class_type", "campus_id", "creation", "modified"
            ],
            order_by="creation desc"
            # NO limit_start or limit_page_length = fetch ALL records
        )

        frappe.logger().info(f"Fetched {len(class_students)} class students without pagination")

        # Return all records in standard success format (no pagination info)
        return success_response(
            data=class_students,
            message=f"Fetched all {len(class_students)} class students successfully"
        )
        
    except Exception as e:
        frappe.log_error(f"Error getting all class students: {str(e)}")
        return error_response(
            message="Error fetching all class students",
            code="FETCH_ALL_CLASS_STUDENTS_ERROR"
        )




@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def assign_student(class_id=None, student_id=None, school_year_id=None, class_type="regular"):
    """Assign a student to a class"""
    try:
        # Get parameters from both form_dict and request args (handle query string params)
        if not class_id:
            class_id = frappe.local.form_dict.get("class_id") or frappe.form_dict.get("class_id")
        if not student_id:
            student_id = frappe.local.form_dict.get("student_id") or frappe.form_dict.get("student_id")
        if not school_year_id:
            school_year_id = frappe.local.form_dict.get("school_year_id") or frappe.form_dict.get("school_year_id")
        if not class_type:
            class_type = frappe.local.form_dict.get("class_type", "regular") or frappe.form_dict.get("class_type", "regular")

        # Also try to get from request args (query parameters)
        if not class_id:
            class_id = frappe.request.args.get("class_id")
        if not student_id:
            student_id = frappe.request.args.get("student_id")
        if not school_year_id:
            school_year_id = frappe.request.args.get("school_year_id")
        if not class_type:
            class_type = frappe.request.args.get("class_type", "regular")

        # Fallback to JSON data if form_dict is empty
        if not class_id and hasattr(frappe, 'request') and frappe.request.data:
            try:
                import json
                json_data = json.loads(frappe.request.data.decode('utf-8'))
                class_id = json_data.get('class_id') or class_id
                student_id = json_data.get('student_id') or student_id
                school_year_id = json_data.get('school_year_id') or school_year_id
                class_type = json_data.get('class_type') or class_type or 'regular'
            except:
                pass


        
        # Normalize and validate parameters
        if not class_id or not student_id or not school_year_id:
            return validation_error_response(
                message="Missing required parameters",
                errors={
                    "class_id": ["Required"] if not class_id else [],
                    "student_id": ["Required"] if not student_id else [],
                    "school_year_id": ["Required"] if not school_year_id else []
                }
            )
        class_type = (class_type or "regular").strip().lower()
        if class_type not in ["regular", "mixed"]:
            class_type = "regular"
        
        # Get campus from context
        from erp.utils.campus_utils import get_current_campus_from_context
        campus_id = get_current_campus_from_context()
        if not campus_id:
            campus_id = "campus-1"  # Default fallback
        
        # RULES ENFORCEMENT
        # 1) Prevent duplicate assignment to the same class in same year
        if frappe.db.exists("SIS Class Student", {
            "class_id": class_id,
            "student_id": student_id,
            "school_year_id": school_year_id,
        }):
            # Already in this class -> return success idempotently
            existing_doc = frappe.get_all(
                "SIS Class Student",
                filters={
                    "class_id": class_id,
                    "student_id": student_id,
                    "school_year_id": school_year_id,
                },
                fields=["name", "class_id", "student_id", "school_year_id", "class_type", "campus_id"],
                limit=1,
            )
            return single_item_response(
                data=existing_doc[0] if existing_doc else {
                    "class_id": class_id,
                    "student_id": student_id,
                    "school_year_id": school_year_id,
                    "class_type": class_type,
                    "campus_id": campus_id,
                },
                message="Student already assigned to this class"
            )

        if class_type == "regular":
            # 2) Regular: ensure ONLY ONE regular class per student per school year (campus-aware)
            existing_regular = frappe.get_all(
                "SIS Class Student",
                filters={
                    "student_id": student_id,
                    "school_year_id": school_year_id,
                    "class_type": "regular",
                },
                fields=["name", "class_id"],
                order_by="creation asc",
            )
            if existing_regular:
                # If same class -> already handled above
                # Otherwise migrate the oldest regular record to the new class
                target_name = existing_regular[0]["name"]
                old_class_id = existing_regular[0]["class_id"]
                try:
                    frappe.db.set_value("SIS Class Student", target_name, {
                        "class_id": class_id,
                        "campus_id": campus_id,
                    }, update_modified=True)
                    
                    # 🆕 SYNC STUDENT SUBJECT: Update all Student Subject records to new class
                    sync_result = sync_student_subjects_for_class_change(
                        student_id=student_id,
                        new_class_id=class_id,
                        school_year_id=school_year_id,
                        campus_id=campus_id,
                        old_class_id=old_class_id
                    )
                    
                    # Log sync results
                    if sync_result.get("success"):
                        frappe.logger().info(
                            f"Student {student_id} moved from {old_class_id} to {class_id}. "
                            f"Updated {sync_result.get('updated_count', 0)} records, "
                            f"Created {sync_result.get('created_count', 0)} new subject records."
                        )
                    else:
                        frappe.logger().warning(
                            f"Student {student_id} moved to {class_id} but Student Subject sync had issues: "
                            f"{sync_result.get('error', 'Unknown error')}"
                        )
                    
                    # Deduplicate: remove any extra regular records beyond the first
                    for dup in existing_regular[1:]:
                        try:
                            frappe.delete_doc("SIS Class Student", dup["name"])
                        except Exception:
                            pass
                    frappe.db.commit()
                    updated = frappe.get_doc("SIS Class Student", target_name)
                    
                    # Build informative message
                    sync_msg_parts = []
                    if sync_result.get('updated_count', 0) > 0:
                        sync_msg_parts.append(f"updated {sync_result.get('updated_count', 0)} existing")
                    if sync_result.get('created_count', 0) > 0:
                        sync_msg_parts.append(f"created {sync_result.get('created_count', 0)} new")
                    sync_msg = ", ".join(sync_msg_parts) if sync_msg_parts else "no changes needed"
                    
                    return single_item_response(
                        data={
                            "name": updated.name,
                            "class_id": updated.class_id,
                            "student_id": updated.student_id,
                            "school_year_id": updated.school_year_id,
                            "class_type": updated.class_type,
                            "campus_id": updated.campus_id,
                            "sync_info": sync_result  # Include sync info in response
                        },
                        message=f"Student moved to new class. Subject records: {sync_msg}."
                    )
                except Exception as move_err:
                    frappe.logger().error(f"Failed to move regular class assignment: {str(move_err)}")
                    frappe.db.rollback()
                    return error_response(
                        message="Failed to move student to new regular class",
                        code="MOVE_REGULAR_ERROR",
                    )

        # 3) Create new assignment (works for mixed, or regular when none existed)
        class_student = frappe.get_doc({
            "doctype": "SIS Class Student",
            "class_id": class_id,
            "student_id": student_id,
            "school_year_id": school_year_id,
            "class_type": class_type,
            "campus_id": campus_id,
        })
        class_student.insert()
        
        # 🆕 SYNC STUDENT SUBJECT: Ensure any existing Student Subject records are synced to this class
        sync_result = sync_student_subjects_for_class_change(
            student_id=student_id,
            new_class_id=class_id,
            school_year_id=school_year_id,
            campus_id=campus_id,
            old_class_id=None  # Don't know old class for new assignment
        )
        
        # Log sync results
        updated = sync_result.get("updated_count", 0)
        created = sync_result.get("created_count", 0)
        
        if updated > 0 or created > 0:
            frappe.logger().info(
                f"Student {student_id} assigned to {class_id}. "
                f"Updated {updated} records, Created {created} new subject records."
            )
        else:
            # ⚠️ WARNING: No Student Subject records created/updated
            frappe.logger().warning(
                f"⚠️ Student {student_id} assigned to {class_id} but NO Student Subject records were created/updated. "
                f"This may cause empty report cards! Check if timetable exists for this class. "
                f"Logs: {sync_result.get('logs', [])}"
            )
        
        frappe.db.commit()

        # Build informative message
        sync_msg_parts = []
        if updated > 0:
            sync_msg_parts.append(f"updated {updated} existing")
        if created > 0:
            sync_msg_parts.append(f"created {created} new")
        
        if not sync_msg_parts:
            # No records created/updated - add warning
            sync_msg = "⚠️ no subject records created - report cards may be empty"
        else:
            sync_msg = ", ".join(sync_msg_parts)

        return single_item_response(
            data={
                "name": class_student.name,
                "class_id": class_student.class_id,
                "student_id": class_student.student_id,
                "school_year_id": class_student.school_year_id,
                "class_type": class_student.class_type,
                "campus_id": class_student.campus_id,
                "sync_info": sync_result  # Include sync info in response
            },
            message=f"Student assigned to class. Subject records: {sync_msg}."
        )
        
    except Exception as e:
        frappe.log_error(f"Error assigning student to class: {str(e)}")
        frappe.db.rollback()
        return error_response(
            message="Error assigning student to class",
            code="ASSIGN_STUDENT_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def unassign_student(name=None, class_id=None, student_id=None, school_year_id=None, class_type=None, student_code=None, class_name=None, force=False, reassign_to_class_id=None, reassign_to_class_name=None, reassign_to_latest=False):
    """Remove a student from a class"""
    try:
        # Get parameters from form_dict / request args
        form = frappe.local.form_dict or {}
        args = getattr(frappe, 'request', None) and getattr(frappe.request, 'args', None)
        if not name:
            name = form.get('name') or (args.get('name') if args else None)
        if not class_id:
            class_id = form.get('class_id') or (args.get('class_id') if args else None)
        if not class_name:
            class_name = form.get('class_name') or (args.get('class_name') if args else None)
        if not student_id:
            student_id = form.get('student_id') or (args.get('student_id') if args else None)
        if not student_code:
            student_code = form.get('student_code') or (args.get('student_code') if args else None)
        if not school_year_id:
            school_year_id = form.get('school_year_id') or (args.get('school_year_id') if args else None)
        if not class_type:
            class_type = form.get('class_type') or (args.get('class_type') if args else None)

        # Parse force flag from inputs if provided as string/number
        if isinstance(force, str):
            force = force.lower() in ("1", "true", "yes", "y")
        elif not force:
            raw_force = form.get('force') or (args.get('force') if args else None)
            if isinstance(raw_force, str):
                force = raw_force.lower() in ("1", "true", "yes", "y")
            else:
                force = bool(raw_force)

        # Parse reassignment flags/targets
        if not reassign_to_class_id:
            reassign_to_class_id = form.get('reassign_to_class_id') or (args.get('reassign_to_class_id') if args else None)
        if not reassign_to_class_name:
            reassign_to_class_name = form.get('reassign_to_class_name') or (args.get('reassign_to_class_name') if args else None)
        if isinstance(reassign_to_latest, str):
            reassign_to_latest = reassign_to_latest.lower() in ("1", "true", "yes", "y")
        elif not reassign_to_latest:
            raw_latest = form.get('reassign_to_latest') or (args.get('reassign_to_latest') if args else None)
            if isinstance(raw_latest, str):
                reassign_to_latest = raw_latest.lower() in ("1", "true", "yes", "y")
            else:
                reassign_to_latest = bool(raw_latest)

        # Fallback: parse JSON body if sent as application/json
        try:
            if hasattr(frappe, 'request') and getattr(frappe.request, 'data', None):
                import json
                body = json.loads(frappe.request.data.decode('utf-8')) if isinstance(frappe.request.data, (bytes, bytearray)) else {}
                name = name or body.get('name')
                class_id = class_id or body.get('class_id')
                class_name = class_name or body.get('class_name')
                student_id = student_id or body.get('student_id')
                student_code = student_code or body.get('student_code')
                school_year_id = school_year_id or body.get('school_year_id')
                class_type = class_type or body.get('class_type')
                if 'force' in body and not isinstance(force, bool):
                    try:
                        force = str(body.get('force')).lower() in ("1", "true", "yes", "y")
                    except Exception:
                        pass
                if not reassign_to_class_id:
                    reassign_to_class_id = body.get('reassign_to_class_id')
                if not reassign_to_class_name:
                    reassign_to_class_name = body.get('reassign_to_class_name')
                if 'reassign_to_latest' in body and not isinstance(reassign_to_latest, bool):
                    try:
                        reassign_to_latest = str(body.get('reassign_to_latest')).lower() in ("1", "true", "yes", "y")
                    except Exception:
                        pass
        except Exception:
            pass

        # Resolve student_id by student_code if needed
        if not student_id and student_code:
            try:
                stu = frappe.get_all("CRM Student", filters={"student_code": student_code}, fields=["name"], limit=1)
                if stu:
                    student_id = stu[0].name
            except Exception:
                pass

        # Resolve class_id by class_name if needed (by name or title)
        if not class_id and class_name:
            try:
                cls = frappe.get_all("SIS Class", filters={"name": class_name}, fields=["name", "school_year_id"], limit=1)
                if not cls:
                    cls = frappe.get_all("SIS Class", filters={"title": class_name}, fields=["name", "school_year_id"], limit=1)
                if cls:
                    class_id = cls[0].name
                    if not school_year_id:
                        school_year_id = cls[0].get("school_year_id")
            except Exception:
                pass

        # Resolve school_year_id from active year if still missing
        if not school_year_id:
            try:
                active = frappe.get_all("SIS School Year", filters={"is_enable": 1}, fields=["name"], order_by="start_date desc", limit=1)
                if active:
                    school_year_id = active[0].name
            except Exception:
                pass

        # If name not provided, try to resolve using composite key
        if not name:
            filters = {}
            if class_id:
                filters['class_id'] = class_id
            if student_id:
                filters['student_id'] = student_id
            if school_year_id:
                filters['school_year_id'] = school_year_id
            if class_type:
                filters['class_type'] = class_type

            # Require student_id and at least one scope key (school_year_id or class_id)
            has_student = 'student_id' in filters
            has_scope = ('school_year_id' in filters) or ('class_id' in filters)
            if not (has_student and has_scope):
                return error_response(
                    message="Missing required parameter: name or (student_id|student_code, school_year_id|class_id)",
                    code="MISSING_KEY"
                )

            candidates = frappe.get_all(
                "SIS Class Student",
                filters=filters,
                fields=["name"],
                order_by="creation desc",
                limit=2,
            )
            if not candidates:
                return not_found_response(
                    message="Class student assignment not found",
                    code="CLASS_STUDENT_NOT_FOUND"
                )
            if len(candidates) > 1 and not class_id:
                return validation_error_response(
                    message="Multiple assignments found. Please provide class_id to unassign a specific class",
                )
            name = candidates[0]["name"]
        
        # Check if class student exists
        if not frappe.db.exists("SIS Class Student", name):
            return not_found_response(
                message="Class student assignment not found",
                code="CLASS_STUDENT_NOT_FOUND"
            )

        # Load current class student document for context
        cs_doc = frappe.get_doc("SIS Class Student", name)

        # Reassign flow: migrate linked records to a target class student instead of deleting them
        migrated_event_students = 0
        if reassign_to_class_id or reassign_to_class_name or reassign_to_latest:
            target_class_id = reassign_to_class_id
            if not target_class_id and reassign_to_class_name:
                try:
                    row = frappe.get_all("SIS Class", filters={"name": reassign_to_class_name}, fields=["name"], limit=1)
                    if not row:
                        row = frappe.get_all("SIS Class", filters={"title": reassign_to_class_name}, fields=["name"], limit=1)
                    if row:
                        target_class_id = row[0].name
                except Exception:
                    target_class_id = None
            if not target_class_id and reassign_to_latest:
                try:
                    other = frappe.get_all(
                        "SIS Class Student",
                        filters={
                            "student_id": cs_doc.student_id,
                            "school_year_id": cs_doc.school_year_id,
                            "name": ["!=", cs_doc.name]
                        },
                        fields=["name", "class_id"],
                        order_by="creation desc",
                        limit=1
                    )
                    if other:
                        target_class_id = other[0].class_id
                except Exception:
                    target_class_id = None

            if not target_class_id:
                return validation_error_response(
                    message="Missing target class for reassignment",
                    errors={"reassign_to_class_id": ["Required if reassigning"]}
                )

            # Ensure destination class student exists or create
            target_cs = frappe.get_all(
                "SIS Class Student",
                filters={
                    "class_id": target_class_id,
                    "student_id": cs_doc.student_id,
                    "school_year_id": cs_doc.school_year_id,
                },
                fields=["name"],
                limit=1
            )
            if target_cs:
                target_cs_name = target_cs[0].name
            else:
                # Create a new class student record mirroring essential fields
                target_doc = frappe.get_doc({
                    "doctype": "SIS Class Student",
                    "class_id": target_class_id,
                    "student_id": cs_doc.student_id,
                    "school_year_id": cs_doc.school_year_id,
                    "class_type": cs_doc.class_type or "regular",
                    "campus_id": cs_doc.campus_id,
                })
                target_doc.insert()
                target_cs_name = target_doc.name

            # Migrate linked SIS Event Student -> point to target class student
            try:
                linked_es = frappe.get_all(
                    "SIS Event Student",
                    filters={"class_student_id": cs_doc.name},
                    fields=["name"],
                    limit_page_length=100000
                )
                for es in linked_es:
                    try:
                        frappe.db.set_value("SIS Event Student", es["name"], {
                            "class_student_id": target_cs_name
                        }, update_modified=True)
                        migrated_event_students += 1
                    except Exception:
                        # Continue with others
                        pass
                frappe.db.commit()
            except Exception as migrate_err:
                frappe.logger().error(f"Reassign migration failed for class student {name}: {str(migrate_err)}")
                return error_response(
                    message="Failed to migrate linked event participants during reassignment",
                    code="REASSIGN_MIGRATION_ERROR"
                )

        # If force flag is set, delete linked SIS Event Student first (when not reassigning)
        deleted_event_students = 0
        if force and not (reassign_to_class_id or reassign_to_class_name or reassign_to_latest):
            try:
                linked_es = frappe.get_all(
                    "SIS Event Student",
                    filters={"class_student_id": name},
                    fields=["name"],
                    limit_page_length=100000
                )
                for es in linked_es:
                    try:
                        frappe.delete_doc("SIS Event Student", es["name"]) 
                    except Exception:
                        # Continue deleting others; the final delete below will surface remaining links if any
                        pass
                if linked_es:
                    deleted_event_students = len(linked_es)
            except Exception as cleanup_err:
                frappe.logger().error(f"Force cleanup failed for class student {name}: {str(cleanup_err)}")
                return error_response(
                    message="Failed to remove linked event participants before unassigning",
                    code="FORCE_UNASSIGN_CLEANUP_ERROR"
                )

        # 🆕 Clear Class Log Student link before delete
        _clear_class_log_student_link(name)
        
        # Delete the assignment
        frappe.delete_doc("SIS Class Student", name)
        frappe.db.commit()
        
        frappe.logger().info(f"Successfully unassigned class student: {name}")
        
        suffix = ""
        if deleted_event_students > 0:
            suffix += f" (removed {deleted_event_students} linked event participant(s))"
        if migrated_event_students > 0:
            suffix += f" (migrated {migrated_event_students} linked event participant(s))"
        return success_response(
            message=f"Student unassigned from class successfully{suffix}"
        )
        
    except frappe.LinkExistsError as e:
        # Happens when Class Student is linked to other doctypes (e.g., SIS Event Student)
        frappe.db.rollback()
        # Attempt auto-resolution if flags provided, then retry deletion
        try:
            # Reassignment takes precedence over force deletion
            if reassign_to_class_id or reassign_to_class_name or reassign_to_latest:
                try:
                    cs_doc = frappe.get_doc("SIS Class Student", name)
                except Exception:
                    cs_doc = None
                target_class_id = reassign_to_class_id
                if not target_class_id and reassign_to_class_name:
                    try:
                        row = frappe.get_all("SIS Class", filters={"name": reassign_to_class_name}, fields=["name"], limit=1)
                        if not row:
                            row = frappe.get_all("SIS Class", filters={"title": reassign_to_class_name}, fields=["name"], limit=1)
                        if row:
                            target_class_id = row[0].name
                    except Exception:
                        target_class_id = None
                if not target_class_id and reassign_to_latest and cs_doc:
                    try:
                        other = frappe.get_all(
                            "SIS Class Student",
                            filters={
                                "student_id": cs_doc.student_id,
                                "school_year_id": cs_doc.school_year_id,
                                "name": ["!=", cs_doc.name]
                            },
                            fields=["name", "class_id"],
                            order_by="creation desc",
                            limit=1
                        )
                        if other:
                            target_class_id = other[0].class_id
                    except Exception:
                        target_class_id = None
                if target_class_id and cs_doc:
                    # Ensure destination class student exists or create
                    target_cs = frappe.get_all(
                        "SIS Class Student",
                        filters={
                            "class_id": target_class_id,
                            "student_id": cs_doc.student_id,
                            "school_year_id": cs_doc.school_year_id,
                        },
                        fields=["name"],
                        limit=1
                    )
                    if target_cs:
                        target_cs_name = target_cs[0].name
                    else:
                        target_doc = frappe.get_doc({
                            "doctype": "SIS Class Student",
                            "class_id": target_class_id,
                            "student_id": cs_doc.student_id,
                            "school_year_id": cs_doc.school_year_id,
                            "class_type": cs_doc.class_type or "regular",
                            "campus_id": cs_doc.campus_id,
                        })
                        target_doc.insert()
                        target_cs_name = target_doc.name

                    linked_es = frappe.get_all(
                        "SIS Event Student",
                        filters={"class_student_id": name},
                        fields=["name"],
                        limit_page_length=100000
                    )
                    for es in linked_es:
                        try:
                            frappe.db.set_value("SIS Event Student", es["name"], {"class_student_id": target_cs_name}, update_modified=True)
                        except Exception:
                            pass
                    frappe.db.commit()

                    # 🆕 Clear Class Log Student link before retry delete
                    _clear_class_log_student_link(name)

                    # Retry delete
                    frappe.delete_doc("SIS Class Student", name)
                    frappe.db.commit()
                    return success_response(message="Student unassigned (reassigned and links migrated)")

            if force:
                # Remove linked ES then retry delete
                linked_es = frappe.get_all(
                    "SIS Event Student",
                    filters={"class_student_id": name},
                    fields=["name"],
                    limit_page_length=100000
                )
                for es in linked_es:
                    try:
                        frappe.delete_doc("SIS Event Student", es["name"])
                    except Exception:
                        pass
                frappe.db.commit()
                
                # 🆕 Clear Class Log Student link before force delete
                _clear_class_log_student_link(name)
                
                frappe.delete_doc("SIS Class Student", name)
                frappe.db.commit()
                return success_response(message="Student unassigned (force removed linked records)")
            
            # Fallback auto-resolution when no flags provided
            try:
                cs_doc = frappe.get_doc("SIS Class Student", name)
            except Exception:
                cs_doc = None
            target_cs_name = None
            if cs_doc:
                try:
                    other = frappe.get_all(
                        "SIS Class Student",
                        filters={
                            "student_id": cs_doc.student_id,
                            "school_year_id": cs_doc.school_year_id,
                            "name": ["!=", cs_doc.name]
                        },
                        fields=["name", "class_id"],
                        order_by="creation desc",
                        limit=1
                    )
                    if other:
                        target_cs_name = other[0].name
                except Exception:
                    target_cs_name = None

            if target_cs_name:
                linked_es = frappe.get_all(
                    "SIS Event Student",
                    filters={"class_student_id": name},
                    fields=["name"],
                    limit_page_length=100000
                )
                for es in linked_es:
                    try:
                        frappe.db.set_value("SIS Event Student", es["name"], {"class_student_id": target_cs_name}, update_modified=True)
                    except Exception:
                        pass
                frappe.db.commit()
                
                # 🆕 Clear Class Log Student link before delete
                _clear_class_log_student_link(name)
                
                frappe.delete_doc("SIS Class Student", name)
                frappe.db.commit()
                return success_response(message="Student unassigned (auto-migrated links)")

            # As last resort, remove linked ES then delete
            linked_es = frappe.get_all(
                "SIS Event Student",
                filters={"class_student_id": name},
                fields=["name"],
                limit_page_length=100000
            )
            for es in linked_es:
                try:
                    frappe.delete_doc("SIS Event Student", es["name"]) 
                except Exception:
                    pass
            frappe.db.commit()
            
            # 🆕 Clear Class Log Student link before delete
            _clear_class_log_student_link(name)
            
            frappe.delete_doc("SIS Class Student", name)
            frappe.db.commit()
            return success_response(message="Student unassigned (auto-removed linked records)")
        except Exception as resolve_err:
            try:
                frappe.log_error(title="Unassign auto-resolve failed", message=str(resolve_err))
            except Exception:
                pass

        # Fall back: report link error
        try:
            frappe.log_error(title="Unassign failed: linked documents", message=str(e))
        except Exception:
            pass
        return error_response(
            message=str(e),
            code="CLASS_STUDENT_LINKED"
        )
    except Exception as e:
        # Generic error handler
        frappe.db.rollback()
        try:
            frappe.log_error(title="Unassign class student error", message=str(e))
        except Exception:
            pass
        return error_response(
            message="Error unassigning student from class",
            code="UNASSIGN_STUDENT_ERROR"
        )


@frappe.whitelist(allow_guest=False, methods=['POST'])
def batch_get_class_sizes():
    """
    Get student counts for multiple classes in a single request
    
    POST body:
    {
        "class_ids": ["CLASS-001", "CLASS-002", ...],
        "school_year_id": "2024-2025" (optional)
    }
    
    Returns:
    {
        "success": true,
        "data": {
            "CLASS-001": 25,
            "CLASS-002": 30,
            ...
        }
    }
    """
    try:
        frappe.logger().info("🚀 [Backend] batch_get_class_sizes called")
        
        # Parse request body
        import json
        body = {}
        try:
            if hasattr(frappe, 'request') and getattr(frappe.request, 'data', None):
                body = json.loads(frappe.request.data.decode('utf-8'))
        except Exception:
            pass
        
        class_ids = body.get('class_ids', [])
        school_year_id = body.get('school_year_id')
        
        if not class_ids or not isinstance(class_ids, list):
            return error_response(
                message="Missing required parameter: class_ids (must be an array)",
                code="MISSING_PARAMS"
            )
        
        frappe.logger().info(f"📊 [Backend] Getting sizes for {len(class_ids)} classes")
        
        # Build base filters
        filters = {"class_id": ["in", class_ids]}
        if school_year_id:
            filters["school_year_id"] = school_year_id
        
        # Get campus filter from context
        from erp.utils.campus_utils import get_current_campus_from_context
        campus_id = get_current_campus_from_context()
        if campus_id:
            filters['campus_id'] = campus_id
        
        # Single query to get counts grouped by class_id
        # Using frappe.db.sql for efficient GROUP BY query
        query = """
            SELECT class_id, COUNT(*) as count
            FROM `tabSIS Class Student`
            WHERE class_id IN %(class_ids)s
        """
        
        params = {"class_ids": class_ids}
        
        if school_year_id:
            query += " AND school_year_id = %(school_year_id)s"
            params["school_year_id"] = school_year_id
        
        if campus_id:
            query += " AND campus_id = %(campus_id)s"
            params["campus_id"] = campus_id
        
        query += " GROUP BY class_id"
        
        results = frappe.db.sql(query, params, as_dict=True)
        
        # Build result map: class_id -> count
        result = {}
        for row in results:
            result[row['class_id']] = row['count']
        
        # Ensure all requested class_ids are in result (even if 0 students)
        for class_id in class_ids:
            if class_id not in result:
                result[class_id] = 0
        
        frappe.logger().info(f"✅ [Backend] Returning sizes for {len(result)} classes")
        
        return success_response(
            data=result,
            message=f"Fetched sizes for {len(class_ids)} classes"
        )
        
    except Exception as e:
        frappe.logger().error(f"❌ [Backend] batch_get_class_sizes error: {str(e)}")
        frappe.log_error(f"batch_get_class_sizes error: {str(e)}", "Batch Get Class Sizes Error")
        return error_response(
            message=f"Failed to fetch batch class sizes: {str(e)}",
            code="BATCH_GET_CLASS_SIZES_ERROR"
        )


@frappe.whitelist(allow_guest=False, methods=["POST"])
def check_student_subject_sync_status(class_ids=None):
    """
    Check if Student Subject records are in sync with Class Student records.
    Returns a report of any mismatches that need to be fixed.
    
    This is useful for:
    - Verifying data integrity after class transfers
    - Identifying students who need their Student Subject records updated
    - Troubleshooting report card creation issues
    """
    try:
        from erp.utils.campus_utils import get_current_campus_from_context
        campus_id = get_current_campus_from_context()
        if not campus_id:
            campus_id = "campus-1"
        
        # Get class_ids from request
        if not class_ids:
            data = {}
            if hasattr(frappe, 'request') and frappe.request.data:
                try:
                    import json
                    data = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
                except:
                    pass
            class_ids = data.get('class_ids', [])
        
        if not class_ids:
            return validation_error_response("class_ids is required")
        
        if not isinstance(class_ids, list):
            class_ids = [class_ids]
        
        report = {
            "classes_checked": len(class_ids),
            "issues": [],
            "students_with_mismatches": [],
            "total_mismatches": 0
        }
        
        for class_id in class_ids:
            # Get students from Class Student (authoritative)
            class_students = frappe.get_all(
                "SIS Class Student",
                fields=["student_id", "school_year_id"],
                filters={
                    "campus_id": campus_id,
                    "class_id": class_id
                }
            )
            
            for cs in class_students:
                student_id = cs["student_id"]
                school_year_id = cs["school_year_id"]
                
                # Check if Student Subject has mismatched class_id
                mismatched = frappe.db.sql("""
                    SELECT COUNT(*) as count, 
                           GROUP_CONCAT(DISTINCT class_id) as wrong_classes
                    FROM `tabSIS Student Subject`
                    WHERE student_id = %s
                    AND school_year_id = %s
                    AND campus_id = %s
                    AND class_id != %s
                """, (student_id, school_year_id, campus_id, class_id), as_dict=True)
                
                if mismatched and mismatched[0]["count"] > 0:
                    report["issues"].append({
                        "class_id": class_id,
                        "student_id": student_id,
                        "school_year_id": school_year_id,
                        "mismatch_count": mismatched[0]["count"],
                        "wrong_classes": mismatched[0]["wrong_classes"],
                        "message": f"Student {student_id} is in class {class_id} but has {mismatched[0]['count']} Student Subject records with different class_id"
                    })
                    report["students_with_mismatches"].append(student_id)
                    report["total_mismatches"] += mismatched[0]["count"]
        
        report["has_issues"] = len(report["issues"]) > 0
        
        if report["has_issues"]:
            message = f"Found {len(report['issues'])} students with sync issues ({report['total_mismatches']} mismatched records)"
        else:
            message = "All Student Subject records are in sync with Class Student"
        
        return success_response(
            data=report,
            message=message
        )
        
    except Exception as e:
        frappe.log_error(f"Error checking student subject sync status: {str(e)}")
        return error_response(
            message=f"Failed to check sync status: {str(e)}",
            code="CHECK_SYNC_STATUS_ERROR"
        )


@frappe.whitelist(allow_guest=False, methods=["POST"])
def create_student_subjects_from_timetable(class_id=None, student_id=None):
    """
    Manually create Student Subject records from class timetable.
    
    This is useful when:
    - A student was added to a class before timetable was created
    - Student Subject records are missing and report cards are empty
    - Need to force refresh Student Subject records
    
    Args:
        class_id: Class ID (optional, if not provided will process all classes)
        student_id: Student ID (optional, if not provided will process all students in class)
    
    Returns:
        success_response with created_count and logs
    """
    try:
        from erp.utils.campus_utils import get_current_campus_from_context
        campus_id = get_current_campus_from_context()
        if not campus_id:
            campus_id = "campus-1"
        
        # Get parameters from request
        if class_id is None or student_id is None:
            data = {}
            if hasattr(frappe, 'request') and frappe.request.data:
                try:
                    import json
                    data = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
                except:
                    pass
            class_id = class_id or data.get('class_id')
            student_id = student_id or data.get('student_id')
        
        if not class_id:
            return validation_error_response("class_id is required")
        
        logs = []
        created_count = 0
        skipped_count = 0
        error_count = 0
        
        # Get timetable for this class
        timetable_instances = frappe.get_all(
            "SIS Timetable Instance",
            fields=["name", "school_year_id"],
            filters={
                "campus_id": campus_id,
                "class_id": class_id
            }
        )
        
        if not timetable_instances:
            return error_response(
                f"No timetable found for class {class_id}. "
                "Please create a timetable first before creating student subjects.",
                code="NO_TIMETABLE"
            )
        
        instance_ids = [t["name"] for t in timetable_instances]
        school_year_id = timetable_instances[0]["school_year_id"]
        
        logs.append(f"Found {len(timetable_instances)} timetable instance(s) for class {class_id}")
        
        # Get subjects from timetable
        timetable_subjects = frappe.db.sql("""
            SELECT DISTINCT subject_id
            FROM `tabSIS Timetable Instance Row`
            WHERE parent IN %s
            AND subject_id IS NOT NULL
            AND subject_id != ''
        """, [instance_ids], as_dict=True)
        
        subject_ids = [s["subject_id"] for s in timetable_subjects if s.get("subject_id")]
        logs.append(f"Found {len(subject_ids)} distinct subjects in timetable")
        
        if not subject_ids:
            return error_response(
                f"Timetable for class {class_id} has no subjects. "
                "Please add subjects to timetable first.",
                code="NO_SUBJECTS_IN_TIMETABLE"
            )
        
        # Get students to process
        if student_id:
            # Process single student
            students = [{"student_id": student_id}]
            logs.append(f"Processing single student: {student_id}")
        else:
            # Process all students in class
            students = frappe.get_all(
                "SIS Class Student",
                fields=["student_id"],
                filters={
                    "campus_id": campus_id,
                    "class_id": class_id
                }
            )
            logs.append(f"Processing {len(students)} students in class {class_id}")
        
        # For each student and subject, create Student Subject record if not exists
        for student_record in students:
            student_id = student_record["student_id"]
            
            for subject_id in subject_ids:
                try:
                    # Get actual_subject_id
                    actual_subject_id = frappe.db.get_value("SIS Subject", subject_id, "actual_subject_id")
                    
                    if not actual_subject_id:
                        logs.append(f"⚠️ Subject {subject_id} has no actual_subject_id, skipping")
                        skipped_count += 1
                        continue
                    
                    # Check if exists
                    existing = frappe.db.exists(
                        "SIS Student Subject",
                        {
                            "campus_id": campus_id,
                            "student_id": student_id,
                            "class_id": class_id,
                            "subject_id": subject_id,
                            "school_year_id": school_year_id
                        }
                    )
                    
                    if existing:
                        skipped_count += 1
                        continue
                    
                    # Create new record
                    doc = frappe.get_doc({
                        "doctype": "SIS Student Subject",
                        "campus_id": campus_id,
                        "student_id": student_id,
                        "class_id": class_id,
                        "subject_id": subject_id,
                        "actual_subject_id": actual_subject_id,
                        "school_year_id": school_year_id
                    })
                    doc.insert(ignore_permissions=True)
                    created_count += 1
                    
                except Exception as e:
                    error_count += 1
                    logs.append(f"✗ Error creating Student Subject for student {student_id}, subject {subject_id}: {str(e)}")
                    frappe.log_error(f"Error creating Student Subject: {str(e)}")
        
        frappe.db.commit()
        
        logs.append(f"✓ Created {created_count} new Student Subject records")
        logs.append(f"Skipped {skipped_count} existing records")
        if error_count > 0:
            logs.append(f"✗ {error_count} errors occurred")
        
        return success_response(
            data={
                "created_count": created_count,
                "skipped_count": skipped_count,
                "error_count": error_count,
                "logs": logs
            },
            message=f"Created {created_count} Student Subject records from timetable"
        )
        
    except Exception as e:
        frappe.log_error(f"Error creating student subjects from timetable: {str(e)}")
        frappe.db.rollback()
        return error_response(
            message=f"Failed to create student subjects: {str(e)}",
            code="CREATE_STUDENT_SUBJECTS_ERROR"
        )


@frappe.whitelist(allow_guest=False, methods=["POST"])
def fix_student_subject_sync(class_ids=None, auto_fix=False):
    """
    Fix Student Subject records that are out of sync with Class Student.
    
    This will update all Student Subject records to match the current class assignment
    in Class Student table.
    
    Args:
        class_ids: List of class IDs to fix (optional, if not provided will fix all)
        auto_fix: If True, automatically fix all issues. If False, only report issues.
    """
    try:
        from erp.utils.campus_utils import get_current_campus_from_context
        campus_id = get_current_campus_from_context()
        if not campus_id:
            campus_id = "campus-1"
        
        # Get parameters from request
        if class_ids is None:
            data = {}
            if hasattr(frappe, 'request') and frappe.request.data:
                try:
                    import json
                    data = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
                except:
                    pass
            class_ids = data.get('class_ids')
            auto_fix = data.get('auto_fix', False)
        
        logs = []
        fixed_count = 0
        error_count = 0
        
        # Build filters for Class Student
        filters = {"campus_id": campus_id}
        if class_ids:
            if not isinstance(class_ids, list):
                class_ids = [class_ids]
            filters["class_id"] = ["in", class_ids]
            logs.append(f"Fixing sync for {len(class_ids)} classes")
        else:
            logs.append("Fixing sync for ALL classes in campus")
        
        # Get all class students
        class_students = frappe.get_all(
            "SIS Class Student",
            fields=["student_id", "class_id", "school_year_id"],
            filters=filters
        )
        
        logs.append(f"Found {len(class_students)} class student records to process")
        
        for cs in class_students:
            student_id = cs["student_id"]
            correct_class_id = cs["class_id"]
            school_year_id = cs["school_year_id"]
            
            # Check for mismatches
            mismatched = frappe.db.sql("""
                SELECT name, class_id
                FROM `tabSIS Student Subject`
                WHERE student_id = %s
                AND school_year_id = %s
                AND campus_id = %s
                AND class_id != %s
            """, (student_id, school_year_id, campus_id, correct_class_id), as_dict=True)
            
            if mismatched:
                if auto_fix:
                    # Fix the mismatches
                    try:
                        result = sync_student_subjects_for_class_change(
                            student_id=student_id,
                            new_class_id=correct_class_id,
                            school_year_id=school_year_id,
                            campus_id=campus_id,
                            old_class_id=None
                        )
                        if result.get("success"):
                            fixed_count += result.get("updated_count", 0)
                            logs.append(f"✓ Fixed {result.get('updated_count', 0)} records for student {student_id}")
                        else:
                            error_count += 1
                            logs.append(f"✗ Failed to fix student {student_id}: {result.get('error', 'Unknown error')}")
                    except Exception as e:
                        error_count += 1
                        logs.append(f"✗ Error fixing student {student_id}: {str(e)}")
                else:
                    # Just report
                    logs.append(f"⚠️ Student {student_id} has {len(mismatched)} mismatched records (auto_fix=False, not fixing)")
        
        if auto_fix:
            frappe.db.commit()
            message = f"Fixed {fixed_count} Student Subject records. Errors: {error_count}"
        else:
            message = "Dry run completed. Set auto_fix=True to apply fixes."
        
        return success_response(
            data={
                "fixed_count": fixed_count,
                "error_count": error_count,
                "logs": logs,
                "auto_fix": auto_fix
            },
            message=message
        )
        
    except Exception as e:
        frappe.log_error(f"Error fixing student subject sync: {str(e)}")
        frappe.db.rollback()
        return error_response(
            message=f"Failed to fix sync: {str(e)}",
            code="FIX_SYNC_ERROR"
        )
