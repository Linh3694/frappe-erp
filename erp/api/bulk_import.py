import frappe
from frappe.utils import cstr
from frappe import _
from frappe.utils import now_datetime, get_datetime
import json
import os
from erp.utils.api_response import (
    success_response, error_response, paginated_response,
    single_item_response, validation_error_response,
    not_found_response, forbidden_response
)
from erp.utils.campus_utils import get_current_campus_from_context
import traceback


@frappe.whitelist(allow_guest=False, methods=['POST'])
def start_bulk_import():
    """
    Start a bulk import job for Excel file processing

    Expected parameters:
    - doctype: Target DocType (e.g., "CRM Student", "SIS Subject")
    - file_url: URL of uploaded Excel file
    - options: Optional import options (update_if_exists, dry_run, etc.)
    """
    try:
        # Get parameters from request
        data = _get_request_data()

        # Validate required parameters
        doctype = data.get("doctype")
        file_url = data.get("file_url")

        if not doctype:
            return validation_error_response(
                message="doctype parameter is required",
                errors={"doctype": ["Required field"]}
            )

        if not file_url:
            return validation_error_response(
                message="file_url parameter is required",
                errors={"file_url": ["Required field"]}
            )

        # Validate DocType exists
        if not frappe.db.exists("DocType", doctype):
            return validation_error_response(
                message=f"DocType '{doctype}' does not exist",
                errors={"doctype": ["Invalid DocType"]}
            )

        # Get current user's campus
        campus_id = get_current_campus_from_context()
        if not campus_id:
            return forbidden_response(
                message="Unable to determine user's campus. Please contact administrator.",
                code="NO_CAMPUS_ACCESS"
            )

        # Create bulk import job
        options = data.get("options", {})
        options_json = json.dumps(options) if options else None

        job = frappe.get_doc({
            "doctype": "SIS Bulk Import Job",
            "doctype_target": doctype,
            "file_url": file_url,
            "options_json": options_json,
            "status": "Queued",
            "campus_id": campus_id,
            "created_by": frappe.session.user
        })

        job.insert(ignore_permissions=True)
        frappe.db.commit()

        # Execute immediately (synchronous) so it runs without any worker
        process_bulk_import(job.name)

        frappe.logger().info(f"Bulk import job {job.name} created and queued for {doctype}")

        return single_item_response(
            data={"job_id": job.name},
            message="Bulk import job has been created and queued for processing"
        )

    except Exception as e:
        frappe.log_error(f"Error starting bulk import: {str(e)}")
        return error_response(
            message=f"Failed to start bulk import job: {str(e)}",
            code="START_BULK_IMPORT_ERROR"
        )


@frappe.whitelist(allow_guest=False, methods=['GET'])
def get_bulk_import_status():
    """
    Get status of a bulk import job

    Expected parameters:
    - job_id: Job ID to check
    """
    try:
        # Get job_id from request (support multiple sources)
        job_id = (
            (frappe.form_dict.get("job_id") if hasattr(frappe, 'form_dict') else None)
            or (frappe.local.form_dict.get("job_id") if hasattr(frappe.local, 'form_dict') else None)
            or (frappe.request.args.get("job_id") if hasattr(frappe, 'request') and hasattr(frappe.request, 'args') and frappe.request.args else None)
        )

        if not job_id:
            return validation_error_response(
                message="job_id parameter is required",
                errors={"job_id": ["Required field"]}
            )

        # Get job document
        try:
            job = frappe.get_doc("SIS Bulk Import Job", job_id)
        except frappe.DoesNotExistError:
            return not_found_response(
                message="Bulk import job not found",
                code="JOB_NOT_FOUND"
            )

        # Check if user has access to this job
        if job.created_by != frappe.session.user:
            return forbidden_response(
                message="You don't have permission to view this job",
                code="ACCESS_DENIED"
            )

        # Calculate progress percentage
        progress_percentage = job.get_progress_percentage()

        # Build response
        response_data = {
            "job_id": job.name,
            "status": job.status,
            "doctype_target": job.doctype_target,
            "total_rows": job.total_rows or 0,
            "processed_rows": job.processed_rows or 0,
            "success_count": job.success_count or 0,
            "error_count": job.error_count or 0,
            "progress_percentage": progress_percentage,
            "started_at": job.started_at,
            "finished_at": job.finished_at,
            "message": job.message,
            "error_file_url": job.error_file_url
        }

        # Attach a small preview of errors so FE can show without opening file
        try:
            if job.error_file_url and job.error_count:
                file_url = job.error_file_url
                if file_url.startswith("/private/files/"):
                    filename = file_url.split("/private/files/")[-1]
                    file_path = frappe.get_site_path("private", "files", filename)
                elif file_url.startswith("/files/"):
                    filename = file_url.split("/files/")[-1]
                    file_path = frappe.get_site_path("public", "files", filename)
                else:
                    file_path = file_url if file_url.startswith("/") else frappe.get_site_path("public", file_url)

                import pandas as pd
                df_prev = pd.read_excel(file_path, nrows=5)
                preview = []
                for _, r in df_prev.iterrows():
                    item = {
                        "row": int(r.get("__row_number", 0)) if not pd.isna(r.get("__row_number", 0)) else 0,
                        "error": str(r.get("__error", "")).strip(),
                    }
                    sample = {}
                    for key in ["student_code", "student_name", "title", "name", "gender", "date_of_birth"]:
                        if key in df_prev.columns:
                            val = r.get(key)
                            if not (isinstance(val, float) and pd.isna(val)):
                                sample[key] = str(val)
                    if sample:
                        item["data"] = sample
                    preview.append(item)
                if preview:
                    response_data["errors_preview"] = preview
        except Exception:
            # Do not fail status API if preview extraction fails
            pass

        return single_item_response(
            data=response_data,
            message="Bulk import status retrieved successfully"
        )

    except Exception as e:
        frappe.log_error(f"Error getting bulk import status: {str(e)}")
        return error_response(
            message="Failed to get bulk import status",
            code="GET_STATUS_ERROR"
        )


