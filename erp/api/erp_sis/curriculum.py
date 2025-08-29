# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import nowdate, get_datetime
import json
from erp.utils.campus_utils import get_current_campus_from_context, get_campus_id_from_user_roles
from erp.utils.api_response import (
    success_response, error_response, list_response,
    single_item_response, validation_error_response,
    not_found_response, forbidden_response
)


@frappe.whitelist(allow_guest=False)
def get_all_curriculums():
    """Get all curriculums with basic information - SIMPLE VERSION"""
    try:
        # Get current user's campus information from roles
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            # Fallback to default if no campus found
            campus_id = "campus-1"
            frappe.logger().warning(f"No campus found for user {frappe.session.user}, using default: {campus_id}")
        
        filters = {"campus_id": campus_id}
            
        curriculums = frappe.get_all(
            "SIS Curriculum",
            fields=[
                "name",
                "title_vn",
                "title_en",
                "short_title",
                "academic_program_id",
                "education_stage_id",
                "campus_id",
                "creation",
                "modified"
            ],
            filters=filters,
            order_by="title_vn asc"
        )
        
        return list_response(
            data=curriculums,
            message="Curriculums fetched successfully"
        )
        
    except Exception as e:
        frappe.log_error(f"Error fetching curriculums: {str(e)}")
        return error_response(
            message="Error fetching curriculums",
            code="FETCH_CURRICULUMS_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def get_curriculum_by_id():
    """Get a specific curriculum by ID"""
    try:
       

        # Get curriculum_id from multiple sources (form data or JSON payload)
        curriculum_id = None

        # Try from form_dict first (for FormData/URLSearchParams)
        curriculum_id = frappe.form_dict.get('curriculum_id')
        print(f"Curriculum ID from form_dict: {curriculum_id}")

        # If not found, try from JSON payload
        if not curriculum_id and frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
                curriculum_id = json_data.get('curriculum_id')
                print(f"Curriculum ID from JSON payload: {curriculum_id}")
            except (json.JSONDecodeError, TypeError, AttributeError, UnicodeDecodeError) as e:
                print(f"JSON parsing failed: {e}")

        print(f"Final curriculum_id: {repr(curriculum_id)}")

        if not curriculum_id:
            return error_response(
                message="Curriculum ID is required",
                code="MISSING_CURRICULUM_ID"
            )
        
        # Get current user's campus
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
            
        filters = {
            "name": curriculum_id,
            "campus_id": campus_id
        }
        
        curriculum = frappe.get_doc("SIS Curriculum", filters)
        
        if not curriculum:
            return not_found_response(
                message="Curriculum not found or access denied",
                code="CURRICULUM_NOT_FOUND"
            )
        
        return single_item_response(
            data={
                "name": curriculum.name,
                "title_vn": curriculum.title_vn,
                "title_en": curriculum.title_en,
                "short_title": curriculum.short_title,
                "academic_program_id": curriculum.academic_program_id,
                "education_stage_id": curriculum.education_stage_id,
                "campus_id": curriculum.campus_id,
                "creation": curriculum.creation,
                "modified": curriculum.modified
            },
            message="Curriculum fetched successfully"
        )
        
    except Exception as e:
        frappe.log_error(f"Error fetching curriculum {curriculum_id}: {str(e)}")
        return error_response(
            message="Error fetching curriculum",
            code="FETCH_CURRICULUM_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def create_curriculum():
    """Create a new curriculum - SIMPLE VERSION"""
    try:
        # Get data from request - follow Education Stage pattern
        data = {}
        
        # First try to get JSON data from request body
        if frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data)
                if json_data:
                    data = json_data
                    frappe.logger().info(f"Received JSON data for create_curriculum: {data}")
                else:
                    data = frappe.local.form_dict
                    frappe.logger().info(f"Received form data for create_curriculum: {data}")
            except (json.JSONDecodeError, TypeError):
                # If JSON parsing fails, use form_dict
                data = frappe.local.form_dict
                frappe.logger().info(f"JSON parsing failed, using form data for create_curriculum: {data}")
        else:
            # Fallback to form_dict
            data = frappe.local.form_dict
            frappe.logger().info(f"No request data, using form_dict for create_curriculum: {data}")
        
        # Extract values from data
        title_vn = data.get("title_vn")
        title_en = data.get("title_en")
        short_title = data.get("short_title")
        
        # Input validation
        if not title_vn or not short_title:
            return validation_error_response(
                message="Title VN and short title are required",
                errors={
                    "title_vn": ["Required"] if not title_vn else [],
                    "short_title": ["Required"] if not short_title else []
                }
            )
        
        # Get campus from user context - simplified
        try:
            campus_id = get_current_campus_from_context()
        except Exception as e:
            frappe.logger().error(f"Error getting campus context: {str(e)}")
            campus_id = None
        
        if not campus_id:
            # Get first available campus instead of hardcoded campus-1
            first_campus = frappe.get_all("SIS Campus", fields=["name"], limit=1)
            if first_campus:
                campus_id = first_campus[0].name
                frappe.logger().warning(f"No campus found for user {frappe.session.user}, using first available: {campus_id}")
            else:
                # Create default campus if none exists
                default_campus = frappe.get_doc({
                    "doctype": "SIS Campus",
                    "title_vn": "Trường Mặc Định",
                    "title_en": "Default Campus"
                })
                default_campus.insert()
                frappe.db.commit()
                campus_id = default_campus.name
                frappe.logger().info(f"Created default campus: {campus_id}")
        
        # Check if curriculum title already exists for this campus
        existing = frappe.db.exists(
            "SIS Curriculum",
            {
                "title_vn": title_vn,
                "campus_id": campus_id
            }
        )
        
        if existing:
            return error_response(
                message=f"Curriculum with title '{title_vn}' already exists",
                code="CURRICULUM_EXISTS"
            )

        # Check if short title already exists for this campus
        existing_code = frappe.db.exists(
            "SIS Curriculum",
            {
                "short_title": short_title,
                "campus_id": campus_id
            }
        )

        if existing_code:
            return error_response(
                message=f"Curriculum with short title '{short_title}' already exists",
                code="SHORT_TITLE_EXISTS"
            )
        
        # Create new curriculum - with detailed debugging
        frappe.logger().info(f"Creating SIS Curriculum with data: title_vn={title_vn}, title_en={title_en}, short_title={short_title}, campus_id={campus_id}")
        
        try:
            curriculum_doc = frappe.get_doc({
                "doctype": "SIS Curriculum",
                "title_vn": title_vn,
                "title_en": title_en or "",  # Provide default empty string
                "short_title": short_title,
                "campus_id": campus_id
            })
            
            frappe.logger().info(f"Curriculum doc created: {curriculum_doc}")
            
            curriculum_doc.insert()
            frappe.logger().info("Curriculum doc inserted successfully")
            
            frappe.db.commit()
            frappe.logger().info("Database committed successfully")
            
        except Exception as doc_error:
            frappe.logger().error(f"Error creating/inserting curriculum doc: {str(doc_error)}")
            raise doc_error
        
        # Return the created data - follow Education Stage pattern
        frappe.msgprint(_("Curriculum created successfully"))
        return single_item_response(
            data={
                "name": curriculum_doc.name,
                "title_vn": curriculum_doc.title_vn,
                "title_en": curriculum_doc.title_en,
                "short_title": curriculum_doc.short_title,
                "campus_id": curriculum_doc.campus_id
            },
            message="Curriculum created successfully"
        )
        
    except Exception as e:
        frappe.log_error(f"Error creating curriculum: {str(e)}")
        return error_response(
            message="Error creating curriculum",
            code="CREATE_CURRICULUM_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def update_curriculum():
    """Update an existing curriculum"""
    try:
       

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

        curriculum_id = data.get('curriculum_id')
        print(f"Final curriculum_id: {repr(curriculum_id)}")

        if not curriculum_id:
            return {
                "success": False,
                "message": "Curriculum ID is required",
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
            curriculum_doc = frappe.get_doc("SIS Curriculum", curriculum_id)
            
            # Check campus permission
            if curriculum_doc.campus_id != campus_id:
                                    return forbidden_response(
                        message="Access denied: You don't have permission to modify this curriculum",
                        code="ACCESS_DENIED"
                    )
                
        except frappe.DoesNotExistError:
            return {
                "success": False,
                "data": {},
                "message": "Curriculum not found"
            }
        
        # Update fields if provided
        title_vn = data.get('title_vn')
        title_en = data.get('title_en')
        short_title = data.get('short_title')

        print(f"Updating with: title_vn={title_vn}, title_en={title_en}, short_title={short_title}")

        if title_vn and title_vn != curriculum_doc.title_vn:
            # Check for duplicate curriculum title
            existing = frappe.db.exists(
                "SIS Curriculum",
                {
                    "title_vn": title_vn,
                    "campus_id": campus_id,
                    "name": ["!=", curriculum_id]
                }
            )
            if existing:
                return error_response(
                    message=f"Curriculum with title '{title_vn}' already exists",
                    code="CURRICULUM_EXISTS"
                )
            curriculum_doc.title_vn = title_vn

        if title_en and title_en != curriculum_doc.title_en:
            curriculum_doc.title_en = title_en

        if short_title and short_title != curriculum_doc.short_title:
            # Check for duplicate short title
            existing_code = frappe.db.exists(
                "SIS Curriculum",
                {
                    "short_title": short_title,
                    "campus_id": campus_id,
                    "name": ["!=", curriculum_id]
                }
            )
            if existing_code:
                return error_response(
                    message=f"Curriculum with short title '{short_title}' already exists",
                    code="SHORT_TITLE_EXISTS"
                )
            curriculum_doc.short_title = short_title
        
        curriculum_doc.save()
        frappe.db.commit()
        
        return single_item_response(
            data={
                "name": curriculum_doc.name,
                "title_vn": curriculum_doc.title_vn,
                "title_en": curriculum_doc.title_en,
                "short_title": curriculum_doc.short_title,
                "campus_id": curriculum_doc.campus_id
            },
            message="Curriculum updated successfully"
        )
        
    except Exception as e:
        frappe.log_error(f"Error updating curriculum {curriculum_id}: {str(e)}")
        return error_response(
            message="Error updating curriculum",
            code="UPDATE_CURRICULUM_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def delete_curriculum():
    """Delete a curriculum"""
    try:
       

        # Get curriculum_id from multiple sources (form data or JSON payload)
        curriculum_id = None

        # Try from form_dict first (for FormData/URLSearchParams)
        curriculum_id = frappe.form_dict.get('curriculum_id')
        print(f"Curriculum ID from form_dict: {curriculum_id}")

        # If not found, try from JSON payload
        if not curriculum_id and frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
                curriculum_id = json_data.get('curriculum_id')
                print(f"Curriculum ID from JSON payload: {curriculum_id}")
            except (json.JSONDecodeError, TypeError, AttributeError, UnicodeDecodeError) as e:
                print(f"JSON parsing failed: {e}")

        print(f"Final curriculum_id: {repr(curriculum_id)}")

        if not curriculum_id:
            return error_response(
                message="Curriculum ID is required",
                code="MISSING_CURRICULUM_ID"
            )
        
        # Get campus from user context
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
        
        # Get existing document
        try:
            curriculum_doc = frappe.get_doc("SIS Curriculum", curriculum_id)

            # Check campus permission
            if curriculum_doc.campus_id != campus_id:
                return forbidden_response(
                    message="Access denied: You don't have permission to delete this curriculum",
                    code="ACCESS_DENIED"
                )

        except frappe.DoesNotExistError:
            return not_found_response(
                message="Curriculum not found",
                code="CURRICULUM_NOT_FOUND"
            )

        # Check for linked documents before deletion
        linked_docs = []
        try:
            # Check Actual Subject links
            actual_subject_count = frappe.db.count("SIS Actual Subject", {"curriculum_id": curriculum_id})
            if actual_subject_count > 0:
                linked_docs.append(f"{actual_subject_count} môn học thực tế")

            # Check Subject links
            subject_count = frappe.db.count("SIS Subject", {"curriculum_id": curriculum_id})
            if subject_count > 0:
                linked_docs.append(f"{subject_count} môn học")

            if linked_docs:
                return error_response(
                    message=f"Không thể xóa chương trình học vì đang được liên kết với {', '.join(linked_docs)}. Vui lòng xóa hoặc chuyển các mục liên kết sang chương trình học khác trước.",
                    code="CURRICULUM_LINKED"
                )

            # Delete the document
            frappe.delete_doc("SIS Curriculum", curriculum_id)
            frappe.db.commit()

            return success_response(
                message="Curriculum deleted successfully"
            )

        except frappe.LinkExistsError as e:
            return error_response(
                message=f"Không thể xóa chương trình học vì đang được sử dụng bởi các module khác. Chi tiết: {str(e)}",
                code="CURRICULUM_LINKED"
            )
        except Exception as e:
            frappe.log_error(f"Unexpected error during deletion: {str(e)}")
            return error_response(
                message="Lỗi không mong muốn khi xóa chương trình học",
                code="DELETE_CURRICULUM_ERROR"
            )
        
    except Exception as e:
        frappe.log_error(f"Error deleting curriculum {curriculum_id}: {str(e)}")
        return error_response(
            message="Error deleting curriculum",
            code="DELETE_CURRICULUM_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def check_short_title_availability():
    """Check if short title is available"""
    try:
        

        # Get parameters from multiple sources (form data or JSON payload)
        short_title = None
        curriculum_id = None

        # Try from form_dict first (for FormData/URLSearchParams)
        short_title = frappe.form_dict.get('short_title')
        curriculum_id = frappe.form_dict.get('curriculum_id')
        print(f"Parameters from form_dict: short_title={short_title}, curriculum_id={curriculum_id}")

        # If not found, try from JSON payload
        if not short_title and frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
                short_title = json_data.get('short_title')
                curriculum_id = json_data.get('curriculum_id')
                print(f"Parameters from JSON payload: short_title={short_title}, curriculum_id={curriculum_id}")
            except (json.JSONDecodeError, TypeError, AttributeError, UnicodeDecodeError) as e:
                print(f"JSON parsing failed: {e}")

        if not short_title:
            return error_response(
                message="Short title is required",
                code="MISSING_SHORT_TITLE"
            )
        
        # Get campus from user context  
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
        
        filters = {
            "short_title": short_title,
            "campus_id": campus_id
        }
        
        # If updating existing curriculum, exclude it from check
        if curriculum_id:
            filters["name"] = ["!=", curriculum_id]
        
        existing = frappe.db.exists("SIS Curriculum", filters)
        
        is_available = not bool(existing)
        
        return success_response(
            data={
                "is_available": is_available,
                "short_title": short_title
            },
            message="Available" if is_available else "Short title already exists"
        )
        
    except Exception as e:
        frappe.log_error(f"Error checking short title availability: {str(e)}")
        return error_response(
            message="Error checking short title availability",
            code="CHECK_AVAILABILITY_ERROR"
        )
