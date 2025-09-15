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
def get_all_actual_subjects():
    """Get all actual subjects with basic information - SIMPLE VERSION"""
    try:
        # Get current user's campus information from roles
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            # Fallback to default if no campus found
            campus_id = "campus-1"
            frappe.logger().warning(f"No campus found for user {frappe.session.user}, using default: {campus_id}")
        
        filters = {"campus_id": campus_id}
        frappe.logger().info(f"Using filters: {filters}")

        # Try to get actual subjects with error handling
        try:
            actual_subjects = frappe.get_all(
            "SIS Actual Subject",
            fields=[
                "name",
                "title_vn",
                "title_en",
                "campus_id",
                "creation",
                "modified"
            ],
            filters=filters,
            order_by="title_vn asc"
        )
            frappe.logger().info(f"Found {len(actual_subjects)} actual subjects")

            # Add creation and modified fields if missing
            for subject in actual_subjects:
                if 'creation' not in subject:
                    subject['creation'] = None
                if 'modified' not in subject:
                    subject['modified'] = None
        except Exception as db_error:
            frappe.logger().error(f"Database error: {str(db_error)}")
            import traceback
            frappe.logger().error(f"Database error traceback: {traceback.format_exc()}")
            return error_response(
                message=f"Database error: {str(db_error)}",
                code="DATABASE_ERROR"
            )

        return list_response(
            data=actual_subjects,
            message="Actual subjects fetched successfully"
        )
        
    except Exception as e:
        frappe.log_error(f"Error fetching actual subjects: {str(e)}")
        return error_response(
            message="Error fetching actual subjects",
            code="FETCH_ACTUAL_SUBJECTS_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def get_actual_subject_by_id():
    """Get a specific actual subject by ID"""
    try:
        
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
            return error_response(
                message="Subject ID is required",
                code="MISSING_SUBJECT_ID"
            )
        
        # Get current user's campus
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
            
        filters = {
            "name": subject_id,
            "campus_id": campus_id
        }
        
        actual_subject = frappe.get_doc("SIS Actual Subject", filters)
        
        if not actual_subject:
            return not_found_response(
                message="Actual subject not found or access denied",
                code="ACTUAL_SUBJECT_NOT_FOUND"
            )
        
        return single_item_response(
            data={
                "name": actual_subject.name,
                "title_vn": actual_subject.title_vn,
                "title_en": actual_subject.title_en,
                "campus_id": actual_subject.campus_id,
                "education_stage_id": getattr(actual_subject, "education_stage_id", None),
                "curriculum_id": getattr(actual_subject, "curriculum_id", None),
                "creation": actual_subject.creation,
                "modified": actual_subject.modified
            },
            message="Actual subject fetched successfully"
        )
        
    except Exception as e:
        frappe.log_error(f"Error fetching actual subject {subject_id}: {str(e)}")
        return error_response(
            message="Error fetching actual subject",
            code="FETCH_ACTUAL_SUBJECT_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def create_actual_subject():
    """Create a new actual subject - SIMPLE VERSION"""
    try:
        # Get data from request - follow Education Stage pattern
        data = {}
        
        if frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data)
                if json_data:
                    data = json_data
                else:
                    data = frappe.local.form_dict
            except (json.JSONDecodeError, TypeError):
                data = frappe.local.form_dict
        else:
            data = frappe.local.form_dict
        
        # Extract values from data
        title_vn = data.get("title_vn")
        title_en = data.get("title_en")
        education_stage_id = data.get("education_stage_id")
        curriculum_id = data.get("curriculum_id")
        
        # Input validation
        if not title_vn:
            return validation_error_response(
                message="Title VN is required",
                errors={
                    "title_vn": ["Required"] if not title_vn else []
                }
            )
        
        # Get campus from user context
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
            frappe.logger().warning(f"No campus found for user {frappe.session.user}, using default: {campus_id}")
        
        # Check if actual subject title already exists for this campus
        existing = frappe.db.exists(
            "SIS Actual Subject",
            {
                "title_vn": title_vn,
                "campus_id": campus_id
            }
        )
        
        if existing:
            return error_response(
                message=f"Actual subject with title '{title_vn}' already exists",
                code="ACTUAL_SUBJECT_EXISTS"
            )
        
        # Create new actual subject
        actual_subject_doc = frappe.get_doc({
            "doctype": "SIS Actual Subject",
            "title_vn": title_vn,
            "title_en": title_en,
            "campus_id": campus_id,
            "education_stage_id": education_stage_id,
            "curriculum_id": curriculum_id
        })
        
        actual_subject_doc.insert()
        frappe.db.commit()
        
        # Return the created data - follow Education Stage pattern
        frappe.msgprint(_("Actual subject created successfully"))
        return single_item_response(
            data={
                "name": actual_subject_doc.name,
                "title_vn": actual_subject_doc.title_vn,
                "title_en": actual_subject_doc.title_en,
                "campus_id": actual_subject_doc.campus_id,
                "education_stage_id": getattr(actual_subject_doc, "education_stage_id", None),
                "curriculum_id": getattr(actual_subject_doc, "curriculum_id", None)
            },
            message="Actual subject created successfully"
        )
        
    except Exception as e:
        frappe.log_error(f"Error creating actual subject: {str(e)}")
        return error_response(
            message="Error creating actual subject",
            code="CREATE_ACTUAL_SUBJECT_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def update_actual_subject():
    """Update an existing actual subject"""
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
            return error_response(
                message="Subject ID is required",
                code="MISSING_SUBJECT_ID"
            )
        
        # Get campus from user context
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
        
        # Get existing document
        try:
            actual_subject_doc = frappe.get_doc("SIS Actual Subject", subject_id)
            
            # Check campus permission
            if actual_subject_doc.campus_id != campus_id:
                return forbidden_response(
                    message="Access denied: You don't have permission to modify this actual subject",
                    code="ACCESS_DENIED"
                )
                
        except frappe.DoesNotExistError:
            return not_found_response(
                message="Actual subject not found",
                code="ACTUAL_SUBJECT_NOT_FOUND"
            )
        
        # Update fields if provided
        title_vn = data.get('title_vn')
        title_en = data.get('title_en')
        education_stage_id = data.get('education_stage_id')
        curriculum_id = data.get('curriculum_id')


        if title_vn and title_vn != actual_subject_doc.title_vn:
            # Check for duplicate actual subject title
            existing = frappe.db.exists(
                "SIS Actual Subject",
                {
                    "title_vn": title_vn,
                    "campus_id": campus_id,
                    "name": ["!=", subject_id]
                }
            )
            if existing:
                return error_response(
                    message=f"Actual subject with title '{title_vn}' already exists",
                    code="ACTUAL_SUBJECT_EXISTS"
                )
            actual_subject_doc.title_vn = title_vn
        
        if title_en and title_en != actual_subject_doc.title_en:
            actual_subject_doc.title_en = title_en
            
        if education_stage_id is not None:
            actual_subject_doc.education_stage_id = education_stage_id
        if curriculum_id is not None:
            actual_subject_doc.curriculum_id = curriculum_id
        
        actual_subject_doc.save()
        frappe.db.commit()
        
        return single_item_response(
            data={
                "name": actual_subject_doc.name,
                "title_vn": actual_subject_doc.title_vn,
                "title_en": actual_subject_doc.title_en,
                "campus_id": actual_subject_doc.campus_id,
                "education_stage_id": getattr(actual_subject_doc, "education_stage_id", None),
                "curriculum_id": getattr(actual_subject_doc, "curriculum_id", None)
            },
            message="Actual subject updated successfully"
        )
        
    except Exception as e:
        frappe.log_error(f"Error updating actual subject {subject_id}: {str(e)}")
        return error_response(
            message="Error updating actual subject",
            code="UPDATE_ACTUAL_SUBJECT_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def delete_actual_subject():
    """Delete an actual subject"""
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
            return error_response(
                message="Subject ID is required",
                code="MISSING_SUBJECT_ID"
            )

        # Get campus from user context
        campus_id = get_current_campus_from_context()

        if not campus_id:
            campus_id = "campus-1"

        # Get existing document
        try:
            actual_subject_doc = frappe.get_doc("SIS Actual Subject", subject_id)

            # Check campus permission
            if actual_subject_doc.campus_id != campus_id:
                return forbidden_response(
                    message="Access denied: You don't have permission to delete this actual subject",
                    code="ACCESS_DENIED"
                )
                
        except frappe.DoesNotExistError:
            return not_found_response(
                message="Actual subject not found",
                code="ACTUAL_SUBJECT_NOT_FOUND"
            )
        
        # Delete the document
        frappe.delete_doc("SIS Actual Subject", subject_id)
        frappe.db.commit()
        
        return success_response(
            message="Actual subject deleted successfully"
        )
        
    except Exception as e:
        frappe.log_error(f"Error deleting actual subject {subject_id}: {str(e)}")
        return error_response(
            message="Error deleting actual subject",
            code="DELETE_ACTUAL_SUBJECT_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def get_curriculums_for_selection():
    """Get curriculums for dropdown selection"""
    try:
        # Get current user's campus information from roles
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
        
        filters = {"campus_id": campus_id}
            
        curriculums = frappe.get_all(
            "SIS Curriculum",
            fields=[
                "name",
                "title_vn",
                "title_en"
            ],
            filters=filters,
            order_by="title_vn asc"
        )
        
        return success_response(
            data=curriculums,
            message="Curriculums fetched successfully"
        )
        
    except Exception as e:
        frappe.log_error(f"Error fetching curriculums for selection: {str(e)}")
        return error_response(
            message="Error fetching curriculums",
            code="FETCH_CURRICULUMS_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def delete_actual_subject():
    """Delete an actual subject"""
    try:
        # Get subject_id from request - try multiple ways
        data = frappe.local.form_dict
        subject_id = data.get('subject_id')

        # If not found in form_dict, try request body
        if not subject_id:
            try:
                import json
                request_body = frappe.local.request.get_data()
                if request_body:
                    body_data = json.loads(request_body.decode('utf-8'))
                    subject_id = body_data.get('subject_id')
            except Exception as json_error:
                pass

        # Also try frappe.request.args
        if not subject_id:
            subject_id = frappe.request.args.get('subject_id')

        # Try frappe.local.request.args as well
        if not subject_id:
            try:
                subject_id = frappe.local.request.args.get('subject_id')
            except Exception as args_error:
                pass

        if not subject_id:
            frappe.logger().error("Subject ID is missing from request")
            return error_response(
                message="Subject ID is required",
                code="MISSING_SUBJECT_ID"
            )

        # Get current user's campus information from roles
        try:
            campus_id = get_current_campus_from_context()
        except Exception as campus_error:
            return error_response(
                message="Lỗi khi xác định campus của người dùng",
                code="CAMPUS_CONTEXT_ERROR"
            )

        if not campus_id:
            return error_response(
                message="Unable to determine user's campus",
                code="NO_CAMPUS_FOUND"
            )

        # Check if subject exists and belongs to user's campus
        try:
            subject = frappe.get_doc("SIS Actual Subject", subject_id)
        except frappe.DoesNotExistError:
            return error_response(
                message="Môn học thực tế không tồn tại",
                code="ACTUAL_SUBJECT_NOT_FOUND"
            )
        except Exception as subject_error:
            return error_response(
                message="Lỗi khi truy vấn môn học thực tế",
                code="SUBJECT_QUERY_ERROR"
            )

        if subject.campus_id != campus_id:
            return error_response(
                message="Unauthorized: Subject does not belong to your campus",
                code="UNAUTHORIZED_ACCESS"
            )

        # Check for linked records that prevent deletion
        try:
            linked_docs = []

            # Check Subject links
            subject_count = frappe.db.count("SIS Subject", {"actual_subject_id": subject_id})
            if subject_count > 0:
                linked_docs.append(f"{subject_count} môn học")

            # Check Timetable Subject links
            timetable_count = frappe.db.count("SIS Timetable Subject", {"actual_subject_id": subject_id})
            if timetable_count > 0:
                linked_docs.append(f"{timetable_count} môn học thời khóa biểu")

            if linked_docs:
                return error_response(
                    message=f"Không thể xóa môn học thực tế vì đang được liên kết với {', '.join(linked_docs)}. Vui lòng xóa hoặc chuyển các mục liên kết sang môn học thực tế khác trước.",
                    code="ACTUAL_SUBJECT_LINKED"
                )

        except Exception as link_error:
            return error_response(
                message="Lỗi khi kiểm tra các liên kết của môn học thực tế",
                code="LINK_CHECK_ERROR"
            )

        # Delete the subject
        try:
            frappe.delete_doc("SIS Actual Subject", subject_id)
            frappe.db.commit()

            return success_response(
                message="Môn học thực tế đã được xóa thành công"
            )

        except Exception as delete_error:
            frappe.db.rollback()
            return error_response(
                message="Lỗi khi xóa môn học thực tế",
                code="DELETE_OPERATION_ERROR"
            )

    except frappe.DoesNotExistError as e:
        return error_response(
            message="Môn học thực tế không tồn tại",
            code="ACTUAL_SUBJECT_NOT_FOUND"
        )
    except frappe.LinkExistsError as e:
        return error_response(
            message=f"Không thể xóa môn học thực tế vì đang được sử dụng bởi các module khác. Chi tiết: {str(e)}",
            code="ACTUAL_SUBJECT_LINKED"
        )
    except Exception as e:
        frappe.log_error(f"Unexpected error during actual subject deletion: {str(e)}")
        return error_response(
            message="Lỗi không mong muốn khi xóa môn học thực tế",
            code="DELETE_ACTUAL_SUBJECT_ERROR"
        )
