# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

"""
Timetable Excel Import Operations

Handles Excel file upload and background job enqueueing.

This module now uses the NEW EXECUTOR pattern:
- Validation: import_validator.py (TimetableImportValidator)
- Execution: import_executor.py (TimetableImportExecutor)

Old legacy code (excel_import_legacy.py) is deprecated and no longer used.
"""

import frappe
from frappe import _
from erp.utils.campus_utils import get_current_campus_from_context
from erp.utils.api_response import (
    error_response,
    forbidden_response,
    single_item_response,
    validation_error_response,
)


@frappe.whitelist(allow_guest=False)
def import_timetable():
    """Import timetable from Excel with dry-run validation and final import"""
    try:
        # Get request data - handle both FormData and regular form data
        data = {}

        # Try different sources for FormData
        if hasattr(frappe.request, 'form_data') and frappe.request.form_data:
            # For werkzeug form data
            data = frappe.request.form_data
        elif hasattr(frappe.request, 'form') and frappe.request.form:
            # For flask-style form data
            data = frappe.request.form
        elif frappe.local.form_dict:
            # Fallback to form_dict
            data = frappe.local.form_dict
        elif hasattr(frappe.request, 'args') and frappe.request.args:
            # Try request args
            data = frappe.request.args

        # Convert to dict if it's not already
        if hasattr(data, 'to_dict'):
            data = data.to_dict()
        elif not isinstance(data, dict):
            data = dict(data) if data else {}

        # Check for dry_run parameter
        dry_run = data.get("dry_run", "false").lower() == "true"

        # Extract basic info
        title_vn = data.get("title_vn")
        title_en = data.get("title_en")
        campus_id = data.get("campus_id")
        school_year_id = data.get("school_year_id")
        education_stage_id = data.get("education_stage_id")
        start_date = data.get("start_date")
        end_date = data.get("end_date")

        # Validate required fields - end_date can be provided by user or auto-calculated from school_year_id
        if not all([title_vn, campus_id, school_year_id, education_stage_id, start_date]):
            return validation_error_response("Validation failed", {
                "required_fields": ["title_vn", "campus_id", "school_year_id", "education_stage_id", "start_date"],
                "logs": []
            })
        
        # Auto-calculate end_date from school year if not provided (fallback for backward compatibility)
        if not end_date:
            try:
                school_year = frappe.get_doc("SIS School Year", school_year_id)
                if school_year.campus_id != campus_id:
                    return validation_error_response("Validation failed", {
                        "school_year_id": ["School year does not belong to the selected campus"],
                        "logs": []
                    })
                end_date = school_year.end_date
                
            except frappe.DoesNotExistError:
                return validation_error_response("Validation failed", {
                    "school_year_id": ["School year not found"],
                    "logs": []
                })
            except Exception as e:
                return validation_error_response("Validation failed", {
                    "school_year_id": [f"Error retrieving school year: {str(e)}"],
                    "logs": []
                })

        # Get current user campus
        user_campus = get_current_campus_from_context()
        if user_campus and user_campus != campus_id:
            return forbidden_response("Access denied: Campus mismatch")

        # Process Excel import if file is provided
        files = frappe.request.files

        if files and 'file' in files:
            # File is uploaded, process it
            file_data = files['file']
            if not file_data:
                return validation_error_response("Validation failed", {"file": ["No file uploaded"], "logs": []})

            # Save file temporarily
            file_path = save_uploaded_file(file_data, "timetable_import.xlsx")

            # Call Excel import processor with metadata
            import_data = {
                "file_path": file_path,
                "title_vn": title_vn,
                "title_en": title_en,
                "campus_id": campus_id,
                "school_year_id": school_year_id,
                "education_stage_id": education_stage_id,
                "start_date": start_date,
                "end_date": end_date,
                "dry_run": dry_run
            }

            # Generate job ID for progress tracking
            import uuid
            job_id = f"timetable_import_{uuid.uuid4().hex[:8]}"
            
            frappe.logger().info(f"🚀 Starting import job with job_id: {job_id}")
            
            # Add job_id and user_id to import_data for background function
            import_data['job_id'] = job_id
            import_data['user_id'] = frappe.session.user  # Pass current user to background job
            
            # Enqueue background job using NEW EXECUTOR (validator + executor pattern)
            job = frappe.enqueue(
                method='erp.api.erp_sis.timetable.import_executor.process_with_new_executor',
                queue='long',
                timeout=7200,  # 2 hour timeout - increased for handling 40+ classes
                is_async=True,
                **import_data
            )
            
            # Use our job_id (not RQ job id) for consistency
            actual_job_id = job_id
            frappe.logger().info(f"✅ Job enqueued successfully. Job ID for tracking: {actual_job_id}")
            
            return single_item_response({
                "status": "processing",
                "job_id": actual_job_id,
                "message": "Timetable import đang được xử lý trong background (NEW EXECUTOR)",
                "logs": [
                    "📤 Đã upload file thành công", 
                    f"⚙️ Job ID: {actual_job_id}",
                    "🚀 Using new validator + executor pattern"
                ]
            }, "Timetable import job created")
        else:
            # No file uploaded, just validate metadata
            result = {
                "dry_run": dry_run,
                "title_vn": title_vn,
                "title_en": title_en,
                "campus_id": campus_id,
                "school_year_id": school_year_id,
                "education_stage_id": education_stage_id,
                "start_date": start_date,
                "end_date": end_date,
                "message": "Metadata validation completed",
                "requires_file": True,
                "logs": []
            }

            return single_item_response(result, "Timetable metadata validated successfully")

    except Exception as e:

        return error_response(f"Error importing timetable: {str(e)}")