@frappe.whitelist(allow_guest=True)
def reload_whitelist():
    """
    Reload whitelisted methods cache
    Call this after adding new whitelisted methods
    """
    try:
        # Clear method cache
        frappe.cache().delete_key("whitelisted_methods")
        frappe.cache().delete_key("method_map")

        # Reload hooks
        frappe.get_hooks()

        return single_item_response(
            data={"message": "Whitelist cache reloaded successfully"},
            message="Cache reloaded"
        )
    except Exception as e:
        frappe.log_error(f"Error reloading whitelist: {str(e)}")
        return error_response(
            message="Failed to reload whitelist",
            code="RELOAD_ERROR"
        )


# Move to a different file to avoid whitelist caching
# This function is now in a separate test file

# @frappe.whitelist(allow_guest=False, methods=['POST'])  # Temporarily disabled for testing
def upload_file_test():
    """
    Test upload function - no whitelist required
    """
    try:
        # Simple response for testing
        return single_item_response(
            data={
                "file_url": "/files/test.xlsx",
                "file_name": "test.xlsx",
                "message": "Test upload successful - whitelist bypassed"
            },
            message="Test upload completed"
        )
    except Exception as e:
        return error_response(
            message=f"Test upload failed: {str(e)}",
            code="TEST_UPLOAD_ERROR"
        )


# @frappe.whitelist(allow_guest=False, methods=['POST'])  # Temporarily disabled for testing
def upload_bulk_import_file_v2():
    """
    Upload file for bulk import processing

    Expected parameters:
    - file: File to upload
    - file_name: Name of the file
    """
    try:
        # Use Frappe's built-in file upload mechanism
        from frappe.utils.file_manager import save_file

        # Debug: Log all available request data
        frappe.logger().info("=== DEBUG: Bulk Import File Upload ===")
        frappe.logger().info(f"Available form_dict keys: {list(frappe.form_dict.keys())}")
        frappe.logger().info(f"Available local.form_dict keys: {list(frappe.local.form_dict.keys()) if hasattr(frappe.local, 'form_dict') else 'No local.form_dict'}")

        # Check for file in different locations
        if "file" not in frappe.form_dict and "file" not in frappe.local.form_dict:
            frappe.logger().info("File not found in form_dict or local.form_dict")

            # Try to check if file is in request.files
            if hasattr(frappe.request, 'files') and frappe.request.files:
                frappe.logger().info(f"Request files available: {list(frappe.request.files.keys())}")
            else:
                frappe.logger().info("No request.files available")

            return validation_error_response(
                message="File is required",
                errors={"file": ["Required field"]}
            )

        # Get file data
        file_obj = frappe.form_dict.get("file") or frappe.local.form_dict.get("file")
        file_name = frappe.form_dict.get("file_name") or frappe.local.form_dict.get("file_name") or "bulk_import_file.xlsx"

        frappe.logger().info(f"File object type: {type(file_obj)}")
        frappe.logger().info(f"File name: {file_name}")

        # Save file using Frappe's file manager
        file_doc = save_file(
            fname=file_name,
            content=file_obj,
            dt="File",
            dn="",
            folder="Home/Bulk Import",
            is_private=1
        )

        frappe.logger().info(f"File saved successfully: {file_doc.file_url}")

        return single_item_response(
            data={
                "file_url": file_doc.file_url,
                "file_name": file_doc.file_name
            },
            message="File uploaded successfully"
        )

    except Exception as e:
        frappe.log_error(f"Error uploading bulk import file: {str(e)}")
        return error_response(
            message="Failed to upload file",
            code="FILE_UPLOAD_ERROR"
        )


@frappe.whitelist(allow_guest=False, methods=['GET', 'POST'])
def download_template():
    """
    Download Excel template for a specific DocType

    Expected parameters:
    - doctype: Target DocType to generate template for
    """
    try:
        # Get doctype from request - try multiple sources
        doctype = (
            frappe.form_dict.get("doctype") or
            frappe.local.form_dict.get("doctype") or
            frappe.request.args.get("doctype") if hasattr(frappe.request, 'args') and frappe.request.args else None
        )

        # Log doctype resolution for debugging
        if not doctype:
            frappe.logger().info(f"Download template - doctype resolution failed. form_dict keys: {list(frappe.form_dict.keys())}")

        # TEMPORARY: For debugging, use hardcoded doctype if not found
        # Remove temporary fix - now requires proper doctype parameter

        if not doctype:
            return validation_error_response(
                message="doctype parameter is required",
                errors={"doctype": ["Required field"]}
            )

        # Validate DocType exists
        if not frappe.db.exists("DocType", doctype):
            return validation_error_response(
                message=f"DocType '{doctype}' does not exist",
                errors={"doctype": ["Invalid DocType"]}
            )

        # Template is handled by frontend directly - just return success
        return single_item_response(
            data={"message": "Template download handled by frontend"},
            message=f"Template ready for {doctype}"
        )

    except Exception as e:
        frappe.log_error(f"Error downloading template: {str(e)}")
        return error_response(
            message="Failed to download template",
            code="DOWNLOAD_TEMPLATE_ERROR"
        )


