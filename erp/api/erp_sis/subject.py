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
            
        # Use SQL query to join with related tables for proper display names
        subjects_query = """
            SELECT
                s.name,
                s.title_vn,
                s.title_en,
                s.short_title,
                s.education_stage,
                s.academic_program_id,
                s.curriculum_id,
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
            ORDER BY s.title_vn ASC
        """
        
        # Try to get subjects with error handling
        try:
            subjects = frappe.db.sql(subjects_query, (campus_id,), as_dict=True)
            frappe.logger().info(f"Found {len(subjects)} subjects")

            # Debug: Print first few subjects to check data
            frappe.logger().info("=== DEBUG get_all_subjects ===")
            frappe.logger().info(f"Campus ID: {campus_id}")
            frappe.logger().info(f"Number of subjects: {len(subjects)}")
            if subjects:
                frappe.logger().info(f"First subject: {subjects[0]}")
                frappe.logger().info(f"Subject fields: {list(subjects[0].keys())}")
        except Exception as db_error:
            frappe.logger().error(f"Database error: {str(db_error)}")
            import traceback
            frappe.logger().error(f"Database error traceback: {traceback.format_exc()}")
            return error_response(
                message=f"Database error: {str(db_error)}",
                code="DATABASE_ERROR"
            )

        return list_response(subjects, "Subjects fetched successfully")
        
    except Exception as e:
        frappe.log_error(f"Error fetching subjects: {str(e)}")
        return error_response(f"Error fetching subjects: {str(e)}")


