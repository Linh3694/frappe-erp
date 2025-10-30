# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import nowdate, get_datetime
import json
from erp.utils.campus_utils import get_current_campus_from_context, get_campus_id_from_user_roles
from erp.utils.api_response import (
    success_response,
    error_response,
    list_response,
    single_item_response,
    validation_error_response,
    not_found_response,
    forbidden_response
)


@frappe.whitelist(allow_guest=False)
def get_all_subjects():
    """Get all subjects with basic information - SIMPLE VERSION"""
    try:
        # Get current user's campus information from roles
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            # Fallback to default if no campus found
            campus_id = "campus-1"
            frappe.logger().warning(f"No campus found for user {frappe.session.user}, using default: {campus_id}")
        
        filters = {"campus_id": campus_id}
            

        try:
            subjects_query = """
                SELECT
                    s.name,
                    s.title as title_vn,
                    '' as title_en,
                    '' as short_title,
                    s.education_stage,
                    s.academic_program_id,
                    NULL as curriculum_id,
                    s.timetable_subject_id,
                    s.actual_subject_id,
                    s.subcurriculum_id,
                    s.room_id,
                    s.campus_id,
                    s.creation,
                    s.modified,
                    COALESCE(es.title_vn, '') as education_stage_name,
                    COALESCE(ts.title_vn, '') as timetable_subject_name,
                    COALESCE(act.title_vn, '') as actual_subject_name,
                    COALESCE(r.title_vn, '') as room_name
                FROM `tabSIS Subject` s
                LEFT JOIN `tabSIS Education Stage` es ON s.education_stage = es.name AND es.campus_id = s.campus_id
                LEFT JOIN `tabSIS Timetable Subject` ts ON s.timetable_subject_id = ts.name AND ts.campus_id = s.campus_id
                LEFT JOIN `tabSIS Actual Subject` act ON s.actual_subject_id = act.name AND act.campus_id = s.campus_id
                LEFT JOIN `tabSIS Sub Curriculum` sc ON s.subcurriculum_id = sc.name AND sc.campus_id = s.campus_id
                LEFT JOIN `tabERP Administrative Room` r ON s.room_id = r.name
                WHERE s.campus_id = %s
                ORDER BY s.title ASC
            """
            subjects = frappe.db.sql(subjects_query, (campus_id,), as_dict=True)
        except Exception as column_error:
            frappe.logger().warning(f"Query with all fields failed: {str(column_error)}, trying with basic fields only")
            # Fallback query without potentially missing columns
            subjects_query = """
                SELECT
                    s.name,
                    s.title as title_vn,
                    '' as title_en,
                    '' as short_title,
                    s.education_stage,
                    s.timetable_subject_id,
                    s.actual_subject_id,
                    s.room_id,
                    s.campus_id,
                    s.creation,
                    s.modified,
                    COALESCE(es.title_vn, '') as education_stage_name,
                    COALESCE(ts.title_vn, '') as timetable_subject_name,
                    COALESCE(act.title_vn, '') as actual_subject_name,
                    COALESCE(r.title_vn, '') as room_name
                FROM `tabSIS Subject` s
                LEFT JOIN `tabSIS Education Stage` es ON s.education_stage = es.name AND es.campus_id = s.campus_id
                LEFT JOIN `tabSIS Timetable Subject` ts ON s.timetable_subject_id = ts.name AND ts.campus_id = s.campus_id
                LEFT JOIN `tabSIS Actual Subject` act ON s.actual_subject_id = act.name AND act.campus_id = s.campus_id
                LEFT JOIN `tabERP Administrative Room` r ON s.room_id = r.name
                WHERE s.campus_id = %s
                ORDER BY s.title ASC
            """
            subjects = frappe.db.sql(subjects_query, (campus_id,), as_dict=True)

        frappe.logger().info(f"Found {len(subjects)} subjects")

    except Exception as db_error:
        frappe.logger().error(f"Database error: {str(db_error)}")
        import traceback
        frappe.logger().error(f"Database error traceback: {traceback.format_exc()}")
        return error_response(
            message=f"Database error: {str(db_error)}",
            code="DATABASE_ERROR"
        )

    return list_response(subjects, "Subjects fetched successfully")


