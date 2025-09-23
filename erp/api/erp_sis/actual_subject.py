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
                "education_stage_id",
                "curriculum_id",
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
        
        if not title_en:
            return validation_error_response(
                message="Title EN is required",
                errors={
                    "title_en": ["Required"] if not title_en else []
                }
            )
        
        if not education_stage_id:
            return validation_error_response(
                message="Education Stage is required",
                errors={
                    "education_stage_id": ["Required"] if not education_stage_id else []
                }
            )
        
        if not curriculum_id:
            return validation_error_response(
                message="Curriculum is required",
                errors={
                    "curriculum_id": ["Required"] if not curriculum_id else []
                }
            )
        
        # Get campus from user context
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
            frappe.logger().warning(f"No campus found for user {frappe.session.user}, using default: {campus_id}")
        
        # Allow duplicate title_vn - unique constraint removed
        
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
            # Allow duplicate title_vn - unique constraint removed
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


@frappe.whitelist(allow_guest=False, methods=['POST'])
def delete_actual_subject():
    """Delete an actual subject"""
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
def bulk_import_actual_subjects():
    """Bulk import actual subjects from Excel file"""
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
        
        frappe.logger().info(f"Actual subject bulk import file received: {uploaded_file.filename}")
        
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
        required_columns = ['title_vn', 'title_en', 'education_stage', 'curriculum']
        
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
        
        # Get existing actual subjects to check for uniqueness
        existing_subjects = frappe.get_all(
            "SIS Actual Subject",
            fields=["name", "title_vn", "education_stage_id", "curriculum_id"],
            filters={"campus_id": campus_id},
            order_by="creation asc"
        )
        
        existing_combinations = set()
        for subj in existing_subjects:
            combo = f"{subj.get('title_vn', '').lower()}|{subj.get('education_stage_id', '')}|{subj.get('curriculum_id', '')}"
            existing_combinations.add(combo)
        
        # Process each row
        success_count = 0
        error_count = 0
        errors = []
        logs = []
        
        for index, row in df.iterrows():
            try:
                # Extract data from row
                title_vn = str(row.get('title_vn', '')).strip() if pd.notna(row.get('title_vn')) else ''
                title_en = str(row.get('title_en', '')).strip() if pd.notna(row.get('title_en')) else ''
                education_stage_name = str(row.get('education_stage', '')).strip() if pd.notna(row.get('education_stage')) else ''
                curriculum_name = str(row.get('curriculum', '')).strip() if pd.notna(row.get('curriculum')) else ''
                
                # Clean up extra spaces
                if education_stage_name:
                    education_stage_name = ' '.join(education_stage_name.split())
                if curriculum_name:
                    curriculum_name = ' '.join(curriculum_name.split())
                
                frappe.logger().info(f"Processing row {index + 2}: Title VN='{title_vn}', Education Stage='{education_stage_name}'")
                
                # Validation
                if not title_vn:
                    error_count += 1
                    error_msg = f"Row {index + 2}: Title VN is required"
                    errors.append(error_msg)
                    logs.append(error_msg)
                    continue
                
                if not title_en:
                    error_count += 1
                    error_msg = f"Row {index + 2}: Title EN is required"
                    errors.append(error_msg)
                    logs.append(error_msg)
                    continue
                
                if not education_stage_name:
                    error_count += 1
                    error_msg = f"Row {index + 2}: Education stage is required"
                    errors.append(error_msg)
                    logs.append(error_msg)
                    continue
                
                if not curriculum_name:
                    error_count += 1
                    error_msg = f"Row {index + 2}: Curriculum is required"
                    errors.append(error_msg)
                    logs.append(error_msg)
                    continue
                
                # Lookup education stage ID from title_vn
                education_stage_id = frappe.db.get_value(
                    "SIS Education Stage",
                    {
                        "title_vn": education_stage_name,
                        "campus_id": campus_id
                    },
                    "name"
                )
                
                # If not found, try case insensitive search
                if not education_stage_id:
                    all_stages = frappe.db.get_all(
                        "SIS Education Stage",
                        filters={"campus_id": campus_id},
                        fields=["name", "title_vn"]
                    )
                    
                    for stage in all_stages:
                        if stage.get('title_vn', '').lower().strip() == education_stage_name.lower().strip():
                            education_stage_id = stage.get('name')
                            logs.append(f"Row {index + 2}: Found education stage '{education_stage_name}' with case insensitive match")
                            break
                
                if not education_stage_id:
                    # Log available stages for debugging
                    available_stages = [stage.get('title_vn', '') for stage in frappe.db.get_all(
                        "SIS Education Stage",
                        filters={"campus_id": campus_id},
                        fields=["title_vn"]
                    )]
                    error_count += 1
                    error_msg = f"Row {index + 2}: Education stage '{education_stage_name}' does not exist. Available: {', '.join(available_stages[:5])}{'...' if len(available_stages) > 5 else ''}"
                    errors.append(error_msg)
                    logs.append(error_msg)
                    continue
                
                # Lookup curriculum ID from title_vn
                curriculum_id = frappe.db.get_value(
                    "SIS Curriculum",
                    {
                        "title_vn": curriculum_name,
                        "campus_id": campus_id
                    },
                    "name"
                )
                
                # If not found, try case insensitive search
                if not curriculum_id:
                    all_curriculums = frappe.db.get_all(
                        "SIS Curriculum",
                        filters={"campus_id": campus_id},
                        fields=["name", "title_vn"]
                    )
                    
                    for curr in all_curriculums:
                        if curr.get('title_vn', '').lower().strip() == curriculum_name.lower().strip():
                            curriculum_id = curr.get('name')
                            logs.append(f"Row {index + 2}: Found curriculum '{curriculum_name}' with case insensitive match")
                            break
                
                if not curriculum_id:
                    # Log available curriculums for debugging
                    available_curriculums = [curr.get('title_vn', '') for curr in frappe.db.get_all(
                        "SIS Curriculum",
                        filters={"campus_id": campus_id},
                        fields=["title_vn"]
                    )]
                    error_count += 1
                    error_msg = f"Row {index + 2}: Curriculum '{curriculum_name}' does not exist. Available: {', '.join(available_curriculums[:5])}{'...' if len(available_curriculums) > 5 else ''}"
                    errors.append(error_msg)
                    logs.append(error_msg)
                    continue
                
                # Check uniqueness combination
                combo = f"{title_vn.lower()}|{education_stage_id}|{curriculum_id}"
                if combo in existing_combinations:
                    error_count += 1
                    error_msg = f"Row {index + 2}: Actual subject '{title_vn}' already exists in education stage '{education_stage_name}' and curriculum '{curriculum_name}'"
                    errors.append(error_msg)
                    logs.append(error_msg)
                    continue
                
                # Create actual subject
                actual_subject_doc = frappe.get_doc({
                    "doctype": "SIS Actual Subject",
                    "title_vn": title_vn,
                    "title_en": title_en,
                    "campus_id": campus_id,
                    "education_stage_id": education_stage_id,
                    "curriculum_id": curriculum_id
                })
                
                actual_subject_doc.flags.ignore_validate = True
                actual_subject_doc.flags.ignore_permissions = True
                actual_subject_doc.insert(ignore_permissions=True)
                
                # Track this creation for uniqueness checking in subsequent rows
                existing_combinations.add(combo)
                
                success_count += 1
                logs.append(f"Row {index + 2}: Successfully created actual subject '{title_vn}'")
                
            except Exception as e:
                error_count += 1
                error_msg = f"Row {index + 2}: Error creating actual subject: {str(e)}"
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
                message=f"Bulk import completed. {success_count} actual subjects created, {error_count} errors."
            )
        else:
            return error_response(
                data=response_data,
                message=f"Bulk import failed. {error_count} errors occurred.",
                code="BULK_IMPORT_FAILED"
            )
            
    except Exception as e:
        frappe.log_error(f"Error in bulk import actual subjects: {str(e)}", "Actual Subject Bulk Import Error")
        return error_response(
            message=f"Error in bulk import actual subjects: {str(e)}",
            code="BULK_IMPORT_ERROR"
        )