@frappe.whitelist(allow_guest=False)
def get_subject_by_id():
    """Get a specific subject by ID"""
    try:
        # Debug: Print all request data
        print("=== DEBUG get_subject_by_id ===")
        print(f"Request method: {frappe.request.method}")
        print(f"Content-Type: {frappe.request.headers.get('Content-Type', 'Not set')}")
        print(f"Form dict: {dict(frappe.form_dict)}")
        print(f"Request data: {frappe.request.data}")

        # Get subject_id from multiple sources (form data or JSON payload)
        subject_id = None

        # Try from form_dict first (for FormData/URLSearchParams)
        subject_id = frappe.form_dict.get('subject_id')
        print(f"Subject ID from form_dict: {subject_id}")

        # If not found, try from JSON payload
        if not subject_id and frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
                subject_id = json_data.get('subject_id')
                print(f"Subject ID from JSON payload: {subject_id}")
            except (json.JSONDecodeError, TypeError, AttributeError, UnicodeDecodeError) as e:
                print(f"JSON parsing failed: {e}")

        print(f"Final subject_id: {repr(subject_id)}")

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
        room_id = data.get("room_id")  # Can be None if not provided

        print("=== DEBUG create_subject extracted data ===")
        print(f"title: {title}")
        print(f"education_stage: {education_stage}")
        print(f"timetable_subject_id: {timetable_subject_id}")
        print(f"actual_subject_id: {actual_subject_id}")
        print(f"room_id: {room_id}")
        
        # Input validation
        if not title or not education_stage:
            frappe.throw(_("Title and education stage are required"))
        
        # Get campus from user context
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
            frappe.logger().warning(f"No campus found for user {frappe.session.user}, using default: {campus_id}")
        
        # Check if subject title already exists for this campus
        existing = frappe.db.exists(
            "SIS Subject",
            {
                "title": title,
                "campus_id": campus_id
            }
        )
        
        if existing:
            frappe.throw(_(f"Subject with title '{title}' already exists"))
        
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

        print("=== DEBUG subject_data to create ===")
        print(subject_data)

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
        if subject_doc.room_id:
            try:
                room_doc = frappe.get_doc("ERP Administrative Room", subject_doc.room_id)
                room_name = room_doc.title_vn
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
        print("=== DEBUG update_subject ===")
        print(f"Request method: {frappe.request.method}")
        print(f"Content-Type: {frappe.request.headers.get('Content-Type', 'Not set')}")
        print(f"Form dict: {dict(frappe.form_dict)}")
        print(f"Request data: {frappe.request.data}")

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
                print(f"Merged JSON data: {json_data}")
            except (json.JSONDecodeError, TypeError, AttributeError, UnicodeDecodeError) as e:
                print(f"JSON data merge failed: {e}")

        subject_id = data.get('subject_id')
        print(f"Final subject_id: {repr(subject_id)}")

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
        room_id = data.get('room_id')

        print(f"Updating with: title={title}, education_stage={education_stage}, timetable_subject_id={timetable_subject_id}, actual_subject_id={actual_subject_id}, room_id={room_id}")
        print(f"Request data keys: {list(data.keys())}")

        if title and title != subject_doc.title:
            # Check for duplicate subject title
            existing = frappe.db.exists(
                "SIS Subject",
                {
                    "title": title,
                    "campus_id": campus_id,
                    "name": ["!=", subject_id]
                }
            )
            if existing:
                return {
                    "success": False,
                    "data": {},
                    "message": f"Subject with title '{title}' already exists"
                }
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
            print(f"Updating timetable_subject_id: {subject_doc.timetable_subject_id} -> {timetable_subject_id}")
            subject_doc.timetable_subject_id = timetable_subject_id

        if 'actual_subject_id' in data and actual_subject_id != subject_doc.actual_subject_id:
            print(f"Updating actual_subject_id: {subject_doc.actual_subject_id} -> {actual_subject_id}")
            subject_doc.actual_subject_id = actual_subject_id

        if 'room_id' in data and room_id != subject_doc.room_id:
            print(f"Updating room_id: {subject_doc.room_id} -> {room_id}")
            subject_doc.room_id = room_id
        
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
        print("=== DEBUG delete_subject ===")
        print(f"Request method: {frappe.request.method}")
        print(f"Content-Type: {frappe.request.headers.get('Content-Type', 'Not set')}")
        print(f"Form dict: {dict(frappe.form_dict)}")
        print(f"Request data: {frappe.request.data}")

        # Get subject_id from multiple sources (form data or JSON payload)
        subject_id = None

        # Try from form_dict first (for FormData/URLSearchParams)
        subject_id = frappe.form_dict.get('subject_id')
        print(f"Subject ID from form_dict: {subject_id}")

        # If not found, try from JSON payload
        if not subject_id and frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
                subject_id = json_data.get('subject_id')
                print(f"Subject ID from JSON payload: {subject_id}")
            except (json.JSONDecodeError, TypeError, AttributeError, UnicodeDecodeError) as e:
                print(f"JSON parsing failed: {e}")

        print(f"Final subject_id: {repr(subject_id)}")

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
            
        actual_subjects = frappe.get_all(
            "SIS Actual Subject",
            fields=["name", "title_vn", "title_en"],
            filters=filters,
            order_by="title_vn asc"
        )
        
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
            
        timetable_subjects = frappe.get_all(
            "SIS Timetable Subject",
            fields=["name", "title_vn", "title_en"],
            filters=filters,
            order_by="title_vn asc"
        )
        
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
def get_rooms_for_selection():
    """Get all rooms for dropdown selection"""
    try:
        # Get current user's campus information from roles
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            # Fallback to default if no campus found
            campus_id = "campus-1"
            frappe.logger().warning(f"No campus found for user {frappe.session.user}, using default: {campus_id}")
        
        filters = {"campus_id": campus_id}
            
        rooms = frappe.get_all(
            "ERP Administrative Room",
            fields=["name", "title_vn", "title_en", "short_title"],
            filters=filters,
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
        print("=== DEBUG get_education_stages_for_selection ===")

        # Get current user's campus information from roles
        campus_id = get_current_campus_from_context()
        print(f"Campus ID from context: {campus_id}")

        if not campus_id:
            campus_id = "campus-1"
            print(f"Using default campus: {campus_id}")

        filters = {"campus_id": campus_id}
        print(f"Filters: {filters}")

        # First, check total count of education stages
        total_count = frappe.db.count("SIS Education Stage")
        print(f"Total education stages in database: {total_count}")

        # Check education stages with current campus
        campus_count = frappe.db.count("SIS Education Stage", filters)
        print(f"Education stages with campus {campus_id}: {campus_count}")

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

        print(f"Query result count: {len(education_stages)}")
        if education_stages:
            print(f"First education stage: {education_stages[0]}")
        else:
            print("No education stages found with current campus filter")
            # Try without campus filter to see if there are any education stages
            all_stages = frappe.get_all(
                "SIS Education Stage",
                fields=["name", "title_vn", "title_en", "campus_id"],
                limit=5
            )
            print(f"All education stages (first 5): {all_stages}")

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
                print(f"Returning all stages for testing: {len(education_stages)}")
        
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
        print("=== DEBUG get_timetable_subjects_for_selection ===")

        # Get current user's campus information from roles
        campus_id = get_current_campus_from_context()
        print(f"Campus ID from context: {campus_id}")

        if not campus_id:
            campus_id = "campus-1"
            print(f"Using default campus: {campus_id}")

        filters = {"campus_id": campus_id}
        print(f"Filters: {filters}")

        # First, check total count
        total_count = frappe.db.count("SIS Timetable Subject")
        print(f"Total timetable subjects in database: {total_count}")

        campus_count = frappe.db.count("SIS Timetable Subject", filters)
        print(f"Timetable subjects with campus {campus_id}: {campus_count}")

        timetable_subjects = frappe.get_all(
            "SIS Timetable Subject",
            fields=[
                "name",
                "title_vn",
                "title_en",
                "campus_id"
            ],
            filters=filters,
            order_by="title_vn asc"
        )

        print(f"Query result count: {len(timetable_subjects)}")
        if timetable_subjects:
            print(f"First timetable subject: {timetable_subjects[0]}")
        else:
            print("No timetable subjects found with current campus filter")
            # Try without campus filter
            all_subjects = frappe.get_all(
                "SIS Timetable Subject",
                fields=["name", "title_vn", "title_en", "campus_id"],
                limit=5
            )
            print(f"All timetable subjects (first 5): {all_subjects}")

            # If no subjects at all, return empty
            if not all_subjects:
                print("No timetable subjects found in database at all")
                timetable_subjects = []
            else:
                print("Timetable subjects exist but campus filter doesn't match")
                # Temporarily return all subjects for testing
                timetable_subjects = frappe.get_all(
                    "SIS Timetable Subject",
                    fields=["name", "title_vn", "title_en", "campus_id"],
                    order_by="title_vn asc"
                )
                print(f"Returning all timetable subjects for testing: {len(timetable_subjects)}")
        
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
        print("=== DEBUG get_actual_subjects_for_selection ===")

        # Get current user's campus information from roles
        campus_id = get_current_campus_from_context()
        print(f"Campus ID from context: {campus_id}")

        if not campus_id:
            campus_id = "campus-1"
            print(f"Using default campus: {campus_id}")

        # Get actual subjects for this campus
        filters = {
            "campus_id": campus_id,
            "curriculum_id": ["!=", ""]  # Ensure it has a curriculum
        }
        print(f"Filters: {filters}")

        # First, check total count
        total_count = frappe.db.count("SIS Actual Subject")
        print(f"Total actual subjects in database: {total_count}")

        campus_count = frappe.db.count("SIS Actual Subject", {"campus_id": campus_id})
        print(f"Actual subjects with campus {campus_id}: {campus_count}")

        actual_subjects = frappe.get_all(
            "SIS Actual Subject",
            fields=[
                "name",
                "title_vn",
                "title_en",
                "campus_id",
                "curriculum_id"
            ],
            filters=filters,
            order_by="title_vn asc"
        )

        print(f"Query result count: {len(actual_subjects)}")
        if actual_subjects:
            print(f"First actual subject: {actual_subjects[0]}")
        else:
            print("No actual subjects found with current filters")
            # Try without curriculum filter
            all_subjects = frappe.get_all(
                "SIS Actual Subject",
                fields=["name", "title_vn", "title_en", "campus_id", "curriculum_id"],
                filters={"campus_id": campus_id},
                limit=5
            )
            print(f"Actual subjects with campus only (first 5): {all_subjects}")

            # If no subjects at all, return empty
            if not all_subjects:
                print("No actual subjects found in database at all")
                actual_subjects = []
            else:
                print("Actual subjects exist but curriculum filter doesn't match")
                # Temporarily return all subjects for testing
                actual_subjects = frappe.get_all(
                    "SIS Actual Subject",
                    fields=["name", "title_vn", "title_en", "campus_id", "curriculum_id"],
                    filters={"campus_id": campus_id},
                    order_by="title_vn asc"
                )
                print(f"Returning all actual subjects for testing: {len(actual_subjects)}")
        
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
            campus_id = "campus-1"
        
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
