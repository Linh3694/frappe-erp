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
            metadata = {
                "title_vn": title_vn,
                "title_en": title_en,
                "campus_id": campus_id,
                "school_year_id": school_year_id,
                "education_stage_id": education_stage_id,
                "start_date": start_date,
                "end_date": end_date
            }

            frappe.logger().info(f"🚀 Starting SYNCHRONOUS import execution")
            
            # ⚡ NEW: Execute synchronously instead of background job
            # This avoids worker queue issues and provides immediate feedback
            from erp.api.erp_sis.timetable.import_executor import execute_import_synchronous
            
            # Progress tracking list (to be sent with response)
            progress_updates = []
            last_percentage = [0]  # Use list to allow modification in nested function
            
            def progress_callback(progress):
                """Capture progress updates and log frequently"""
                progress_updates.append(progress)
                current_pct = progress.get('percentage', 0)
                
                # Log every significant progress change (every 5%) for visibility
                if current_pct - last_percentage[0] >= 5 or current_pct == 100:
                    frappe.logger().info(
                        f"📊 Import Progress {current_pct}%: {progress.get('message')} "
                        f"[{progress.get('current', 0)}/{progress.get('total', 0)}]"
                    )
                    last_percentage[0] = current_pct
                
                # Always log current class being processed
                if progress.get('current_class'):
                    frappe.logger().info(f"  🏫 Processing: {progress.get('current_class')}")
            
            # Execute import synchronously with progress callback
            result = execute_import_synchronous(file_path, metadata, progress_callback=progress_callback)
            
            frappe.logger().info(f"✅ Import execution completed: success={result.get('success')}")
            
            # Clean up temp file
            try:
                import os
                if os.path.exists(file_path):
                    os.remove(file_path)
                    frappe.logger().info(f"🗑️ Cleaned up temp file: {file_path}")
            except Exception as cleanup_error:
                frappe.logger().warning(f"⚠️ Failed to clean up temp file: {str(cleanup_error)}")
            
            # Return result immediately
            if result.get('success'):
                stats = result.get('stats', {})
                instances_created = result.get('instances_created', 0)
                instances_updated = result.get('instances_updated', 0)
                total_instances = result.get('total_instances_processed', instances_created + instances_updated)
                rows = result.get('rows_created', 0)
                
                frappe.logger().info(
                    f"✅ IMPORT SUCCESS: {instances_created} created, {instances_updated} updated, "
                    f"{rows} rows created"
                )
                
                return single_item_response({
                    "status": "completed",
                    "success": True,
                    "message": result.get('message', 'Import thành công!'),
                    "timetable_id": result.get('timetable_id'),
                    "instances_created": instances_created,
                    "instances_updated": instances_updated,
                    "total_instances_processed": total_instances,
                    "rows_created": rows,
                    "stats": stats,
                    "logs": result.get('logs', []),
                    "warnings": result.get('warnings', []),
                    "progress_history": progress_updates,  # Include all progress updates
                    "total_progress_steps": len(progress_updates)
                }, "Timetable import completed successfully")
            else:
                return validation_error_response(
                    result.get('message', 'Import failed'),
                    {
                        "errors": result.get('errors', []),
                        "logs": result.get('logs', []),
                        "warnings": result.get('warnings', []),
                        "stats": result.get('stats', {}),
                        "progress_history": progress_updates
                    }
                )
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
        # Frontend sends: params[job_id]=xxx (nested format from axios)
        # So we need to check both flat and nested formats
        job_id = None
        
        # Try nested format: params[job_id]
        if hasattr(frappe, 'request') and hasattr(frappe.request, 'args'):
            job_id = frappe.request.args.get("params[job_id]")
        
        # Try flat format: job_id
        if not job_id and hasattr(frappe, 'request') and hasattr(frappe.request, 'args'):
            job_id = frappe.request.args.get("job_id")
        
        # Try form_dict
        if not job_id and hasattr(frappe, 'form_dict'):
            job_id = frappe.form_dict.get("job_id")
        
        # Try local.form_dict
        if not job_id and hasattr(frappe, 'local') and hasattr(frappe.local, 'form_dict'):
            job_id = frappe.local.form_dict.get("job_id")
        
        frappe.logger().info(f"📊 Poll Status REQUEST: job_id={job_id}, user={frappe.session.user}")
        if hasattr(frappe, 'request') and hasattr(frappe.request, 'args'):
            frappe.logger().info(f"   All request.args: {dict(frappe.request.args)}")
        
        # Check for final result first
        # Use job_id for cache key instead of user_id to avoid session mismatch
        result_key = f"timetable_import_result_{job_id}" if job_id else f"timetable_import_result_{frappe.session.user}"
        frappe.logger().info(f"🔍 Checking result_key: {result_key}")
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
        frappe.logger().info(f"   Returning job_id={job_id} in response")
        
        response_data = {
            "status": "processing",
            "job_id": job_id,  # Preserve job_id even if no progress yet
            "progress": {
                "phase": "starting",
                "current": 0,
                "total": 100,
                "percentage": 0,
                "message": "Đang khởi động import job...",
                "current_class": ""
            }
        }
        
        frappe.logger().info(f"   Response data: {response_data}")
        return single_item_response(response_data, "Import starting")
    
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