@frappe.whitelist(methods=["GET"])
def get_import_job_status():
    """
    Get the status/result of timetable import background job.
    Frontend should poll this endpoint after submitting import.
    
    Query params:
        - job_id: Background job ID for progress tracking
    
    Returns:
        - If completed: final result with success/error
        - If processing: progress data with current/total/percentage/message
    """
    try:
        # Get job_id from query params
        job_id = frappe.form_dict.get("job_id") or frappe.request.args.get("job_id")
        
        frappe.logger().info(f"📊 Poll Status: job_id={job_id}, user={frappe.session.user}")
        
        # Check for final result first
        result_key = f"timetable_import_result_{frappe.session.user}"
        result = frappe.cache().get_value(result_key)
        
        if result:
            frappe.logger().info(f"✅ Found final result: success={result.get('success')}")
            
            # Add status field for frontend
            result_with_status = dict(result)
            result_with_status['status'] = 'completed' if result.get('success') else 'failed'
            result_with_status['job_id'] = job_id
            
            frappe.logger().info(f"📤 Returning final result with status={result_with_status['status']}")
            
            # Don't clear cache immediately - let frontend clear it
            return single_item_response(result_with_status, "Import result retrieved")
        
        # Check for progress data (job still running)
        if job_id:
            progress_key = f"timetable_import_progress:{job_id}"
            progress = frappe.cache().get_value(progress_key)
            
            frappe.logger().info(f"🔍 Checking progress_key: {progress_key}")
            frappe.logger().info(f"🔍 Progress data: {progress}")
            
            if progress:
                frappe.logger().info(f"📊 Progress {progress.get('percentage', 0)}%: {progress.get('message', 'Processing...')}")
                
                # Return progress data in format frontend expects (nested under 'progress' key)
                return single_item_response({
                    "status": "processing",
                    "job_id": job_id,
                    "progress": {
                        "phase": progress.get("phase", "importing"),
                        "current": progress.get("current", 0),
                        "total": progress.get("total", 100),
                        "percentage": progress.get("percentage", 0),
                        "message": progress.get("message", "Đang xử lý..."),
                        "current_class": progress.get("current_class", "")
                    }
                }, "Import in progress")
            else:
                frappe.logger().warning(f"⚠️ No progress data found for job_id={job_id}")
        else:
            frappe.logger().warning(f"⚠️ No job_id provided in request")
        
        # No result and no progress data yet - job just started or crashed
        frappe.logger().info(f"⏳ Returning 'starting' status - job may still be initializing")
        return single_item_response({
            "status": "processing",
            "job_id": job_id,
            "progress": {
                "phase": "starting",
                "current": 0,
                "total": 100,
                "percentage": 0,
                "message": "Đang khởi động import job...",
                "current_class": ""
            }
        }, "Import starting")
    
    except Exception as e:
        frappe.logger().error(f"❌ Error in get_import_job_status: {str(e)}")
        import traceback
        frappe.logger().error(traceback.format_exc())
        return error_response(f"Error retrieving import status: {str(e)}")


def save_uploaded_file(file_data, filename: str) -> str:
    """Save uploaded file temporarily and return file path"""
    try:
        import os
        import uuid

        # Create temporary directory if it doesn't exist
        temp_dir = frappe.utils.get_site_path("private", "files", "temp")
        if not os.path.exists(temp_dir):
            os.makedirs(temp_dir, exist_ok=True)

        # Generate unique filename
        unique_filename = f"{uuid.uuid4().hex}_{filename}"
        file_path = os.path.join(temp_dir, unique_filename)

        # Save file
        with open(file_path, 'wb') as f:
            f.write(file_data.read())

        return file_path
    except Exception as e:

        raise e