def _get_request_data():
    """Helper to get request data from various sources"""
    # Try JSON body first
    if frappe.request.data:
        try:
            return json.loads(frappe.request.data.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass

    # Fallback to form_dict
    return frappe.local.form_dict or {}





@frappe.whitelist(allow_guest=False)
def process_bulk_import(job_id):
    """
    Worker function to process bulk import job
    This function runs in background queue
    """
    try:
        frappe.logger().info(f"Starting bulk import processing for job {job_id}")

        # Get job
        job = frappe.get_doc("SIS Bulk Import Job", job_id)
        job.status = "Running"
        job.started_at = now_datetime()
        job.save(ignore_permissions=True)
        frappe.db.commit()

        # Process the Excel file
        result = _process_excel_file(job)

        # Update job with results
        if result["success"]:
            job.mark_completed(
                message=result["message"],
                error_file_url=result.get("error_file_url")
            )
        else:
            job.mark_failed(
                message=result["message"],
                error_file_url=result.get("error_file_url")
            )

        frappe.logger().info(f"Bulk import job {job_id} completed with status: {job.status}")

    except Exception as e:
        error_msg = f"Bulk import processing failed: {str(e)}"
        frappe.logger().error(f"{error_msg}\n{traceback.format_exc()}")

        try:
            job = frappe.get_doc("SIS Bulk Import Job", job_id)
            job.mark_failed(message=error_msg)
        except Exception:
            frappe.logger().error(f"Failed to mark job {job_id} as failed")


def _process_excel_file(job):
    """
    Process Excel file for bulk import

    Returns:
        dict: {
            "success": bool,
            "message": str,
            "error_file_url": str (optional)
        }
    """
    try:
        import pandas as pd
        from frappe.utils.file_manager import save_file

        frappe.logger().info(f"Processing Excel file for job {job.name}")

        # Resolve file_url to absolute file system path
        file_url = job.file_url or ""
        if not file_url:
            return {
                "success": False,
                "message": "Job has no file_url"
            }

        # Map /files/* and /private/files/* to site paths
        # Support both public and private file locations
        if file_url.startswith("/private/files/"):
            filename = file_url.split("/private/files/")[-1]
            file_path = frappe.get_site_path("private", "files", filename)
        elif file_url.startswith("/files/"):
            filename = file_url.split("/files/")[-1]
            file_path = frappe.get_site_path("public", "files", filename)
        else:
            # Fallback: if it's a relative path treat as public, else assume absolute
            file_path = file_url if file_url.startswith("/") else frappe.get_site_path("public", file_url)

        # Read Excel file
        try:
            import pandas as pd
            df = pd.read_excel(file_path)
        except Exception as e:
            return {
                "success": False,
                "message": f"Failed to read Excel file: {str(e)}"
            }

        # Skip first row (header) for Excel template files
        if len(df) > 1:
            df = df.iloc[1:]  # Skip first row (header), keep data from row 2 onwards
        else:
            return {
                "success": False,
                "message": "File appears to be too short. Please use the downloaded template and fill data starting from row 2."
            }

        # Remove completely empty rows
        df = df.dropna(how='all')

        total_rows = len(df)
        if total_rows == 0:
            return {
                "success": False,
                "message": "No data found in file. Please fill data starting from row 2 in the template."
            }

        job.total_rows = total_rows
        job.save(ignore_permissions=True)
        frappe.db.commit()

        frappe.logger().info(f"Excel file has {total_rows} rows")

        # Build label->fieldname mapping for column headers
        meta = frappe.get_meta(job.doctype_target)
        def _normalize_key(text):
            key = cstr(text)
            return "".join(ch.lower() for ch in key if ch.isalnum())

        label_map = {}
        for f in meta.fields:
            if getattr(f, 'fieldname', None):
                label_map[_normalize_key(f.fieldname)] = f.fieldname
            if getattr(f, 'label', None):
                label_map[_normalize_key(f.label)] = f.fieldname
        
        # Add special column mappings for specific DocTypes
        special_mappings = {
            "SIS Subject": {
                # education_stage field exists as-is in SIS Subject DocType
                "curriculum": "curriculum_id",
                "timetable_subject": "timetable_subject_id",
                "actual_subject": "actual_subject_id"
            },
            "SIS Timetable Subject": {
                "education_stage": "education_stage_id",
                "curriculum": "curriculum_id"
            },
            "SIS Actual Subject": {
                "education_stage": "education_stage_id",
                "curriculum": "curriculum_id",
                "timetable_subject": "timetable_subject_id"
            },
            "SIS Menu Category": {
                # Simple direct mapping - Excel columns match field names
                "title_vn": "title_vn",
                "title_en": "title_en",
                "code": "code"
            }
        }

        # Apply special mappings
        if job.doctype_target in special_mappings:
            for excel_col, target_field in special_mappings[job.doctype_target].items():
                normalized_col = "".join(ch.lower() for ch in excel_col if ch.isalnum())
                label_map[normalized_col] = target_field

        # Debug: Show column mapping for troubleshooting
        column_names = df.columns.tolist() if len(df) > 0 else []
        debug_mapping = {}
        for col in column_names:
            normalized = "".join(ch.lower() for ch in cstr(col) if ch.isalnum())
            target_key = label_map.get(normalized, col)
            debug_mapping[col] = target_key

        # Process data in batches
        batch_size = 100
        success_count = 0
        error_count = 0
        errors = []

        options = job.get_options_dict()
        update_if_exists = options.get("update_if_exists", False)
        dry_run = options.get("dry_run", False)

        # Process data in batches, accounting for skipped rows
        for i in range(0, total_rows, batch_size):
            batch_df = df.iloc[i:i+batch_size]
            original_start_index = i + 1 + 1  # +1 for skipped header row, +1 for Excel 1-indexing
            batch_result = _process_batch(job, batch_df, original_start_index, update_if_exists, dry_run, label_map, debug_mapping)

            success_count += batch_result["success_count"]
            error_count += batch_result["error_count"]
            errors.extend(batch_result["errors"])

            # Update progress
            processed_rows = min(i + batch_size, total_rows)
            job.update_progress(
                processed_rows=processed_rows,
                success_count=success_count,
                error_count=error_count
            )

        # Generate error report if there are errors
        error_file_url = None
        if errors:
            error_file_url = _generate_error_report(job, errors)

        message = f"Import completed: {success_count} success, {error_count} errors"
        if dry_run:
            message = f"Dry run completed: {success_count} would be imported, {error_count} errors"

        return {
            "success": True,
            "message": message,
            "error_file_url": error_file_url
        }

    except Exception as e:
        error_msg = f"Error processing Excel file: {str(e)}"
        frappe.logger().error(f"{error_msg}\n{traceback.format_exc()}")
        return {
            "success": False,
            "message": error_msg
        }


def _process_batch(job, batch_df, start_index, update_if_exists, dry_run, label_map, debug_mapping):
    """Process a batch of records"""
    success_count = 0
    error_count = 0
    errors = []

    import pandas as pd
    for idx, row in batch_df.iterrows():
        row_num = start_index + idx  # start_index already accounts for skipped header and Excel 1-indexing

        try:
            # Convert row to dict and clean data
            row_data = {}
            for col in batch_df.columns:
                value = row[col]
                if pd.isna(value):
                    value = None
                # Convert pandas Timestamp to ISO date string
                if isinstance(value, pd.Timestamp):
                    try:
                        value = value.date().isoformat()
                    except Exception:
                        value = value.to_pydatetime().date().isoformat()
                # Map header label to fieldname if possible (case/space-insensitive)
                normalized = "".join(ch.lower() for ch in cstr(col) if ch.isalnum())
                target_key = label_map.get(normalized, col)
                row_data[target_key] = value

            # Process single record
            result = _process_single_record(job, row_data, row_num, update_if_exists, dry_run)

            if result["success"]:
                success_count += 1
            else:
                error_count += 1
                
                # Add debug info to error
                debug_info = f"DEBUG - DocType: {job.doctype_target} | Column mapping: {debug_mapping} | Row data: {row_data}"
                enhanced_error = f"{result['error']} | {debug_info}"
                
                errors.append({
                    "row": row_num,
                    "data": row_data,
                    "error": enhanced_error
                })

        except Exception as e:
            error_count += 1
            debug_info = f"DEBUG - DocType: {job.doctype_target} | Column mapping: {debug_mapping} | Exception in batch processing"
            enhanced_error = f"{str(e)} | {debug_info}"
            errors.append({
                "row": row_num,
                "data": str(row.to_dict())[:500],  # Limit data size
                "error": enhanced_error
            })

    return {
        "success_count": success_count,
        "error_count": error_count,
        "errors": errors
    }


def _process_single_record(job, row_data, row_num, update_if_exists, dry_run):
    """Process a single record"""
    try:
        doctype = job.doctype_target

        # Handle campus_id - use from file or default to user's campus
        campus_id = row_data.get("campus_id")
        if not campus_id:
            campus_id = job.campus_id

        # Build document data
        doc_data = {
            "doctype": doctype,
            "campus_id": campus_id
        }

        # Special handling for reference fields BEFORE regular field mapping
        if doctype == "SIS Timetable Subject":
            
            # Handle curriculum lookup - check various possible keys
            curriculum_name = None
            for key in ["curriculum", "curriculum_id", "Curriculum"]:
                if key in row_data and row_data[key] and str(row_data[key]).strip():
                    curriculum_name = str(row_data[key]).strip()
                    break
            
            if curriculum_name:
                # Normalize and clean the curriculum name
                curriculum_name = ' '.join(curriculum_name.split())  # Remove extra spaces
                frappe.logger().info(f"Row {row_num} - Looking up curriculum: '{curriculum_name}'")
                
                # Lookup curriculum by title_vn
                curriculum_id = _lookup_curriculum_by_name(curriculum_name, campus_id)
                if curriculum_id:
                    doc_data["curriculum_id"] = curriculum_id
                    frappe.logger().info(f"Row {row_num} - Found curriculum ID: {curriculum_id}")
                else:
                    raise frappe.ValidationError(f"[SIS Subject] Không thể tìm thấy Curriculum: '{curriculum_name}' cho campus {campus_id}")
            
            # Handle education stage lookup - check various possible keys  
            education_stage_name = None
            for key in ["stage", "education_stage", "education_stage_id", "Stage"]:
                if key in row_data and row_data[key] and str(row_data[key]).strip():
                    education_stage_name = str(row_data[key]).strip()
                    break
                    
            if education_stage_name:
                # Normalize and clean the education stage name
                education_stage_name = ' '.join(education_stage_name.split())  # Remove extra spaces
                frappe.logger().info(f"Row {row_num} - Looking up education stage: '{education_stage_name}'")
                
                # Lookup education stage by title_vn
                education_stage_id = _lookup_education_stage_by_name(education_stage_name, campus_id)
                if education_stage_id:
                    doc_data["education_stage_id"] = education_stage_id
                    frappe.logger().info(f"Row {row_num} - Found education stage ID: {education_stage_id}")
                else:
                    raise frappe.ValidationError(f"[{doctype}] Không thể tìm thấy Education Stage: '{education_stage_name}' cho campus {campus_id}")
        
        elif doctype == "SIS Subject":
            
            # Handle curriculum lookup
            curriculum_name = None
            for key in ["curriculum", "curriculum_id", "Curriculum"]:
                if key in row_data and row_data[key] and str(row_data[key]).strip():
                    curriculum_name = str(row_data[key]).strip()
                    break
            
            if curriculum_name:
                # Normalize and clean the curriculum name
                curriculum_name = ' '.join(curriculum_name.split())  # Remove extra spaces
                frappe.logger().info(f"Row {row_num} - [SIS Subject] Looking up curriculum: '{curriculum_name}'")
                
                # Lookup curriculum by title_vn
                curriculum_id = _lookup_curriculum_by_name(curriculum_name, campus_id)
                if curriculum_id:
                    doc_data["curriculum_id"] = curriculum_id
                    frappe.logger().info(f"Row {row_num} - [SIS Subject] Found curriculum ID: {curriculum_id}")
                else:
                    raise frappe.ValidationError(f"[SIS Subject] Không thể tìm thấy Curriculum: '{curriculum_name}' cho campus {campus_id}")
            
            # Handle education stage lookup
            education_stage_name = None
            for key in ["stage", "education_stage", "education_stage_id", "Stage"]:
                if key in row_data and row_data[key] and str(row_data[key]).strip():
                    education_stage_name = str(row_data[key]).strip()
                    break
                    
            if education_stage_name:
                # Normalize and clean the education stage name
                education_stage_name = ' '.join(education_stage_name.split())  # Remove extra spaces
                
                # Debug message to track in error response
                debug_msg = f"DEBUG LOOKUP - Education stage: '{education_stage_name}' for campus {campus_id}"
                
                # Lookup education stage by title_vn
                education_stage_id = _lookup_education_stage_by_name(education_stage_name, campus_id)
                if education_stage_id:
                    # For SIS Subject, field name is "education_stage" not "education_stage_id"
                    doc_data["education_stage"] = education_stage_id
                    # Remove the original text value to avoid confusion
                    if "education_stage" in row_data:
                        row_data.pop("education_stage", None)
                else:
                    raise frappe.ValidationError(f"[SIS Subject] Không thể tìm thấy Education Stage: '{education_stage_name}' cho campus {campus_id} | {debug_msg}")
                    
            # Handle actual subject lookup
            actual_subject_name = None
            for key in ["actual_subject", "actual_subject_id", "Actual Subject"]:
                if key in row_data and row_data[key] and str(row_data[key]).strip():
                    actual_subject_name = str(row_data[key]).strip()
                    break
                    
            if actual_subject_name:
                # Normalize and clean the actual subject name
                actual_subject_name = ' '.join(actual_subject_name.split())  # Remove extra spaces
                frappe.logger().info(f"Row {row_num} - [SIS Subject] Looking up actual subject: '{actual_subject_name}'")
                
                # Lookup actual subject by title_vn
                actual_subject_id = _lookup_actual_subject_by_name(actual_subject_name, campus_id)
                if actual_subject_id:
                    # For SIS Subject, field name is "actual_subject_id" (as per JSON)
                    doc_data["actual_subject_id"] = actual_subject_id
                    # Remove the original text value to avoid confusion
                    if "actual_subject_id" in row_data:
                        row_data.pop("actual_subject_id", None)
                else:
                    raise frappe.ValidationError(f"[SIS Subject] Không thể tìm thấy Actual Subject: '{actual_subject_name}' cho campus {campus_id}")
                    
            # Handle timetable subject lookup
            timetable_subject_name = None
            for key in ["timetable_subject", "timetable_subject_id", "Timetable Subject"]:
                if key in row_data and row_data[key] and str(row_data[key]).strip():
                    timetable_subject_name = str(row_data[key]).strip()
                    break
                    
            if timetable_subject_name:
                # Normalize and clean the timetable subject name
                timetable_subject_name = ' '.join(timetable_subject_name.split())  # Remove extra spaces
                
                # Lookup timetable subject by title_vn
                timetable_subject_id = _lookup_timetable_subject_by_name(timetable_subject_name, campus_id)
                if timetable_subject_id:
                    # For SIS Subject, field name is "timetable_subject_id" (as per JSON)
                    doc_data["timetable_subject_id"] = timetable_subject_id
                    # Remove the original text value to avoid confusion
                    if "timetable_subject_id" in row_data:
                        row_data.pop("timetable_subject_id", None)
                else:
                    raise frappe.ValidationError(f"[SIS Subject] Không thể tìm thấy Timetable Subject: '{timetable_subject_name}' cho campus {campus_id}")
                    
        elif doctype == "SIS Actual Subject":
            
            # Handle curriculum lookup
            curriculum_name = None
            for key in ["curriculum", "curriculum_id", "Curriculum"]:
                if key in row_data and row_data[key] and str(row_data[key]).strip():
                    curriculum_name = str(row_data[key]).strip()
                    break
            
            if curriculum_name:
                # Normalize and clean the curriculum name
                curriculum_name = ' '.join(curriculum_name.split())  # Remove extra spaces
                frappe.logger().info(f"Row {row_num} - [SIS Actual Subject] Looking up curriculum: '{curriculum_name}'")
                
                # Lookup curriculum by title_vn
                curriculum_id = _lookup_curriculum_by_name(curriculum_name, campus_id)
                if curriculum_id:
                    doc_data["curriculum_id"] = curriculum_id
                    frappe.logger().info(f"Row {row_num} - [SIS Actual Subject] Found curriculum ID: {curriculum_id}")
                else:
                    raise frappe.ValidationError(f"[SIS Subject] Không thể tìm thấy Curriculum: '{curriculum_name}' cho campus {campus_id}")
            
            # Handle timetable subject lookup
            timetable_subject_name = None
            for key in ["timetable_subject", "timetable_subject_id", "Timetable Subject"]:
                if key in row_data and row_data[key] and str(row_data[key]).strip():
                    timetable_subject_name = str(row_data[key]).strip()
                    break
            
            if timetable_subject_name:
                # Normalize and clean the timetable subject name
                timetable_subject_name = ' '.join(timetable_subject_name.split())  # Remove extra spaces
                frappe.logger().info(f"Row {row_num} - [SIS Actual Subject] Looking up timetable subject: '{timetable_subject_name}'")
                
                # Lookup timetable subject by title_vn
                timetable_subject_id = _lookup_timetable_subject_by_name(timetable_subject_name, campus_id)
                if timetable_subject_id:
                    doc_data["timetable_subject_id"] = timetable_subject_id
                    frappe.logger().info(f"Row {row_num} - [SIS Actual Subject] Found timetable subject ID: {timetable_subject_id}")
                else:
                    raise frappe.ValidationError(f"Không thể tìm thấy Timetable Subject: '{timetable_subject_name}' cho campus {campus_id}")
            
            # Handle education stage lookup
            education_stage_name = None
            for key in ["stage", "education_stage", "education_stage_id", "Stage"]:
                if key in row_data and row_data[key] and str(row_data[key]).strip():
                    education_stage_name = str(row_data[key]).strip()
                    break
                    
            if education_stage_name:
                # Normalize and clean the education stage name
                education_stage_name = ' '.join(education_stage_name.split())  # Remove extra spaces
                frappe.logger().info(f"Row {row_num} - [SIS Actual Subject] Looking up education stage: '{education_stage_name}'")
                
                # Lookup education stage by title_vn
                education_stage_id = _lookup_education_stage_by_name(education_stage_name, campus_id)
                if education_stage_id:
                    doc_data["education_stage_id"] = education_stage_id
                    frappe.logger().info(f"Row {row_num} - [SIS Actual Subject] Found education stage ID: {education_stage_id}")
                else:
                    raise frappe.ValidationError(f"[{doctype}] Không thể tìm thấy Education Stage: '{education_stage_name}' cho campus {campus_id}")

        # Map Excel columns to DocType fields (regular fields)
        meta = frappe.get_meta(doctype)
        excluded_fields = ["name", "owner", "creation", "modified", "curriculum_id", "education_stage_id", "timetable_subject_id", "actual_subject_id", "education_stage"]
        for field in meta.fields:
            if field.fieldname in row_data and field.fieldname not in excluded_fields:
                # Regular field mapping (skip already processed reference fields)
                doc_data[field.fieldname] = row_data[field.fieldname]

        # Special handling for SIS Menu Category - don't set image_url if not provided
        # This allows it to be optional/undefined in the response
        pass

        # Check if record exists for update
        existing_doc = None
        if update_if_exists:
            # Try to find existing record based on unique fields
            existing_doc = _find_existing_record(doctype, doc_data)

        if dry_run:
            # Just validate without saving
            return {"success": True}

        if existing_doc:
            # Update existing record
            for key, value in doc_data.items():
                if key != "doctype" and value is not None:
                    existing_doc.set(key, value)
            existing_doc.save(ignore_permissions=True)
        else:
            # Create new record
            doc = frappe.get_doc(doc_data)
            doc.insert(ignore_permissions=True)

        frappe.db.commit()
        return {"success": True}

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def _find_existing_record(doctype, doc_data):
    """Find existing record for update"""
    # This is a simple implementation - in production, you'd want more sophisticated
    # unique key detection based on DocType configuration

    if doctype == "CRM Student" and doc_data.get("student_code"):
        name = frappe.db.exists(doctype, {"student_code": doc_data["student_code"]})
        return frappe.get_doc(doctype, name) if name else None

    if doctype == "SIS Subject" and doc_data.get("title"):
        name = frappe.db.exists(doctype, {"title": doc_data["title"]})
        return frappe.get_doc(doctype, name) if name else None

    return None


def _generate_error_report(job, errors):
    """Generate Excel error report"""
    try:
        import pandas as pd
        from frappe.utils.file_manager import save_file

        # Create error DataFrame
        error_data = []
        for error in errors:
            row_data = {"__row_number": error["row"], "__error": error["error"]}
            if isinstance(error.get("data"), dict):
                row_data.update(error["data"])
            else:
                row_data["__original_data"] = str(error.get("data", ""))[:1000]
            error_data.append(row_data)

        df_errors = pd.DataFrame(error_data)

        # Save to temporary file
        temp_file_path = f"/tmp/bulk_import_errors_{job.name}.xlsx"
        df_errors.to_excel(temp_file_path, index=False)

        # Upload file to Frappe
        with open(temp_file_path, "rb") as f:
            file_doc = save_file(
                f"bulk_import_errors_{job.name}.xlsx",
                f.read(),
                "SIS Bulk Import Job",
                job.name,
                is_private=1
            )

        # Clean up temp file
        os.unlink(temp_file_path)

        return file_doc.file_url

    except Exception as e:
        frappe.logger().error(f"Failed to generate error report: {str(e)}")
        return None


def _normalize_vietnamese_text(text):
    """Normalize Vietnamese text for better matching"""
    import unicodedata
    import re
    
    if not text:
        return ""
    
    # Convert to string and strip
    text = str(text).strip()
    
    # Normalize Unicode (NFC - Canonical Decomposition, followed by Canonical Composition)
    text = unicodedata.normalize('NFC', text)
    
    # Remove extra whitespace (including non-breaking spaces, tabs, etc.)
    text = re.sub(r'\s+', ' ', text)
    
    # Convert to lowercase for comparison
    text = text.lower()
    
    # Handle common variations/typos
    text = text.replace('cơ sở', 'cơ sở')  # Ensure consistent spacing
    text = text.replace('trung học', 'trung học')  # Ensure consistent spacing
    text = text.replace('phổ thông', 'phổ thông')  # Ensure consistent spacing
    
    return text


def _lookup_actual_subject_by_name(actual_subject_name, campus_id):
    """Lookup actual subject ID by title_vn with normalized matching"""
    try:
        # Get all actual subjects for the campus
        actual_subjects = frappe.get_all(
            "SIS Actual Subject",
            filters={"campus_id": campus_id},
            fields=["name", "title_vn"]
        )
        
        frappe.logger().info(f"Found {len(actual_subjects)} actual subjects for campus {campus_id}")
        for subj in actual_subjects:
            frappe.logger().info(f"Available actual subject: '{subj.get('title_vn', '')}' (ID: {subj.get('name', '')})")
        
        # Normalize search term
        normalized_search = _normalize_vietnamese_text(actual_subject_name)
        frappe.logger().info(f"Looking up actual subject: '{actual_subject_name}' -> '{normalized_search}'")
        
        # Try exact match first
        for subj in actual_subjects:
            subj_title = subj.get('title_vn', '')
            if subj_title == actual_subject_name:
                frappe.logger().info(f"Found actual subject with exact match: {subj_title}")
                return subj.get('name')
        
        # If not found, try normalized matching
        for subj in actual_subjects:
            subj_title = subj.get('title_vn', '')
            normalized_subj = _normalize_vietnamese_text(subj_title)
            
            frappe.logger().info(f"Comparing normalized: '{normalized_search}' with '{normalized_subj}'")
            if normalized_subj == normalized_search:
                frappe.logger().info(f"Found actual subject with normalized match: {subj_title}")
                return subj.get('name')
        
        # If still not found, try partial matching (contains)
        for subj in actual_subjects:
            subj_title = subj.get('title_vn', '')
            normalized_subj = _normalize_vietnamese_text(subj_title)
            
            # Try both directions: search term contains subject name OR subject name contains search term
            if (normalized_search in normalized_subj or normalized_subj in normalized_search) and len(normalized_search) > 2:
                frappe.logger().info(f"Found actual subject with partial match: '{subj_title}' matches '{actual_subject_name}'")
                return subj.get('name')
        
        # Log available actual subjects for debugging
        available_titles = [s.get('title_vn', '') for s in actual_subjects]
        frappe.logger().warning(f"Actual subject '{actual_subject_name}' not found. Available: {available_titles}")
        return None
        
    except Exception as e:
        frappe.logger().error(f"Error looking up actual subject: {str(e)}")
        return None


def _lookup_curriculum_by_name(curriculum_name, campus_id):
    """Lookup curriculum ID by title_vn with normalized matching"""
    try:
        # Get all curriculums for the campus
        curriculums = frappe.get_all(
            "SIS Curriculum",
            filters={"campus_id": campus_id},
            fields=["name", "title_vn"]
        )
        
        # Normalize search term
        normalized_search = _normalize_vietnamese_text(curriculum_name)
        frappe.logger().info(f"Looking up curriculum: '{curriculum_name}' -> '{normalized_search}'")
        
        # Try exact match first
        for curr in curriculums:
            curr_title = curr.get('title_vn', '')
            if curr_title == curriculum_name:
                frappe.logger().info(f"Found curriculum with exact match: {curr_title}")
                return curr.get('name')
        
        # If not found, try normalized matching
        for curr in curriculums:
            curr_title = curr.get('title_vn', '')
            normalized_curr = _normalize_vietnamese_text(curr_title)
            
            frappe.logger().info(f"Comparing normalized: '{normalized_search}' with '{normalized_curr}'")
            if normalized_curr == normalized_search:
                frappe.logger().info(f"Found curriculum with normalized match: {curr_title}")
                return curr.get('name')
        
        # Log available curriculums for debugging
        available_titles = [c.get('title_vn', '') for c in curriculums]
        frappe.logger().warning(f"Curriculum '{curriculum_name}' not found. Available: {available_titles}")
        return None
        
    except Exception as e:
        frappe.logger().error(f"Error looking up curriculum: {str(e)}")
        return None


def _lookup_education_stage_by_name(stage_name, campus_id):
    """Lookup education stage ID by title_vn with normalized matching"""
    try:
        # Get all education stages for the campus
        stages = frappe.get_all(
            "SIS Education Stage",
            filters={"campus_id": campus_id},
            fields=["name", "title_vn"]
        )
        
        frappe.logger().info(f"Found {len(stages)} education stages for campus {campus_id}")
        for stage in stages:
            frappe.logger().info(f"Available stage: '{stage.get('title_vn', '')}' (ID: {stage.get('name', '')})")
        
        # Normalize search term
        normalized_search = _normalize_vietnamese_text(stage_name)
        frappe.logger().info(f"Looking up education stage: '{stage_name}' -> '{normalized_search}'")
        
        # Try exact match first
        for stage in stages:
            stage_title = stage.get('title_vn', '')
            if stage_title == stage_name:
                frappe.logger().info(f"Found education stage with exact match: {stage_title}")
                return stage.get('name')
        
        # If not found, try normalized matching
        for stage in stages:
            stage_title = stage.get('title_vn', '')
            normalized_stage = _normalize_vietnamese_text(stage_title)
            
            frappe.logger().info(f"Comparing normalized: '{normalized_search}' with '{normalized_stage}'")
            if normalized_stage == normalized_search:
                frappe.logger().info(f"Found education stage with normalized match: {stage_title}")
                return stage.get('name')
        
        # If still not found, try partial matching (contains)
        for stage in stages:
            stage_title = stage.get('title_vn', '')
            normalized_stage = _normalize_vietnamese_text(stage_title)
            
            # Try both directions: search term contains stage name OR stage name contains search term
            if (normalized_search in normalized_stage or normalized_stage in normalized_search) and len(normalized_search) > 3:
                frappe.logger().info(f"Found education stage with partial match: '{stage_title}' matches '{stage_name}'")
                return stage.get('name')
        
        # Log available stages for debugging
        available_titles = [s.get('title_vn', '') for s in stages]
        frappe.logger().warning(f"Education stage '{stage_name}' not found. Available: {available_titles}")
        return None
        
    except Exception as e:
        frappe.logger().error(f"Error looking up education stage: {str(e)}")
        return None


def _lookup_timetable_subject_by_name(timetable_subject_name, campus_id):
    """Lookup timetable subject ID by title_vn with normalized matching"""
    try:
        # Get all timetable subjects for the campus
        timetable_subjects = frappe.get_all(
            "SIS Timetable Subject",
            filters={"campus_id": campus_id},
            fields=["name", "title_vn"]
        )
        
        # Normalize search term
        normalized_search = _normalize_vietnamese_text(timetable_subject_name)
        frappe.logger().info(f"Looking up timetable subject: '{timetable_subject_name}' -> '{normalized_search}'")
        
        # Try exact match first
        for tts in timetable_subjects:
            tts_title = tts.get('title_vn', '')
            if tts_title == timetable_subject_name:
                frappe.logger().info(f"Found timetable subject with exact match: {tts_title}")
                return tts.get('name')
        
        # If not found, try normalized matching
        for tts in timetable_subjects:
            tts_title = tts.get('title_vn', '')
            normalized_tts = _normalize_vietnamese_text(tts_title)
            
            frappe.logger().info(f"Comparing normalized: '{normalized_search}' with '{normalized_tts}'")
            if normalized_tts == normalized_search:
                frappe.logger().info(f"Found timetable subject with normalized match: {tts_title}")
                return tts.get('name')
        
        # Log available timetable subjects for debugging
        available_titles = [t.get('title_vn', '') for t in timetable_subjects]
        frappe.logger().warning(f"Timetable subject '{timetable_subject_name}' not found. Available: {available_titles}")
        return None
        
    except Exception as e:
        frappe.logger().error(f"Error looking up timetable subject: {str(e)}")
        return None