@frappe.whitelist(allow_guest=False)
def get_subjects_by_curriculums():
    """Get subjects filtered by curriculum IDs for report card templates"""
    try:
        # Get curriculum_ids from request data
        data = {}
        
        # Try to get from JSON payload first
        if frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
                data = json_data
            except (json.JSONDecodeError, TypeError, AttributeError, UnicodeDecodeError):
                data = frappe.local.form_dict
        else:
            data = frappe.local.form_dict
        
        curriculum_ids = data.get('curriculum_ids')
        
        if not curriculum_ids:
            return validation_error_response({"curriculum_ids": ["Curriculum IDs are required"]})
        
        # Ensure curriculum_ids is a list
        if isinstance(curriculum_ids, str):
            try:
                curriculum_ids = json.loads(curriculum_ids)
            except json.JSONDecodeError:
                curriculum_ids = [curriculum_ids]
        
        if not isinstance(curriculum_ids, list) or len(curriculum_ids) == 0:
            return validation_error_response({"curriculum_ids": ["At least one curriculum ID is required"]})
        
        # Get current user's campus information
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
            frappe.logger().warning(f"No campus found for user {frappe.session.user}, using default: {campus_id}")
        
        # Query subjects with curriculum filtering from SIS Actual Subject table
        # This matches the same logic as get_subjects_by_classes in student_subject.py
        subjects_query = """
            SELECT DISTINCT
                s.name,
                s.title_vn,
                s.title_en,
                s.education_stage_id,
                s.curriculum_id,
                s.campus_id,
                s.title_vn as title
            FROM `tabSIS Actual Subject` s
            WHERE s.campus_id = %s 
              AND s.curriculum_id IN ({placeholders})
            ORDER BY s.title_vn ASC
        """.format(placeholders=','.join(['%s'] * len(curriculum_ids)))
        
        query_params = [campus_id] + curriculum_ids
        subjects = frappe.db.sql(subjects_query, query_params, as_dict=True)

        frappe.logger().info(f"Found {len(subjects)} subjects for curriculums {curriculum_ids}")

        return list_response(subjects, f"Found {len(subjects)} subjects for specified curriculums")
        
    except Exception as e:
        frappe.log_error(f"Error fetching subjects by curriculums: {str(e)}")
        return error_response(
            message=f"Error fetching subjects by curriculums: {str(e)}",
            code="FETCH_SUBJECTS_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def get_subject_by_id():
    """Get a specific subject by ID"""
    try:
        # Get subject_id from multiple sources (form data or JSON payload)
        subject_id = None

        # Try from form_dict first (for FormData/URLSearchParams)
        subject_id = frappe.form_dict.get('subject_id')

        # Try from URL args (for query parameters)
        if not subject_id:
            subject_id = frappe.request.args.get('subject_id')

        # If not found, try from JSON payload
        if not subject_id and frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
                subject_id = json_data.get('subject_id')
            except (json.JSONDecodeError, TypeError, AttributeError, UnicodeDecodeError) as e:
                pass

        if not subject_id:
            return validation_error_response({"subject_id": ["Subject ID is required"]})
        
        # Get current user's campus
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
            
        filters = {
            "name": subject_id,
            "campus_id": campus_id
        }
        
        subject = frappe.get_doc("SIS Subject", filters)

        if not subject:
            return not_found_response("Subject not found or access denied")

        # Get display names from linked tables
        education_stage_name = None
        if subject.education_stage:
            try:
                education_stage_doc = frappe.get_doc("SIS Education Stage", subject.education_stage)
                education_stage_name = education_stage_doc.title_vn
            except:
                pass

        timetable_subject_name = None
        if subject.timetable_subject_id:
            try:
                timetable_subject_doc = frappe.get_doc("SIS Timetable Subject", subject.timetable_subject_id)
                timetable_subject_name = timetable_subject_doc.title_vn
            except:
                pass

        actual_subject_name = None
        if subject.actual_subject_id:
            try:
                actual_subject_doc = frappe.get_doc("SIS Actual Subject", subject.actual_subject_id)
                actual_subject_name = actual_subject_doc.title_vn
            except:
                pass

        room_name = None
        if subject.room_id:
            try:
                room_doc = frappe.get_doc("ERP Administrative Room", subject.room_id)
                room_name = room_doc.title_vn
            except:
                pass

        subject_data = {
            "name": subject.name,
            "title": subject.title,
            "education_stage": subject.education_stage,
            "timetable_subject_id": subject.timetable_subject_id,
            "actual_subject_id": subject.actual_subject_id,
            "subcurriculum_id": subject.subcurriculum_id,
            "room_id": subject.room_id,
            "campus_id": subject.campus_id,
            # Display names for UI
            "education_stage_name": education_stage_name,
            "timetable_subject_name": timetable_subject_name,
            "actual_subject_name": actual_subject_name,
            "room_name": room_name
        }

        return single_item_response(subject_data, "Subject fetched successfully")
        
    except Exception as e:
        frappe.log_error(f"Error fetching subject {subject_id}: {str(e)}")
        return {
            "success": False,
            "data": {},
            "message": f"Error fetching subject: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def create_subject():
    """Create a new subject - SIMPLE VERSION"""
    try:
        # Get data from request - follow Education Stage pattern
        data = {}
        
        # First try to get JSON data from request body
        if frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data)
                if json_data:
                    data = json_data
                    frappe.logger().info(f"Received JSON data for create_subject: {data}")
                else:
                    data = frappe.local.form_dict
                    frappe.logger().info(f"Received form data for create_subject: {data}")
            except (json.JSONDecodeError, TypeError):
                # If JSON parsing fails, use form_dict
                data = frappe.local.form_dict
                frappe.logger().info(f"JSON parsing failed, using form data for create_subject: {data}")
        else:
            # Fallback to form_dict
            data = frappe.local.form_dict
            frappe.logger().info(f"No request data, using form_dict for create_subject: {data}")
        
        # Extract values from data
        title = data.get("title")
        education_stage = data.get("education_stage")
        timetable_subject_id = data.get("timetable_subject_id")
        actual_subject_id = data.get("actual_subject_id")
        subcurriculum_id = data.get("subcurriculum_id")
        room_id = data.get("room_id")  # Can be None if not provided

        
        # Input validation
        if not title or not education_stage:
            frappe.throw(_("Title and education stage are required"))
        
        # Get campus from user context
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
            frappe.logger().warning(f"No campus found for user {frappe.session.user}, using default: {campus_id}")
        
        # Allow duplicate title - unique constraint removed
        
        # Verify education stage exists and belongs to same campus
        education_stage_exists = frappe.db.exists(
            "SIS Education Stage",
            {
                "name": education_stage,
                "campus_id": campus_id
            }
        )
        
        if not education_stage_exists:
            return not_found_response("Selected education stage does not exist or access denied")
        
        # Create new subject
        subject_data = {
            "doctype": "SIS Subject",
            "title": title,
            "education_stage": education_stage,
            "campus_id": campus_id
        }

        # Only add optional fields if they have values
        if timetable_subject_id:
            subject_data["timetable_subject_id"] = timetable_subject_id
        if actual_subject_id:
            subject_data["actual_subject_id"] = actual_subject_id
        if room_id:
            subject_data["room_id"] = room_id
        if subcurriculum_id:
            subject_data["subcurriculum_id"] = subcurriculum_id



        subject_doc = frappe.get_doc(subject_data)
        
        subject_doc.insert()
        frappe.db.commit()

        # Get display names from linked tables
        education_stage_name = None
        if subject_doc.education_stage:
            try:
                education_stage_doc = frappe.get_doc("SIS Education Stage", subject_doc.education_stage)
                education_stage_name = education_stage_doc.title_vn
            except:
                pass

        timetable_subject_name = None
        if subject_doc.timetable_subject_id:
            try:
                timetable_subject_doc = frappe.get_doc("SIS Timetable Subject", subject_doc.timetable_subject_id)
                timetable_subject_name = timetable_subject_doc.title_vn
            except:
                pass

        actual_subject_name = None
        if subject_doc.actual_subject_id:
            try:
                actual_subject_doc = frappe.get_doc("SIS Actual Subject", subject_doc.actual_subject_id)
                actual_subject_name = actual_subject_doc.title_vn
            except:
                pass

        room_name = None
        subcurriculum_name = None
        if subject_doc.room_id:
            try:
                room_doc = frappe.get_doc("ERP Administrative Room", subject_doc.room_id)
                room_name = room_doc.title_vn
            except:
                pass
        if subject_doc.subcurriculum_id:
            try:
                sc_doc = frappe.get_doc("SIS Sub Curriculum", subject_doc.subcurriculum_id)
                subcurriculum_name = sc_doc.title_vn
            except:
                pass

        # Return the created data - follow Education Stage pattern
        subject_data = {
            "name": subject_doc.name,
            "title": subject_doc.title,
            "education_stage": subject_doc.education_stage,
            "timetable_subject_id": subject_doc.timetable_subject_id,
            "actual_subject_id": subject_doc.actual_subject_id,
            "room_id": subject_doc.room_id,
            "campus_id": subject_doc.campus_id,
            "education_stage_name": education_stage_name,
            "timetable_subject_name": timetable_subject_name,
            "actual_subject_name": actual_subject_name,
            "subcurriculum_name": subcurriculum_name,
            "room_name": room_name
        }
        return single_item_response(subject_data, "Subject created successfully")
        
    except Exception as e:
        frappe.log_error(f"Error creating subject: {str(e)}")
        frappe.throw(_(f"Error creating subject: {str(e)}"))


@frappe.whitelist(allow_guest=False)
def update_subject():
    """Update an existing subject"""
    try:
        # Debug: Print all request data

        # Get data from multiple sources (form data or JSON payload)
        data = {}

        # Start with form_dict data
        if frappe.local.form_dict:
            data.update(dict(frappe.local.form_dict))

        # If JSON payload exists, merge it (JSON takes precedence)
        if frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
                data.update(json_data)
            except (json.JSONDecodeError, TypeError, AttributeError, UnicodeDecodeError) as e:
                pass

        subject_id = data.get('subject_id')

        if not subject_id:
            return {
                "success": False,
                "message": "Subject ID is required",
                "debug": {
                    "form_dict": dict(frappe.form_dict),
                    "request_data": str(frappe.request.data)[:500] if frappe.request.data else None,
                    "final_data": data
                }
            }
        
        # Get campus from user context
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
        
        # Get existing document
        try:
            subject_doc = frappe.get_doc("SIS Subject", subject_id)
            
            # Check campus permission
            if subject_doc.campus_id != campus_id:
                return {
                    "success": False,
                    "data": {},
                    "message": "Access denied: You don't have permission to modify this subject"
                }
                
        except frappe.DoesNotExistError:
            return {
                "success": False,
                "data": {},
                "message": "Subject not found"
            }
        
        # Update fields if provided
        title = data.get('title')
        education_stage = data.get('education_stage')
        timetable_subject_id = data.get('timetable_subject_id')
        actual_subject_id = data.get('actual_subject_id')
        subcurriculum_id = data.get('subcurriculum_id')
        room_id = data.get('room_id')


        if title and title != subject_doc.title:
            # Allow duplicate title - unique constraint removed
            subject_doc.title = title
        
        if education_stage and education_stage != subject_doc.education_stage:
            # Verify education stage exists and belongs to same campus
            education_stage_exists = frappe.db.exists(
                "SIS Education Stage",
                {
                    "name": education_stage,
                    "campus_id": campus_id
                }
            )
            
            if not education_stage_exists:
                return {
                    "success": False,
                    "data": {},
                    "message": "Selected education stage does not exist or access denied"
                }
            subject_doc.education_stage = education_stage
            
        # Update optional fields only if they are explicitly provided in the request
        # This handles the case where user selects "none" - field will be in request as None
        if 'timetable_subject_id' in data and timetable_subject_id != subject_doc.timetable_subject_id:
            subject_doc.timetable_subject_id = timetable_subject_id

        if 'actual_subject_id' in data and actual_subject_id != subject_doc.actual_subject_id:
            subject_doc.actual_subject_id = actual_subject_id

        if 'room_id' in data and room_id != subject_doc.room_id:
            subject_doc.room_id = room_id
        if 'subcurriculum_id' in data and subcurriculum_id != subject_doc.subcurriculum_id:
            subject_doc.subcurriculum_id = subcurriculum_id
        
        subject_doc.save()
        frappe.db.commit()

        # Get display names from linked tables
        education_stage_name = None
        if subject_doc.education_stage:
            try:
                education_stage_doc = frappe.get_doc("SIS Education Stage", subject_doc.education_stage)
                education_stage_name = education_stage_doc.title_vn
            except:
                pass

        timetable_subject_name = None
        if subject_doc.timetable_subject_id:
            try:
                timetable_subject_doc = frappe.get_doc("SIS Timetable Subject", subject_doc.timetable_subject_id)
                timetable_subject_name = timetable_subject_doc.title_vn
            except:
                pass

        actual_subject_name = None
        if subject_doc.actual_subject_id:
            try:
                actual_subject_doc = frappe.get_doc("SIS Actual Subject", subject_doc.actual_subject_id)
                actual_subject_name = actual_subject_doc.title_vn
            except:
                pass

        room_name = None
        if subject_doc.room_id:
            try:
                room_doc = frappe.get_doc("ERP Administrative Room", subject_doc.room_id)
                room_name = room_doc.title_vn
            except:
                pass

        return success_response(
            data={
                "name": subject_doc.name,
                "title": subject_doc.title,
                "education_stage": subject_doc.education_stage,
                "timetable_subject_id": subject_doc.timetable_subject_id,
                "actual_subject_id": subject_doc.actual_subject_id,
                "subcurriculum_id": subject_doc.subcurriculum_id,
                "room_id": subject_doc.room_id,
                "campus_id": subject_doc.campus_id,
                "education_stage_name": education_stage_name,
                "timetable_subject_name": timetable_subject_name,
                "actual_subject_name": actual_subject_name,
                "room_name": room_name
            },
            message="Subject updated successfully"
        )
        
    except Exception as e:
        frappe.log_error(f"Error updating subject {subject_id}: {str(e)}")
        return {
            "success": False,
            "data": {},
            "message": f"Error updating subject: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def delete_subject():
    """Delete a subject"""
    try:
        # Debug: Print request data

        # Get subject_id from multiple sources (form data or JSON payload)
        subject_id = None

        # Try from form_dict first (for FormData/URLSearchParams)
        subject_id = frappe.form_dict.get('subject_id')

        # If not found, try from JSON payload
        if not subject_id and frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
                subject_id = json_data.get('subject_id')
            except (json.JSONDecodeError, TypeError, AttributeError, UnicodeDecodeError) as e:
                pass

        if not subject_id:
            return validation_error_response({"subject_id": ["Subject ID is required"]})
        
        # Get campus from user context
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
        
        # Get existing document
        try:
            subject_doc = frappe.get_doc("SIS Subject", subject_id)
            
            # Check campus permission
            if subject_doc.campus_id != campus_id:
                return {
                    "success": False,
                    "data": {},
                    "message": "Access denied: You don't have permission to delete this subject"
                }
                
        except frappe.DoesNotExistError:
            return {
                "success": False,
                "data": {},
                "message": "Subject not found"
            }
        
        # Delete the document
        frappe.delete_doc("SIS Subject", subject_id)
        frappe.db.commit()
        
        return success_response(
            data={},
            message="Subject deleted successfully"
        )
        
    except Exception as e:
        frappe.log_error(f"Error deleting subject {subject_id}: {str(e)}")
        return {
            "success": False,
            "data": {},
            "message": f"Error deleting subject: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def get_actual_subjects_for_selection():
    """Get all actual subjects for dropdown selection"""
    try:
        # Get current user's campus information from roles
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            # Fallback to default if no campus found
            campus_id = "campus-1"
            frappe.logger().warning(f"No campus found for user {frappe.session.user}, using default: {campus_id}")
        
        filters = {"campus_id": campus_id}
            
        actual_subjects = frappe.db.sql("""
            SELECT 
                s.name,
                s.title_vn,
                s.title_en,
                COALESCE(es.title_vn, '') as education_stage_name
            FROM `tabSIS Actual Subject` s
            LEFT JOIN `tabSIS Education Stage` es ON s.education_stage_id = es.name
            WHERE s.campus_id = %(campus_id)s
            ORDER BY s.title_vn ASC
        """, {"campus_id": campus_id}, as_dict=True)
        
        return success_response(
            data=actual_subjects,
            message="Actual subjects for selection fetched successfully"
        )
        
    except Exception as e:
        frappe.log_error(f"Error fetching actual subjects for selection: {str(e)}")
        return {
            "success": False,
            "data": [],
            "message": f"Error fetching actual subjects: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def get_timetable_subjects_for_selection():
    """Get all timetable subjects for dropdown selection"""
    try:
        # Get current user's campus information from roles
        campus_id = get_current_campus_from_context()

        if not campus_id:
            # Fallback to default if no campus found
            campus_id = "campus-1"
            frappe.logger().warning(f"No campus found for user {frappe.session.user}, using default: {campus_id}")

        filters = {"campus_id": campus_id}

        timetable_subjects = frappe.db.sql("""
            SELECT 
                s.name,
                s.title_vn,
                s.title_en,
                COALESCE(es.title_vn, '') as education_stage_name
            FROM `tabSIS Timetable Subject` s
            LEFT JOIN `tabSIS Education Stage` es ON s.education_stage_id = es.name
            WHERE s.campus_id = %(campus_id)s
            ORDER BY s.title_vn ASC
        """, {"campus_id": campus_id}, as_dict=True)

        return success_response(
            data=timetable_subjects,
            message="Timetable subjects for selection fetched successfully"
        )

    except Exception as e:
        frappe.log_error(f"Error fetching timetable subjects for selection: {str(e)}")
        return {
            "success": False,
            "data": [],
            "message": f"Error fetching timetable subjects: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def get_subjects_for_timetable_selection():
    """Get subjects for timetable dropdown selection, filtered by education_stage_id"""
    try:
        # Get current user's campus information from roles
        campus_id = get_current_campus_from_context()

        if not campus_id:
            # Fallback to default if no campus found
            campus_id = "campus-1"
            frappe.logger().warning(f"No campus found for user {frappe.session.user}, using default: {campus_id}")

        # Get education_stage_id from request (try both form_dict and args for GET requests)
        education_stage_id = (
            frappe.local.form_dict.get("education_stage_id") or 
            frappe.request.args.get("education_stage_id")
        )

        filters = {"campus_id": campus_id}
        if education_stage_id:
            filters["education_stage"] = education_stage_id

        subjects = frappe.get_all(
            "SIS Subject",
            fields=["name", "title", "education_stage"],
            filters=filters,
            order_by="title asc"
        )

        return success_response(
            data=subjects,
            message="Subjects for timetable selection fetched successfully"
        )

    except Exception as e:
        frappe.log_error(f"Error fetching subjects for timetable selection: {str(e)}")
        return {
            "success": False,
            "data": [],
            "message": f"Error fetching subjects: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def get_rooms_for_selection():
    """Get all rooms for dropdown selection"""
    try:
        # Get current user's campus information from roles
        campus_id = get_current_campus_from_context()

        if not campus_id:
            # Fallback: try to get first available campus from database
            try:
                first_campus = frappe.db.get_value("SIS Campus", {}, "name", order_by="creation asc")
                campus_id = first_campus or "CAMPUS-00001"
            except Exception:
                # Final fallback to known campus
                campus_id = "CAMPUS-00001"
            frappe.logger().warning(f"No campus found for user {frappe.session.user}, using fallback: {campus_id}")

        # Get buildings for this campus to filter rooms
        building_filters = {"campus_id": campus_id}
        buildings = frappe.get_all(
            "ERP Administrative Building",
            fields=["name"],
            filters=building_filters
        )

        building_ids = [b.name for b in buildings]

        if not building_ids:
            return success_response(
                data=[],
                message="No buildings found for this campus"
            )

        # Get rooms that belong to buildings in this campus
        rooms = frappe.get_all(
            "ERP Administrative Room",
            fields=["name", "title_vn", "title_en", "short_title"],
            filters={"building_id": ["in", building_ids]},
            order_by="title_vn asc"
        )

        return success_response(
            data=rooms,
            message="Rooms for selection fetched successfully"
        )
        
    except Exception as e:
        frappe.log_error(f"Error fetching rooms for selection: {str(e)}")
        return {
            "success": False,
            "data": [],
            "message": f"Error fetching rooms: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def get_education_stages_for_selection():
    """Get education stages for dropdown selection"""
    try:
        # Debug: Log campus information

        # Get current user's campus information from roles
        campus_id = get_current_campus_from_context()

        if not campus_id:
            campus_id = "campus-1"

        filters = {"campus_id": campus_id}

        # First, check total count of education stages
        total_count = frappe.db.count("SIS Education Stage")

        # Check education stages with current campus
        campus_count = frappe.db.count("SIS Education Stage", filters)

        education_stages = frappe.get_all(
            "SIS Education Stage",
            fields=[
                "name",
                "title_vn",
                "title_en",
                "campus_id"
            ],
            filters=filters,
            order_by="title_vn asc"
        )

        if education_stages:
            pass
        else:

            # Try without campus filter to see if there are any education stages
            all_stages = frappe.get_all(
                "SIS Education Stage",
                fields=["name", "title_vn", "title_en", "campus_id"],
                limit=5
            )

            # If no stages at all, return all stages regardless of campus
            if not all_stages:
                print("No education stages found in database at all")
                education_stages = []
            else:
                print("Education stages exist but campus filter doesn't match")
                # Temporarily return all stages for testing
                education_stages = frappe.get_all(
                    "SIS Education Stage",
                    fields=["name", "title_vn", "title_en", "campus_id"],
                    order_by="title_vn asc"
                )
        
        return success_response(
            data=education_stages,
            message="Education stages fetched successfully"
        )
        
    except Exception as e:
        frappe.log_error(f"Error fetching education stages for selection: {str(e)}")
        return {
            "success": False,
            "data": [],
            "message": f"Error fetching education stages: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def get_timetable_subjects_for_selection():
    """Get timetable subjects for dropdown selection"""
    try:
        # Debug: Log campus information

        # Get current user's campus information from roles
        campus_id = get_current_campus_from_context()

        if not campus_id:
            campus_id = "campus-1"

        filters = {"campus_id": campus_id}

        # First, check total count
        total_count = frappe.db.count("SIS Timetable Subject")

        campus_count = frappe.db.count("SIS Timetable Subject", filters)

        timetable_subjects = frappe.db.sql("""
            SELECT 
                s.name,
                s.title_vn,
                s.title_en,
                s.campus_id,
                COALESCE(es.title_vn, '') as education_stage_name
            FROM `tabSIS Timetable Subject` s
            LEFT JOIN `tabSIS Education Stage` es ON s.education_stage_id = es.name
            WHERE s.campus_id = %(campus_id)s
            ORDER BY s.title_vn ASC
        """, {"campus_id": campus_id}, as_dict=True)

        if timetable_subjects:
            pass
        else:

            # Try without campus filter
            all_subjects = frappe.get_all(
                "SIS Timetable Subject",
                fields=["name", "title_vn", "title_en", "campus_id"],
                limit=5
            )

            # If no subjects at all, return empty
            if not all_subjects:
                print("No timetable subjects found in database at all")
                timetable_subjects = []
            else:
                print("Timetable subjects exist but campus filter doesn't match")
                # Temporarily return all subjects for testing
                timetable_subjects = frappe.db.sql("""
                    SELECT 
                        s.name,
                        s.title_vn,
                        s.title_en,
                        s.campus_id,
                        COALESCE(es.title_vn, '') as education_stage_name
                    FROM `tabSIS Timetable Subject` s
                    LEFT JOIN `tabSIS Education Stage` es ON s.education_stage_id = es.name
                    ORDER BY s.title_vn ASC
                """, as_dict=True)
        
        return success_response(
            data=timetable_subjects,
            message="Timetable subjects fetched successfully"
        )
        
    except Exception as e:
        frappe.log_error(f"Error fetching timetable subjects for selection: {str(e)}")
        return {
            "success": False,
            "data": [],
            "message": f"Error fetching timetable subjects: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def get_actual_subjects_for_selection():
    """Get actual subjects for dropdown selection"""
    try:
        # Debug: Log campus information

        # Get current user's campus information from roles
        campus_id = get_current_campus_from_context()

        if not campus_id:
            campus_id = "campus-1"

        # Get actual subjects for this campus
        filters = {
            "campus_id": campus_id
        }

        # First, check total count
        total_count = frappe.db.count("SIS Actual Subject")

        campus_count = frappe.db.count("SIS Actual Subject", {"campus_id": campus_id})

        actual_subjects = frappe.db.sql("""
            SELECT 
                s.name,
                s.title_vn,
                s.title_en,
                s.campus_id,
                COALESCE(es.title_vn, '') as education_stage_name
            FROM `tabSIS Actual Subject` s
            LEFT JOIN `tabSIS Education Stage` es ON s.education_stage_id = es.name
            WHERE s.campus_id = %(campus_id)s
            ORDER BY s.title_vn ASC
        """, {"campus_id": campus_id}, as_dict=True)

        if actual_subjects:
            pass
        else:

            # Try fetch again without extra filters
            all_subjects = frappe.get_all(
                "SIS Actual Subject",
                fields=["name", "title_vn", "title_en", "campus_id"],
                filters={"campus_id": campus_id},
                limit=5
            )

            # If no subjects at all, return empty
            if not all_subjects:
                print("No actual subjects found in database at all")
                actual_subjects = []
            else:
                print("Actual subjects exist but filter doesn't match")
                # Return all subjects for this campus
                actual_subjects = frappe.get_all(
                    "SIS Actual Subject",
                    fields=["name", "title_vn", "title_en", "campus_id"],
                    filters={"campus_id": campus_id},
                    order_by="title_vn asc"
                )
        
        return success_response(
            data=actual_subjects,
            message="Actual subjects fetched successfully"
        )
        
    except Exception as e:
        frappe.log_error(f"Error fetching actual subjects for selection: {str(e)}")
        return {
            "success": False,
            "data": [],
            "message": f"Error fetching actual subjects: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def get_rooms_for_selection():
    """Get rooms for dropdown selection"""
    try:
        # Get current user's campus information from roles
        campus_id = get_current_campus_from_context()

        if not campus_id:
            # Fallback: try to get first available campus from database
            try:
                first_campus = frappe.db.get_value("SIS Campus", {}, "name", order_by="creation asc")
                campus_id = first_campus or "CAMPUS-00001"
            except Exception:
                # Final fallback to known campus
                campus_id = "CAMPUS-00001"
        
        # Get buildings for this campus to filter rooms
        building_filters = {"campus_id": campus_id}
        buildings = frappe.get_all(
            "ERP Administrative Building",
            fields=["name"],
            filters=building_filters
        )
        
        building_ids = [b.name for b in buildings]
        
        if not building_ids:
            return success_response(
            data=[],
            message="No buildings found for this campus"
        )
        
        rooms = frappe.get_all(
            "ERP Administrative Room",
            fields=[
                "name",
                "title_vn",
                "title_en",
                "short_title"
            ],
            filters={"building_id": ["in", building_ids]},
            order_by="title_vn asc"
        )
        
        return success_response(
            data=rooms,
            message="Rooms fetched successfully"
        )
        
    except Exception as e:
        frappe.log_error(f"Error fetching rooms for selection: {str(e)}")
        return {
            "success": False,
            "data": [],
            "message": f"Error fetching rooms: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def bulk_import_subjects():
    """Bulk import subjects from Excel file"""
    try:
        # Get file from request
        import io
        import pandas as pd
        from werkzeug.datastructures import FileStorage
        
        # Get uploaded file
        uploaded_file = frappe.request.files.get('file')
        if not uploaded_file:
            return error_response(
                message="No file uploaded",
                code="NO_FILE_UPLOADED"
            )
        
        frappe.logger().info(f"Subject bulk import file received: {uploaded_file.filename}")
        
        # Read Excel file
        try:
            df = pd.read_excel(uploaded_file, sheet_name=0)
            frappe.logger().info(f"Excel file read successfully. Shape: {df.shape}")
        except Exception as e:
            return error_response(
                message=f"Error reading Excel file: {str(e)}",
                code="EXCEL_READ_ERROR"
            )
        
        # Log available columns for debugging
        frappe.logger().info(f"Excel columns found: {list(df.columns)}")
        
        # Validate required columns
        required_columns = ['title', 'education_stage']
        optional_columns = ['timetable_subject', 'actual_subject', 'subcurriculum', 'room']
        
        # Check for required columns (case insensitive)
        missing_columns = []
        for req_col in required_columns:
            if req_col not in df.columns:
                # Try case insensitive match
                found = False
                for col in df.columns:
                    if col.lower().replace(' ', '').replace('_', '') == req_col.lower().replace(' ', '').replace('_', ''):
                        found = True
                        break
                if not found:
                    missing_columns.append(req_col)
        
        if missing_columns:
            return error_response(
                message=f"Missing required columns: {', '.join(missing_columns)}. Found columns: {', '.join(df.columns)}",
                code="MISSING_COLUMNS"
            )
        
        # Get current campus
        campus_id = get_current_campus_from_context()
        if not campus_id:
            campus_id = "campus-1"
        
        # Get existing subjects to check for uniqueness
        existing_subjects = frappe.get_all(
            "SIS Subject",
            fields=["name", "title", "education_stage"],
            filters={"campus_id": campus_id},
            order_by="creation asc"
        )
        
        existing_titles_per_stage = {}
        for subj in existing_subjects:
            stage = subj.get('education_stage', '')  # This is already the ID
            title = subj.get('title', '').lower()
            if stage not in existing_titles_per_stage:
                existing_titles_per_stage[stage] = set()
            existing_titles_per_stage[stage].add(title)
        
        # Process each row
        success_count = 0
        error_count = 0
        errors = []
        logs = []
        
        for index, row in df.iterrows():
            try:
                # Extract data from row
                title = str(row.get('title', '')).strip() if pd.notna(row.get('title')) else ''
                education_stage = str(row.get('education_stage', '')).strip() if pd.notna(row.get('education_stage')) else ''
                
                # Optional fields - get names, then lookup IDs
                timetable_subject_name = str(row.get('timetable_subject', '')).strip() if pd.notna(row.get('timetable_subject')) else None
                actual_subject_name = str(row.get('actual_subject', '')).strip() if pd.notna(row.get('actual_subject')) else None
                subcurriculum_name = str(row.get('subcurriculum', '')).strip() if pd.notna(row.get('subcurriculum')) else None
                room_name = str(row.get('room', '')).strip() if pd.notna(row.get('room')) else None
                
                # Clean up extra spaces
                if education_stage:
                    education_stage = ' '.join(education_stage.split())
                if timetable_subject_name:
                    timetable_subject_name = ' '.join(timetable_subject_name.split())
                if actual_subject_name:
                    actual_subject_name = ' '.join(actual_subject_name.split())
                if subcurriculum_name:
                    subcurriculum_name = ' '.join(subcurriculum_name.split())
                if room_name:
                    room_name = ' '.join(room_name.split())
                
                frappe.logger().info(f"Processing row {index + 2}: Title='{title}', Education Stage='{education_stage}'")
                
                # Validation
                if not title:
                    error_count += 1
                    error_msg = f"Row {index + 2}: Title is required"
                    errors.append(error_msg)
                    logs.append(error_msg)
                    continue
                
                if not education_stage:
                    error_count += 1
                    error_msg = f"Row {index + 2}: Education stage is required"
                    errors.append(error_msg)
                    logs.append(error_msg)
                    continue
                
                # Lookup education stage ID from title_vn
                education_stage_doc = frappe.db.get_value(
                    "SIS Education Stage",
                    {
                        "title_vn": education_stage,
                        "campus_id": campus_id
                    },
                    "name"
                )
                
                # If not found, try case insensitive search
                if not education_stage_doc:
                    all_stages = frappe.db.get_all(
                        "SIS Education Stage",
                        filters={"campus_id": campus_id},
                        fields=["name", "title_vn"]
                    )
                    
                    for stage in all_stages:
                        if stage.get('title_vn', '').lower().strip() == education_stage.lower().strip():
                            education_stage_doc = stage.get('name')
                            logs.append(f"Row {index + 2}: Found education stage '{education_stage}' with case insensitive match")
                            break
                
                if not education_stage_doc:
                    # Log available stages for debugging
                    available_stages = [stage.get('title_vn', '') for stage in frappe.db.get_all(
                        "SIS Education Stage",
                        filters={"campus_id": campus_id},
                        fields=["title_vn"]
                    )]
                    error_count += 1
                    error_msg = f"Row {index + 2}: Education stage '{education_stage}' does not exist. Available: {', '.join(available_stages[:5])}{'...' if len(available_stages) > 5 else ''}"
                    errors.append(error_msg)
                    logs.append(error_msg)
                    continue
                
                # Check title uniqueness within the same education stage
                if education_stage_doc in existing_titles_per_stage and title.lower() in existing_titles_per_stage[education_stage_doc]:
                    error_count += 1
                    error_msg = f"Row {index + 2}: Subject title '{title}' already exists in education stage '{education_stage}'"
                    errors.append(error_msg)
                    logs.append(error_msg)
                    continue
                
                # Lookup optional fields IDs from names
                timetable_subject_id = None
                if timetable_subject_name and timetable_subject_name != 'nan':
                    timetable_subject_id = frappe.db.get_value(
                        "SIS Timetable Subject",
                        {
                            "title_vn": timetable_subject_name,
                            "campus_id": campus_id
                        },
                        "name"
                    )
                    if not timetable_subject_id:
                        logs.append(f"Row {index + 2}: Warning - Timetable subject '{timetable_subject_name}' not found, skipping")
                
                actual_subject_id = None
                if actual_subject_name and actual_subject_name != 'nan':
                    actual_subject_id = frappe.db.get_value(
                        "SIS Actual Subject",
                        {
                            "title_vn": actual_subject_name,
                            "campus_id": campus_id
                        },
                        "name"
                    )
                    if not actual_subject_id:
                        logs.append(f"Row {index + 2}: Warning - Actual subject '{actual_subject_name}' not found, skipping")
                
                subcurriculum_id = None
                if subcurriculum_name and subcurriculum_name != 'nan':
                    subcurriculum_id = frappe.db.get_value(
                        "SIS Sub Curriculum",
                        {
                            "title_vn": subcurriculum_name,
                            "campus_id": campus_id
                        },
                        "name"
                    )
                    if not subcurriculum_id:
                        logs.append(f"Row {index + 2}: Warning - Subcurriculum '{subcurriculum_name}' not found, skipping")
                
                room_id = None
                if room_name and room_name != 'nan':
                    room_id = frappe.db.get_value(
                        "ERP Administrative Room",
                        {
                            "title_vn": room_name
                        },
                        "name"
                    )
                    if not room_id:
                        logs.append(f"Row {index + 2}: Warning - Room '{room_name}' not found, skipping")
                
                # Build subject data
                subject_data = {
                    "doctype": "SIS Subject",
                    "title": title,
                    "education_stage": education_stage_doc,
                    "campus_id": campus_id
                }
                
                # Add optional fields if IDs were found
                if timetable_subject_id:
                    subject_data["timetable_subject_id"] = timetable_subject_id
                if actual_subject_id:
                    subject_data["actual_subject_id"] = actual_subject_id
                if subcurriculum_id:
                    subject_data["subcurriculum_id"] = subcurriculum_id
                if room_id:
                    subject_data["room_id"] = room_id
                
                # Create subject
                subject_doc = frappe.get_doc(subject_data)
                
                subject_doc.flags.ignore_validate = True
                subject_doc.flags.ignore_permissions = True
                subject_doc.insert(ignore_permissions=True)
                
                # Track this creation for uniqueness checking in subsequent rows
                if education_stage_doc not in existing_titles_per_stage:
                    existing_titles_per_stage[education_stage_doc] = set()
                existing_titles_per_stage[education_stage_doc].add(title.lower())
                
                success_count += 1
                logs.append(f"Row {index + 2}: Successfully created subject '{title}'")
                
            except Exception as e:
                error_count += 1
                error_msg = f"Row {index + 2}: Error creating subject: {str(e)}"
                errors.append(error_msg)
                logs.append(error_msg)
        
        # Commit all changes
        frappe.db.commit()
        
        # Prepare response
        total_rows = len(df)
        is_success = success_count > 0
        
        response_data = {
            "total_rows": total_rows,
            "success_count": success_count,
            "error_count": error_count,
            "errors": errors[:10],  # Limit errors in response
            "logs": logs[-20:],  # Last 20 logs
        }
        
        if is_success:
            return success_response(
                data=response_data,
                message=f"Bulk import completed. {success_count} subjects created, {error_count} errors."
            )
        else:
            return error_response(
                data=response_data,
                message=f"Bulk import failed. {error_count} errors occurred.",
                code="BULK_IMPORT_FAILED"
            )
            
    except Exception as e:
        frappe.log_error(f"Error in bulk import subjects: {str(e)}", "Subject Bulk Import Error")
        return error_response(
            message=f"Error in bulk import subjects: {str(e)}",
            code="BULK_IMPORT_ERROR"
        )
