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
def get_all_timetable_subjects():
    """Get all timetable subjects with basic information - SIMPLE VERSION"""
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
        
        return list_response(timetable_subjects, "Timetable subjects fetched successfully")
        
    except Exception as e:
        frappe.log_error(f"Error fetching timetable subjects: {str(e)}")
        return error_response(f"Error fetching timetable subjects: {str(e)}")


@frappe.whitelist(allow_guest=False)
def get_timetable_subject_by_id():
    """Get a specific timetable subject by ID"""
    try:
        # Debug: Print all request data

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
                frappe.logger().error(f"Error parsing JSON data: {str(e)}")

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
        
        timetable_subject = frappe.get_doc("SIS Timetable Subject", filters)
        
        if not timetable_subject:
            return not_found_response("Timetable subject not found or access denied")
        
        subject_data = {
            "name": timetable_subject.name,
            "title_vn": timetable_subject.title_vn,
            "title_en": timetable_subject.title_en,
            "campus_id": timetable_subject.campus_id,
            "education_stage_id": getattr(timetable_subject, "education_stage_id", None),
            "curriculum_id": getattr(timetable_subject, "curriculum_id", None)
        }
        return single_item_response(subject_data, "Timetable subject fetched successfully")
        
    except Exception as e:
        frappe.log_error(f"Error fetching timetable subject {subject_id}: {str(e)}")
        return error_response(f"Error fetching timetable subject: {str(e)}")


@frappe.whitelist(allow_guest=False)
def create_timetable_subject():
    """Create a new timetable subject - SIMPLE VERSION"""
    try:
        # Get data from request - follow Education Stage pattern
        data = {}
        
        # First try to get JSON data from request body
        if frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data)
                if json_data:
                    data = json_data
                    frappe.logger().info(f"Received JSON data for create_timetable_subject: {data}")
                else:
                    data = frappe.local.form_dict
                    frappe.logger().info(f"Received form data for create_timetable_subject: {data}")
            except (json.JSONDecodeError, TypeError):
                # If JSON parsing fails, use form_dict
                data = frappe.local.form_dict
                frappe.logger().info(f"JSON parsing failed, using form data for create_timetable_subject: {data}")
        else:
            # Fallback to form_dict
            data = frappe.local.form_dict
            frappe.logger().info(f"No request data, using form_dict for create_timetable_subject: {data}")
        
        # Extract values from data
        title_vn = data.get("title_vn")
        title_en = data.get("title_en")
        education_stage_id = data.get("education_stage_id")
        curriculum_id = data.get("curriculum_id")
        
        # Input validation
        if not title_vn:
            frappe.throw(_("Title VN is required"))
        
        # Get campus from user context - simplified
        try:
            campus_id = get_current_campus_from_context()
        except Exception as e:
            frappe.logger().error(f"Error getting campus context: {str(e)}")
            campus_id = None
        
        if not campus_id:
            campus_id = "campus-1"
            frappe.logger().warning(f"No campus found for user {frappe.session.user}, using default: {campus_id}")
        
        
        # Create new timetable subject
        timetable_subject_doc = frappe.get_doc({
            "doctype": "SIS Timetable Subject",
            "title_vn": title_vn,
            "title_en": title_en,
            "campus_id": campus_id,
            "education_stage_id": education_stage_id,
            "curriculum_id": curriculum_id
        })
        
        timetable_subject_doc.insert()
        frappe.db.commit()
        
        # Return the created data - follow Education Stage pattern
        subject_data = {
            "name": timetable_subject_doc.name,
            "title_vn": timetable_subject_doc.title_vn,
            "title_en": timetable_subject_doc.title_en,
            "campus_id": timetable_subject_doc.campus_id,
            "education_stage_id": getattr(timetable_subject_doc, "education_stage_id", None),
            "curriculum_id": getattr(timetable_subject_doc, "curriculum_id", None)
        }
        return single_item_response(subject_data, "Timetable subject created successfully")
        
    except Exception as e:
        frappe.log_error(f"Error creating timetable subject: {str(e)}")
        frappe.throw(_(f"Error creating timetable subject: {str(e)}"))


@frappe.whitelist(allow_guest=False)
def update_timetable_subject():
    """Update an existing timetable subject"""
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
                frappe.logger().error(f"Error parsing JSON data: {str(e)}")

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
            timetable_subject_doc = frappe.get_doc("SIS Timetable Subject", subject_id)
            
            # Check campus permission
            if timetable_subject_doc.campus_id != campus_id:
                return forbidden_response("Access denied: You don't have permission to modify this timetable subject")
                
        except frappe.DoesNotExistError:
            return not_found_response("Timetable subject not found")
        
        # Update fields if provided
        title_vn = data.get('title_vn')
        title_en = data.get('title_en')
        education_stage_id = data.get('education_stage_id')
        curriculum_id = data.get('curriculum_id')


        if title_vn and title_vn != timetable_subject_doc.title_vn:
            # Check for duplicate timetable subject title
            # Allow duplicate title_vn - unique constraint removed
            timetable_subject_doc.title_vn = title_vn
        
        if title_en and title_en != timetable_subject_doc.title_en:
            timetable_subject_doc.title_en = title_en
        
        if education_stage_id is not None:
            timetable_subject_doc.education_stage_id = education_stage_id
        if curriculum_id is not None:
            timetable_subject_doc.curriculum_id = curriculum_id

        timetable_subject_doc.save()
        frappe.db.commit()
        
        subject_data = {
            "name": timetable_subject_doc.name,
            "title_vn": timetable_subject_doc.title_vn,
            "title_en": timetable_subject_doc.title_en,
            "campus_id": timetable_subject_doc.campus_id,
            "education_stage_id": getattr(timetable_subject_doc, "education_stage_id", None),
            "curriculum_id": getattr(timetable_subject_doc, "curriculum_id", None)
        }
        return single_item_response(subject_data, "Timetable subject updated successfully")
        
    except Exception as e:
        frappe.log_error(f"Error updating timetable subject {subject_id}: {str(e)}")
        return error_response(f"Error updating timetable subject: {str(e)}")


