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
        
        # Merge any extra form data (e.g., academic_year) into options
        # This allows frontend to pass academic_year via extraFormData
        if "academic_year" in data:
            options["academic_year"] = data["academic_year"]
            frappe.logger().info(f"Added academic_year to options: {data['academic_year']}")
        
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

        # Log basic dataframe info for troubleshooting
        frappe.logger().info(f"Processing Excel file with {len(df)} rows, columns: {list(df.columns)}")

        # Check if file has enough rows (at least header + 1 data row)
        if len(df) == 0:
            return {
                "success": False,
                "message": "File is empty. Please add data to the template."
            }

        if len(df) == 1:
            # File has only 1 row - special handling for single-row files
            if job.doctype_target == "CRM Student":
                # Special logic for student data
                row_data = dict(df.iloc[0])

                # Check if this row looks like actual student data rather than headers
                has_student_data = False
                for col, value in row_data.items():
                    if pd.notna(value):
                        val_str = str(value).strip()
                        # Check for student data patterns
                        if (col.lower() in ['student name', 'student code', 'gender'] and val_str and
                            not val_str.lower().startswith('student') and
                            not val_str.lower().startswith('gender') and
                            val_str.lower() not in ['male', 'female', 'others', 'nam', 'nữ', 'khác']):
                            has_student_data = True
                            break

                if has_student_data:
                    # This is actually data, not header - treat the single row as data
                    df = pd.DataFrame([{
                        'Student Name': row_data.get('Student Name', ''),
                        'Student Code': row_data.get('Student Code', ''),
                        'Date of Birth': row_data.get('Date of Birth', ''),
                        'Gender': row_data.get('Gender', '')
                    }])
                    # Skip the header skipping logic below since this is already data
                    skipped_rows = 0
                else:
                    # This is just header row
                    return {
                        "success": False,
                        "message": "File contains only header row. Please add student data starting from row 2."
                    }
            elif job.doctype_target == "SIS Class":
                # Special logic for class data
                row_data = dict(df.iloc[0])

                # Check if this row looks like actual class data rather than headers
                has_class_data = False
                for col, value in row_data.items():
                    if pd.notna(value):
                        val_str = str(value).strip()
                        # Check for class data patterns - if column name is in our mapping and value doesn't look like header
                        if (col.lower() in ['title', 'short_title', 'education_grade', 'academic_program', 'class_type', 'school_year_id', 'campus_id'] and
                            val_str and
                            not val_str.lower().startswith(('title', 'short_title', 'education_grade', 'academic_program', 'class_type', 'school_year_id', 'campus_id')) and
                            not val_str.lower() in ['regular', 'mixed', 'club', 'lớp chính quy', 'lớp chạy', 'câu lạc bộ']):
                            has_class_data = True
                            break

                if has_class_data:
                    # This is actually data, not header - treat the single row as data
                    df = pd.DataFrame([row_data])
                    # Skip the header skipping logic below since this is already data
                    skipped_rows = 0
                else:
                    # This is just header row
                    return {
                        "success": False,
                        "message": "File contains only header row. Please add class data starting from row 2."
                    }
            else:
                # For other doctypes, single row is likely header only
                return {
                    "success": False,
                    "message": "File contains only header row. Please add data starting from row 2."
                }

        # Row processing logic - handle both cases: with header and without header
        if skipped_rows == 0:
            # Already processed single data row case, df is ready
            pass
        else:
            # Normal case: skip header and check for sample data
            df = df.iloc[1:]  # Skip header row, start from row 2
            skipped_rows = 1

            if len(df) > 0:
                first_row = df.iloc[0]

                # Check if this is clearly sample/instruction data
                # Only skip if ALL non-empty cells contain sample indicators
                non_empty_count = 0
                sample_indicators_count = 0

                for val in first_row.values:
                    if pd.notna(val) and str(val).strip():
                        non_empty_count += 1
                        val_str = str(val).strip().lower()
                        if ('←' in val_str or
                            'fill your data' in val_str or
                            'sample' in val_str or
                            'ví dụ' in val_str or
                            val_str in ['nam', 'nữ', 'khác'] or
                            val_str.startswith('student_') or
                            '@example.com' in val_str):
                            sample_indicators_count += 1

                # Only consider it sample row if ALL non-empty cells are sample indicators
                is_sample_row = non_empty_count > 0 and sample_indicators_count == non_empty_count

                if is_sample_row and len(df) > 1:
                    # Skip this row and start from next row
                    df = df.iloc[1:]
                    skipped_rows = 2

        # Remove completely empty rows
        df = df.dropna(how='all')

        total_rows = len(df)

        if total_rows == 0:
            return {
                "success": False,
                "message": "No data found in file. Please fill data starting from row 2 or 3 in the template."
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
            },
            "SIS Class": {
                # Map Excel columns to SIS Class fields
                "title": "title",
                "short_title": "short_title",
                "education_grade": "education_grade",
                "academic_program": "academic_program",
                "homeroom_teacher": "homeroom_teacher",
                "vice_homeroom_teacher": "vice_homeroom_teacher",
                "room": "room",
                "class_type": "class_type",
                "school_year_id": "school_year_id",
                "campus_id": "campus_id"
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
            original_start_index = i + skipped_rows + 1  # +skipped_rows for header/sample rows, +1 for Excel 1-indexing
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

                errors.append({
                    "row": row_num,
                    "data": row_data,
                    "error": result["error"]
                })

        except Exception as e:
            error_count += 1
            errors.append({
                "row": row_num,
                "data": str(row.to_dict())[:500],  # Limit data size
                "error": str(e)
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
        
        frappe.logger().info(f"[_process_single_record] Row {row_num} - Processing doctype: {doctype}")
        frappe.logger().info(f"[_process_single_record] Row {row_num} - Row data keys: {list(row_data.keys())}")

        # Handle campus_id - use from file or default to user's campus
        campus_id = row_data.get("campus_id")
        if not campus_id:
            campus_id = job.campus_id
            frappe.logger().info(f"Row {row_num} - Using job campus_id: '{campus_id}'")
        else:
            frappe.logger().info(f"Row {row_num} - Using campus_id from Excel: '{campus_id}'")
        
        # Normalize campus_id - handle case variations (convert to uppercase to match DB format)
        if campus_id:
            original_campus_id = campus_id
            campus_id = campus_id.upper()
            frappe.logger().info(f"Row {row_num} - Normalized campus_id: '{original_campus_id}' -> '{campus_id}'")

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

        elif doctype == "SIS Class Student":

            # Handle bulk import for SIS Class Student assignment
            # Expected columns: student_code, class_short_title

            # Get school_year_id from job options (extraFormData) first, then from row_data
            options = job.get_options_dict()
            school_year_id = options.get("academic_year") or row_data.get("academic_year") or row_data.get("school_year_id")
            
            frappe.logger().info(f"[SIS Class Student] Row {row_num} - academic_year from options: {options.get('academic_year')}")
            frappe.logger().info(f"[SIS Class Student] Row {row_num} - school_year_id resolved: {school_year_id}")
            
            if not school_year_id:
                # Try to get from options or find active school year
                try:
                    active_year = frappe.get_all(
                        "SIS School Year",
                        filters={"is_enable": 1},
                        fields=["name"],
                        order_by="start_date desc",
                        limit=1
                    )
                    if active_year:
                        school_year_id = active_year[0].name
                        frappe.logger().info(f"[SIS Class Student] Row {row_num} - Using active year: {school_year_id}")
                except Exception as e:
                    frappe.logger().error(f"[SIS Class Student] Row {row_num} - Error finding active year: {str(e)}")

            if not school_year_id:
                raise frappe.ValidationError(f"[{doctype}] Không thể xác định năm học. Vui lòng cung cấp academic_year trong file hoặc đảm bảo có năm học đang active.")

            # Handle student_code lookup
            student_code = None
            for key in ["student_code", "studentcode", "student id", "mã học sinh", "mã học sinh*", "student_id"]:
                if key in row_data and row_data[key] and str(row_data[key]).strip():
                    student_code = str(row_data[key]).strip()
                    frappe.logger().info(f"[SIS Class Student] Row {row_num} - Found student_code from key '{key}': {student_code}")
                    break

            if not student_code:
                frappe.logger().error(f"[SIS Class Student] Row {row_num} - No student_code found. Available keys: {list(row_data.keys())}")
                raise frappe.ValidationError(f"[{doctype}] Thiếu mã học sinh trong hàng {row_num}")

            # Lookup student by student_code
            student_id = None
            try:
                frappe.logger().info(f"[SIS Class Student] Row {row_num} - Looking up student with code: {student_code}")
                students = frappe.get_all(
                    "CRM Student",
                    filters={"student_code": student_code},
                    fields=["name", "full_name"],
                    limit=1
                )
                if students:
                    student_id = students[0].name
                    frappe.logger().info(f"[SIS Class Student] Row {row_num} - Found student: {student_id} ({students[0].get('full_name', '')})")
                else:
                    frappe.logger().error(f"[SIS Class Student] Row {row_num} - Student not found with code: {student_code}")
                    raise frappe.ValidationError(f"[{doctype}] Không tìm thấy học sinh với mã '{student_code}'")
            except frappe.ValidationError:
                raise
            except Exception as e:
                frappe.logger().error(f"[SIS Class Student] Row {row_num} - Error looking up student: {str(e)}")
                raise frappe.ValidationError(f"[{doctype}] Lỗi khi tìm học sinh với mã '{student_code}': {str(e)}")

            # Handle class_short_title lookup
            class_short_title = None
            for key in ["class_short_title", "classshorttitle", "class short title", "short_title", "short title", "mã lớp", "mã lớp*", "class_name", "class"]:
                if key in row_data and row_data[key] and str(row_data[key]).strip():
                    class_short_title = str(row_data[key]).strip()
                    frappe.logger().info(f"[SIS Class Student] Row {row_num} - Found class_short_title from key '{key}': {class_short_title}")
                    break

            if not class_short_title:
                frappe.logger().error(f"[SIS Class Student] Row {row_num} - No class_short_title found. Available keys: {list(row_data.keys())}")
                raise frappe.ValidationError(f"[{doctype}] Thiếu mã lớp (class_short_title) trong hàng {row_num}")

            # Lookup class by short_title
            class_id = None
            class_title = None
            try:
                # First try exact match by short_title
                frappe.logger().info(f"[SIS Class Student] Row {row_num} - Looking up class: short_title={class_short_title}, year={school_year_id}, campus={campus_id}")
                classes = frappe.get_all(
                    "SIS Class",
                    filters={
                        "short_title": class_short_title,
                        "school_year_id": school_year_id,
                        "campus_id": campus_id
                    },
                    fields=["name", "title"],
                    limit=1
                )
                if classes:
                    class_id = classes[0].name
                    class_title = classes[0].get('title', class_short_title)
                    frappe.logger().info(f"[SIS Class Student] Row {row_num} - Found class: {class_id} ({class_title})")
                else:
                    frappe.logger().error(f"[SIS Class Student] Row {row_num} - Class not found: {class_short_title}")
                    raise frappe.ValidationError(f"[{doctype}] Không tìm thấy lớp với mã '{class_short_title}' trong năm học {school_year_id} và campus {campus_id}")

            except frappe.ValidationError:
                raise
            except Exception as e:
                frappe.logger().error(f"[SIS Class Student] Row {row_num} - Error looking up class: {str(e)}")
                raise frappe.ValidationError(f"[{doctype}] Lỗi khi tìm lớp với mã '{class_short_title}': {str(e)}")

            # Check for existing assignment
            existing_assignment = frappe.get_all(
                "SIS Class Student",
                filters={
                    "student_id": student_id,
                    "class_id": class_id,
                    "school_year_id": school_year_id
                },
                fields=["name"],
                limit=1
            )

            if existing_assignment:
                # Assignment already exists - skip
                frappe.logger().info(f"[{doctype}] Row {row_num} - Assignment already exists for student {student_code} in class {class_title}")
                return {"success": True, "message": f"Học sinh {student_code} đã được phân vào lớp {class_title}"}

            # Create new SIS Class Student record
            try:
                class_student_doc = frappe.get_doc({
                    "doctype": "SIS Class Student",
                    "class_id": class_id,
                    "student_id": student_id,
                    "school_year_id": school_year_id,
                    "class_type": "regular",  # Default to regular for bulk import
                    "campus_id": campus_id
                })

                class_student_doc.insert(ignore_permissions=True)
                frappe.db.commit()

                success_msg = f"Đã phân học sinh {student_code} vào lớp {class_title}"
                frappe.logger().info(f"[{doctype}] Row {row_num} - {success_msg}")
                return {"success": True, "message": success_msg}
            except Exception as e:
                frappe.logger().error(f"[{doctype}] Row {row_num} - Error creating assignment: {str(e)}")
                raise frappe.ValidationError(f"[{doctype}] Lỗi khi tạo phân lớp cho học sinh {student_code}: {str(e)}")

        elif doctype == "SIS Class":

            # Collect all resolution errors for better user feedback
            resolution_errors = []

            # Handle school year lookup first (required field)
            school_year_name = None
            for key in ["school_year_id", "school_year", "year", "năm học"]:
                if key in row_data and row_data[key] and str(row_data[key]).strip():
                    school_year_name = str(row_data[key]).strip()
                    frappe.logger().info(f"Row {row_num} - [SIS Class] Found school year key '{key}' with value: '{school_year_name}'")
                    break

            if school_year_name:
                # Normalize and clean the school year name
                school_year_name = ' '.join(school_year_name.split())  # Remove extra spaces
                frappe.logger().info(f"Row {row_num} - [SIS Class] Looking up school year: '{school_year_name}' for campus: '{campus_id}'")

                # Try to find by name first, then title_vn, title_en
                # Filter by campus_id for school years
                school_year_id = None
                try:
                    base_filters = {"campus_id": campus_id} if campus_id else {}
                    
                    # Debug: List all available school years for this campus
                    all_years = frappe.get_all(
                        "SIS School Year",
                        filters={"campus_id": campus_id} if campus_id else {},
                        fields=["name", "title_vn", "title_en", "campus_id"]
                    )
                    frappe.logger().info(f"Row {row_num} - [SIS Class] Available School Years for campus '{campus_id}': {all_years}")

                    # Try direct name match
                    name_filters = base_filters.copy()
                    name_filters["name"] = school_year_name
                    frappe.logger().info(f"Row {row_num} - [SIS Class] Searching School Year by name with filters: {name_filters}")
                    name_hit = frappe.get_all(
                        "SIS School Year",
                        filters=name_filters,
                        fields=["name", "campus_id"],
                        limit=1
                    )
                    if name_hit:
                        school_year_id = name_hit[0].name
                        frappe.logger().info(f"Row {row_num} - [SIS Class] Found school year by name: {school_year_id} (campus: {name_hit[0].get('campus_id')})")
                    else:
                        # Try title_vn
                        title_filters = base_filters.copy()
                        title_filters["title_vn"] = school_year_name
                        frappe.logger().info(f"Row {row_num} - [SIS Class] Searching School Year by title_vn with filters: {title_filters}")
                        title_hit = frappe.get_all(
                            "SIS School Year",
                            filters=title_filters,
                            fields=["name", "campus_id"],
                            limit=1
                        )
                        if title_hit:
                            school_year_id = title_hit[0].name
                            frappe.logger().info(f"Row {row_num} - [SIS Class] Found school year by title_vn: {school_year_id} (campus: {title_hit[0].get('campus_id')})")
                        else:
                            # Try title_en
                            title_en_filters = base_filters.copy()
                            title_en_filters["title_en"] = school_year_name
                            frappe.logger().info(f"Row {row_num} - [SIS Class] Searching School Year by title_en with filters: {title_en_filters}")
                            title_en_hit = frappe.get_all(
                                "SIS School Year",
                                filters=title_en_filters,
                                fields=["name", "campus_id"],
                                limit=1
                            )
                            if title_en_hit:
                                school_year_id = title_en_hit[0].name
                                frappe.logger().info(f"Row {row_num} - [SIS Class] Found school year by title_en: {school_year_id} (campus: {title_en_hit[0].get('campus_id')})")
                except Exception as e:
                    frappe.logger().error(f"Error looking up school year '{school_year_name}': {str(e)}")

                # Fallback: try without campus filter if not found
                if not school_year_id:
                    frappe.logger().info(f"Row {row_num} - [SIS Class] School year not found with campus filter, trying without campus filter...")
                    try:
                        # Try title_vn without campus filter
                        fallback_hit = frappe.get_all(
                            "SIS School Year",
                            filters={"title_vn": school_year_name},
                            fields=["name", "campus_id"],
                            limit=1
                        )
                        if fallback_hit:
                            school_year_id = fallback_hit[0].name
                            frappe.logger().info(f"Row {row_num} - [SIS Class] Found school year by title_vn (no campus filter): {school_year_id} (campus: {fallback_hit[0].get('campus_id')})")
                        else:
                            # Try title_en without campus filter
                            fallback_en_hit = frappe.get_all(
                                "SIS School Year",
                                filters={"title_en": school_year_name},
                                fields=["name", "campus_id"],
                                limit=1
                            )
                            if fallback_en_hit:
                                school_year_id = fallback_en_hit[0].name
                                frappe.logger().info(f"Row {row_num} - [SIS Class] Found school year by title_en (no campus filter): {school_year_id} (campus: {fallback_en_hit[0].get('campus_id')})")
                    except Exception as e:
                        frappe.logger().error(f"Error in fallback school year lookup: {str(e)}")

                if school_year_id:
                    doc_data["school_year_id"] = school_year_id
                    frappe.logger().info(f"Row {row_num} - [SIS Class] Found school year ID: {school_year_id}")
                else:
                    resolution_errors.append(f"School Year: '{school_year_name}' for campus '{campus_id}'")

            # Handle education grade lookup
            education_grade_name = None
            for key in ["education_grade", "grade", "khối"]:
                if key in row_data and row_data[key] and str(row_data[key]).strip():
                    education_grade_name = str(row_data[key]).strip()
                    frappe.logger().info(f"Row {row_num} - [SIS Class] Found education grade key '{key}' with value: '{education_grade_name}'")
                    break

            if education_grade_name:
                # Normalize and clean the education grade name
                education_grade_name = ' '.join(education_grade_name.split())  # Remove extra spaces
                frappe.logger().info(f"Row {row_num} - [SIS Class] Looking up education grade: '{education_grade_name}' for campus: '{campus_id}'")

                # Try to find by title_vn first, then grade_name, then title_en
                # Filter by campus_id for education grades
                education_grade_id = None
                try:
                    base_filters = {"campus_id": campus_id} if campus_id else {}
                    
                    # Debug: List all available education grades for this campus
                    all_grades = frappe.get_all(
                        "SIS Education Grade",
                        filters={"campus_id": campus_id} if campus_id else {},
                        fields=["name", "title_vn", "title_en", "campus_id"]
                    )
                    frappe.logger().info(f"Row {row_num} - [SIS Class] Available Education Grades for campus '{campus_id}': {all_grades}")

                    # Try title_vn first (most likely for Vietnamese data)
                    title_filters = base_filters.copy()
                    title_filters["title_vn"] = education_grade_name
                    frappe.logger().info(f"Row {row_num} - [SIS Class] Searching Education Grade with filters: {title_filters}")
                    title_hit = frappe.get_all(
                        "SIS Education Grade",
                        filters=title_filters,
                        fields=["name", "campus_id"],
                        limit=1
                    )
                    if title_hit:
                        education_grade_id = title_hit[0].name
                        frappe.logger().info(f"Row {row_num} - [SIS Class] Found education grade by title_vn: {education_grade_id} (campus: {title_hit[0].get('campus_id')})")
                    else:
                        # Try title_en
                        title_en_filters = base_filters.copy()
                        title_en_filters["title_en"] = education_grade_name
                        frappe.logger().info(f"Row {row_num} - [SIS Class] Searching Education Grade by title_en with filters: {title_en_filters}")
                        title_en_hit = frappe.get_all(
                            "SIS Education Grade",
                            filters=title_en_filters,
                            fields=["name", "campus_id"],
                            limit=1
                        )
                        if title_en_hit:
                            education_grade_id = title_en_hit[0].name
                            frappe.logger().info(f"Row {row_num} - [SIS Class] Found education grade by title_en: {education_grade_id} (campus: {title_en_hit[0].get('campus_id')})")
                except Exception as e:
                    frappe.logger().error(f"Error looking up education grade '{education_grade_name}': {str(e)}")

                # Fallback: try without campus filter if not found
                if not education_grade_id:
                    frappe.logger().info(f"Row {row_num} - [SIS Class] Education grade not found with campus filter, trying without campus filter...")
                    try:
                        # Try title_vn without campus filter
                        fallback_hit = frappe.get_all(
                            "SIS Education Grade",
                            filters={"title_vn": education_grade_name},
                            fields=["name", "campus_id"],
                            limit=1
                        )
                        if fallback_hit:
                            education_grade_id = fallback_hit[0].name
                            frappe.logger().info(f"Row {row_num} - [SIS Class] Found education grade by title_vn (no campus filter): {education_grade_id} (campus: {fallback_hit[0].get('campus_id')})")
                        else:
                            # Try title_en without campus filter
                            fallback_en_hit = frappe.get_all(
                                "SIS Education Grade",
                                filters={"title_en": education_grade_name},
                                fields=["name", "campus_id"],
                                limit=1
                            )
                            if fallback_en_hit:
                                education_grade_id = fallback_en_hit[0].name
                                frappe.logger().info(f"Row {row_num} - [SIS Class] Found education grade by title_en (no campus filter): {education_grade_id} (campus: {fallback_en_hit[0].get('campus_id')})")
                    except Exception as e:
                        frappe.logger().error(f"Error in fallback education grade lookup: {str(e)}")

                if education_grade_id:
                    doc_data["education_grade"] = education_grade_id
                    frappe.logger().info(f"Row {row_num} - [SIS Class] Found education grade ID: {education_grade_id}")
                else:
                    resolution_errors.append(f"Education Grade: '{education_grade_name}' for campus '{campus_id}'")

            # Handle academic program lookup
            academic_program_name = None
            for key in ["academic_program", "program", "hệ"]:
                if key in row_data and row_data[key] and str(row_data[key]).strip():
                    academic_program_name = str(row_data[key]).strip()
                    frappe.logger().info(f"Row {row_num} - [SIS Class] Found academic program key '{key}' with value: '{academic_program_name}'")
                    break

            if academic_program_name:
                # Normalize and clean the academic program name
                academic_program_name = ' '.join(academic_program_name.split())  # Remove extra spaces
                frappe.logger().info(f"Row {row_num} - [SIS Class] Looking up academic program: '{academic_program_name}' for campus: '{campus_id}'")

                # Try to find by title_vn first, then title_en
                # Filter by campus_id for academic programs
                academic_program_id = None
                try:
                    base_filters = {"campus_id": campus_id} if campus_id else {}
                    
                    # Debug: List all available academic programs for this campus
                    all_programs = frappe.get_all(
                        "SIS Academic Program",
                        filters={"campus_id": campus_id} if campus_id else {},
                        fields=["name", "title_vn", "title_en", "campus_id"]
                    )
                    frappe.logger().info(f"Row {row_num} - [SIS Class] Available Academic Programs for campus '{campus_id}': {all_programs}")

                    # Try title_vn
                    title_filters = base_filters.copy()
                    title_filters["title_vn"] = academic_program_name
                    frappe.logger().info(f"Row {row_num} - [SIS Class] Searching Academic Program by title_vn with filters: {title_filters}")
                    title_hit = frappe.get_all(
                        "SIS Academic Program",
                        filters=title_filters,
                        fields=["name", "campus_id"],
                        limit=1
                    )
                    if title_hit:
                        academic_program_id = title_hit[0].name
                        frappe.logger().info(f"Row {row_num} - [SIS Class] Found academic program by title_vn: {academic_program_id} (campus: {title_hit[0].get('campus_id')})")
                    else:
                        # Try title_en
                        title_en_filters = base_filters.copy()
                        title_en_filters["title_en"] = academic_program_name
                        frappe.logger().info(f"Row {row_num} - [SIS Class] Searching Academic Program by title_en with filters: {title_en_filters}")
                        title_en_hit = frappe.get_all(
                            "SIS Academic Program",
                            filters=title_en_filters,
                            fields=["name", "campus_id"],
                            limit=1
                        )
                        if title_en_hit:
                            academic_program_id = title_en_hit[0].name
                            frappe.logger().info(f"Row {row_num} - [SIS Class] Found academic program by title_en: {academic_program_id} (campus: {title_en_hit[0].get('campus_id')})")
                except Exception as e:
                    frappe.logger().error(f"Error looking up academic program '{academic_program_name}': {str(e)}")

                # Fallback: try without campus filter if not found
                if not academic_program_id:
                    frappe.logger().info(f"Row {row_num} - [SIS Class] Academic program not found with campus filter, trying without campus filter...")
                    try:
                        # Try title_vn without campus filter
                        fallback_hit = frappe.get_all(
                            "SIS Academic Program",
                            filters={"title_vn": academic_program_name},
                            fields=["name", "campus_id"],
                            limit=1
                        )
                        if fallback_hit:
                            academic_program_id = fallback_hit[0].name
                            frappe.logger().info(f"Row {row_num} - [SIS Class] Found academic program by title_vn (no campus filter): {academic_program_id} (campus: {fallback_hit[0].get('campus_id')})")
                        else:
                            # Try title_en without campus filter
                            fallback_en_hit = frappe.get_all(
                                "SIS Academic Program",
                                filters={"title_en": academic_program_name},
                                fields=["name", "campus_id"],
                                limit=1
                            )
                            if fallback_en_hit:
                                academic_program_id = fallback_en_hit[0].name
                                frappe.logger().info(f"Row {row_num} - [SIS Class] Found academic program by title_en (no campus filter): {academic_program_id} (campus: {fallback_en_hit[0].get('campus_id')})")
                    except Exception as e:
                        frappe.logger().error(f"Error in fallback academic program lookup: {str(e)}")

                if academic_program_id:
                    doc_data["academic_program"] = academic_program_id
                    frappe.logger().info(f"Row {row_num} - [SIS Class] Found academic program ID: {academic_program_id}")
                else:
                    resolution_errors.append(f"Academic Program: '{academic_program_name}' for campus '{campus_id}'")

            # If there are resolution errors, raise a comprehensive error
            if resolution_errors:
                error_msg = f"Không thể tìm thấy {', '.join(resolution_errors)}"
                raise frappe.ValidationError(error_msg)

        # Special field processing before mapping
        # Convert gender values to lowercase for proper validation
        if 'gender' in row_data and row_data['gender']:
            gender_value = str(row_data['gender']).strip().lower()
            # Map common variations to standard values
            gender_mapping = {
                'male': 'male',
                'nam': 'male',
                'm': 'male',
                'female': 'female',
                'nữ': 'female',
                'f': 'female',
                'others': 'others',
                'khác': 'others',
                'other': 'others',
                'o': 'others'
            }
            row_data['gender'] = gender_mapping.get(gender_value, gender_value)

        # Map Excel columns to DocType fields (regular fields)
        # Skip field mapping for doctypes that are handled entirely by custom logic
        if doctype not in ["SIS Class Student"]:
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

    if doctype == "SIS Class" and doc_data.get("title"):
        name = frappe.db.exists(doctype, {"title": doc_data["title"]})
        return frappe.get_doc(doctype, name) if name else None

    # For SIS Class Student, check for existing assignment
    if doctype == "SIS Class Student":
        # Look for existing assignment with same student, class, and school year
        existing = frappe.get_all(
            doctype,
            filters={
                "student_id": doc_data.get("student_id"),
                "class_id": doc_data.get("class_id"),
                "school_year_id": doc_data.get("school_year_id")
            },
            fields=["name"],
            limit=1
        )
        if existing:
            return frappe.get_doc(doctype, existing[0].name)

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