@frappe.whitelist(allow_guest=False)
def delete_timetable_subject():
    """Delete a timetable subject"""
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
                frappe.logger().error(f"Error parsing JSON data: {str(e)}")

        if not subject_id:
            return validation_error_response({"subject_id": ["Subject ID is required"]})

        # Get campus from user context
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
        
        # Get existing document
        try:
            timetable_subject_doc = frappe.get_doc("SIS Timetable Subject", subject_id)
            
            # Check campus permission
            if timetable_subject_doc.campus_id != campus_id:
                return forbidden_response("Access denied: You don't have permission to delete this timetable subject")
                
        except frappe.DoesNotExistError:
            return not_found_response("Timetable subject not found")
        
        # Delete the document
        frappe.delete_doc("SIS Timetable Subject", subject_id)
        frappe.db.commit()
        
        return success_response(message="Timetable subject deleted successfully")
        
    except Exception as e:
        frappe.log_error(f"Error deleting timetable subject {subject_id}: {str(e)}")
        return error_response(f"Error deleting timetable subject: {str(e)}")


@frappe.whitelist(allow_guest=False)
def bulk_import_timetable_subjects():
    """Bulk import timetable subjects from Excel file"""
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
        
        frappe.logger().info(f"Timetable subject bulk import file received: {uploaded_file.filename}")
        
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
        required_columns = ['title_vn']
        optional_columns = ['title_en', 'education_stage', 'curriculum']
        
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
        
        # Get existing timetable subjects to check for uniqueness
        existing_subjects = frappe.get_all(
            "SIS Timetable Subject",
            fields=["name", "title_vn", "education_stage_id", "curriculum_id"],
            filters={"campus_id": campus_id},
            order_by="creation asc"
        )
        
        existing_combinations = set()
        for subj in existing_subjects:
            # For timetable subjects, we check uniqueness by title_vn + education_stage_id + curriculum_id combo
            combo = f"{subj.get('title_vn', '').lower()}|{subj.get('education_stage_id', '') or ''}|{subj.get('curriculum_id', '') or ''}"
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
                education_stage_name = str(row.get('education_stage', '')).strip() if pd.notna(row.get('education_stage')) else None
                curriculum_name = str(row.get('curriculum', '')).strip() if pd.notna(row.get('curriculum')) else None
                
                # Clean up extra spaces in names
                if education_stage_name:
                    education_stage_name = ' '.join(education_stage_name.split())  # Remove extra spaces
                if curriculum_name:
                    curriculum_name = ' '.join(curriculum_name.split())  # Remove extra spaces
                
                frappe.logger().info(f"Processing row {index + 2}: Title VN='{title_vn}', Education Stage='{education_stage_name}'")
                
                # Validation
                if not title_vn:
                    error_count += 1
                    error_msg = f"Row {index + 2}: Title VN is required"
                    errors.append(error_msg)
                    logs.append(error_msg)
                    continue
                
                # Lookup education stage ID from title_vn (if provided)
                education_stage_id = None
                if education_stage_name and education_stage_name != 'nan':
                    # First try exact match
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
                
                # Lookup curriculum ID from title_vn (if provided)
                curriculum_id = None
                if curriculum_name and curriculum_name != 'nan':
                    # First try exact match
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
                combo = f"{title_vn.lower()}|{education_stage_id or ''}|{curriculum_id or ''}"
                if combo in existing_combinations:
                    error_count += 1
                    error_msg = f"Row {index + 2}: Timetable subject '{title_vn}' already exists with same education stage and curriculum combination"
                    errors.append(error_msg)
                    logs.append(error_msg)
                    continue
                
                # Build timetable subject data
                timetable_subject_data = {
                    "doctype": "SIS Timetable Subject",
                    "title_vn": title_vn,
                    "title_en": title_en or title_vn,  # Default to title_vn if title_en is empty
                    "campus_id": campus_id
                }
                
                # Add optional fields if provided
                if education_stage_id:
                    timetable_subject_data["education_stage_id"] = education_stage_id
                if curriculum_id:
                    timetable_subject_data["curriculum_id"] = curriculum_id
                
                # Create timetable subject
                timetable_subject_doc = frappe.get_doc(timetable_subject_data)
                
                timetable_subject_doc.flags.ignore_validate = True
                timetable_subject_doc.flags.ignore_permissions = True
                timetable_subject_doc.insert(ignore_permissions=True)
                
                # Track this creation for uniqueness checking in subsequent rows
                existing_combinations.add(combo)
                
                success_count += 1
                logs.append(f"Row {index + 2}: Successfully created timetable subject '{title_vn}'")
                
            except Exception as e:
                error_count += 1
                error_msg = f"Row {index + 2}: Error creating timetable subject: {str(e)}"
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
                message=f"Bulk import completed. {success_count} timetable subjects created, {error_count} errors."
            )
        else:
            return error_response(
                data=response_data,
                message=f"Bulk import failed. {error_count} errors occurred.",
                code="BULK_IMPORT_FAILED"
            )
            
    except Exception as e:
        frappe.log_error(f"Error in bulk import timetable subjects: {str(e)}", "Timetable Subject Bulk Import Error")
        return error_response(
            message=f"Error in bulk import timetable subjects: {str(e)}",
            code="BULK_IMPORT_ERROR"
        )
