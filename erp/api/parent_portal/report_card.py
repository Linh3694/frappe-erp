
"""
Report Card API for Parent Portal
Parents can view their children's report cards
"""

import frappe
from frappe import _
import json
from erp.utils.api_response import success_response, error_response


def _get_parent_student_ids(parent_email):
    """Get all student IDs for a parent"""
    # Parent email format: guardian_id@parent.wellspring.edu.vn
    guardian_id = parent_email.split('@')[0]
    
    # Find guardian (ignore permissions since this is internal validation)
    guardians = frappe.get_all(
        "CRM Guardian",
        filters={"guardian_id": guardian_id},
        fields=["name"],
        limit=1,
        ignore_permissions=True
    )
    
    if not guardians:
        return []
    
    guardian_name = guardians[0]['name']
    
    # Find students through family relationships (ignore permissions)
    relationships = frappe.get_all(
        "CRM Family Relationship",
        filters={"guardian": guardian_name},
        fields=["student"],
        pluck="student",
        ignore_permissions=True
    )
    
    return relationships


@frappe.whitelist(allow_guest=False, methods=["POST"])
def get_student_report_cards():
    """
    Get all report cards for a specific student (parent view)
    
    Request body:
        - student_id: Student document name
        - school_year (optional): Filter by school year
        - semester_part (optional): Filter by semester
    
    Returns:
        List of report cards with basic info
    """
    try:
        # Get request body
        body = {}
        try:
            request_data = frappe.request.get_data(as_text=True)
            if request_data:
                body = json.loads(request_data)
        except Exception:
            body = frappe.form_dict
        
        student_id = body.get('student_id')
        school_year = body.get('school_year')
        semester_part = body.get('semester_part')
        
        frappe.logger().info(f"📚 get_student_report_cards called:")
        frappe.logger().info(f"   - student_id: {student_id}")
        frappe.logger().info(f"   - parent_email: {frappe.session.user}")
        frappe.logger().info(f"   - school_year: {school_year}")
        frappe.logger().info(f"   - semester_part: {semester_part}")
        
        if not student_id:
            return error_response(
                message="Missing student_id",
                code="MISSING_PARAMS",
                logs=["student_id is required"]
            )
        
        # Verify parent has access to this student
        parent_email = frappe.session.user
        parent_student_ids = _get_parent_student_ids(parent_email)
        
        if student_id not in parent_student_ids:
            return error_response(
                message="You do not have permission to view this student's report cards",
                code="PERMISSION_DENIED",
                logs=[f"Student {student_id} not in parent's student list: {parent_student_ids}"]
            )
        
        # Build filters - only show approved reports to parents
        filters = {
            "student_id": student_id,
            "is_approved": 1  # Only show approved reports
        }
        
        if school_year:
            filters["school_year"] = school_year
        
        if semester_part:
            filters["semester_part"] = semester_part
        
        # Query report cards (ignore permissions since we verified parent access above)
        report_cards = frappe.get_all(
            "SIS Student Report Card",
            filters=filters,
            fields=[
                "name",
                "title",
                "template_id",
                "form_id",
                "class_id",
                "student_id",
                "school_year",
                "semester_part",
                "status",
                "creation",
                "modified"
            ],
            order_by="school_year desc, semester_part desc, modified desc",
            ignore_permissions=True
        )
        
        # Get additional info for each report card
        enriched_reports = []
        for report in report_cards:
            # Get class info (frappe.db.get_value doesn't check permissions by default)
            class_info = frappe.db.get_value(
                "SIS Class",
                report["class_id"],
                ["short_title", "title"],
                as_dict=True
            ) or {}
            
            # Get school year title (title_vn or title_en)
            school_year_title = report["school_year"]  # Default to ID
            if report.get("school_year"):
                year_info = frappe.db.get_value(
                    "SIS School Year",
                    report["school_year"],
                    ["title_vn", "title_en", "name"],
                    as_dict=True
                )
                if year_info:
                    school_year_title = year_info.get("title_vn") or year_info.get("title_en") or report["school_year"]
            
            enriched_reports.append({
                "name": report["name"],
                "title": report["title"],
                "template_id": report["template_id"],
                "form_id": report["form_id"],
                "class_id": report["class_id"],
                "class_short_title": class_info.get("short_title", ""),
                "class_code": class_info.get("title", ""),
                "student_id": report["student_id"],
                "school_year": school_year_title,  # Use title_vn/title_en instead of ID
                "semester_part": report["semester_part"],
                "status": report["status"],
                "creation": report["creation"],
                "modified": report["modified"]
            })
        
        frappe.logger().info(f"✅ Found {len(enriched_reports)} report cards for student {student_id}")
        
        return success_response(
            data={
                "report_cards": enriched_reports,
                "logs": [
                    f"Found {len(enriched_reports)} report cards",
                    f"Student: {student_id}",
                    f"Filters: {filters}"
                ]
            },
            message=f"Found {len(enriched_reports)} report cards"
        )
        
    except Exception as e:
        frappe.logger().error(f"❌ Error in get_student_report_cards: {str(e)}")
        frappe.logger().error(frappe.get_traceback())
        return error_response(
            message=f"Error fetching report cards: {str(e)}",
            code="SERVER_ERROR",
            logs=[str(e), frappe.get_traceback()]
        )


@frappe.whitelist(allow_guest=False, methods=["POST"])
def get_report_card_detail():
    """
    Get detailed report card data for rendering (parent view)
    This uses the same backend rendering API as the admin portal
    
    Request body:
        - report_id: Report card document name
    
    Returns:
        Structured report data for frontend rendering
    """
    logs = []  # Collect logs to return in response
    
    try:
        # Get request body
        body = {}
        try:
            request_data = frappe.request.get_data(as_text=True)
            if request_data:
                body = json.loads(request_data)
        except Exception:
            body = frappe.form_dict
        
        report_id = body.get('report_id')
        
        log_msg = f"📖 get_report_card_detail called with report_id: {report_id}, parent: {frappe.session.user}"
        frappe.logger().info(log_msg)
        logs.append(log_msg)
        
        if not report_id:
            return error_response(
                message="Missing report_id",
                code="MISSING_PARAMS",
                logs=["report_id is required"] + logs
            )
        
        # Get report card basic info to verify access (ignore permissions for now, we'll check parent access below)
        try:
            log_msg = f"Loading report {report_id}..."
            frappe.logger().info(log_msg)
            logs.append(log_msg)
            
            report = frappe.get_doc("SIS Student Report Card", report_id, ignore_permissions=True)
            
            log_msg = f"✓ Report loaded: student_id={report.student_id}"
            frappe.logger().info(log_msg)
            logs.append(log_msg)
        except frappe.DoesNotExistError:
            log_msg = f"❌ Report {report_id} not found"
            frappe.logger().error(log_msg)
            logs.append(log_msg)
            return error_response(
                message="Report card not found",
                code="NOT_FOUND",
                logs=logs
            )
        
        # Verify parent has access to this student
        parent_email = frappe.session.user
        log_msg = f"Verifying parent {parent_email} access..."
        frappe.logger().info(log_msg)
        logs.append(log_msg)
        
        parent_student_ids = _get_parent_student_ids(parent_email)
        log_msg = f"Parent has access to students: {parent_student_ids}"
        frappe.logger().info(log_msg)
        logs.append(log_msg)
        
        log_msg = f"Report belongs to student: {report.student_id}"
        frappe.logger().info(log_msg)
        logs.append(log_msg)
        
        if report.student_id not in parent_student_ids:
            log_msg = f"❌ Access denied: Student {report.student_id} not in parent's student list {parent_student_ids}"
            frappe.logger().error(log_msg)
            logs.append(log_msg)
            return error_response(
                message="You do not have permission to view this report card",
                code="PERMISSION_DENIED",
                logs=logs
            )
        
        log_msg = f"✓ Parent has access to student {report.student_id}"
        frappe.logger().info(log_msg)
        logs.append(log_msg)
        
        # Check if report is approved
        if not report.is_approved:
            log_msg = f"❌ Report {report_id} is not approved yet"
            frappe.logger().error(log_msg)
            logs.append(log_msg)
            return error_response(
                message="Báo cáo học tập này chưa được phê duyệt",
                code="NOT_APPROVED",
                logs=logs
            )
        
        log_msg = f"✓ Report {report_id} is approved"
        frappe.logger().info(log_msg)
        logs.append(log_msg)
        
        # Use admin API with permission override
        from erp.api.erp_sis.report_card_render import get_report_data
        
        log_msg = "🔄 Switching to Administrator context for parent portal access"
        frappe.logger().info(log_msg)
        logs.append(log_msg)
        
        # Save current user and permission state
        current_user = frappe.session.user
        old_ignore_permissions = getattr(frappe.flags, 'ignore_permissions', False)
        
        try:
            # Switch to Administrator AND set ignore_permissions flag
            frappe.set_user("Administrator")
            frappe.flags.ignore_permissions = True
            
            log_msg = f"✓ Switched user from {current_user} to {frappe.session.user}"
            frappe.logger().info(log_msg)
            logs.append(log_msg)
            
            log_msg = "✓ ignore_permissions flag set to True"
            frappe.logger().info(log_msg)
            logs.append(log_msg)
            
            # Call admin API to get fully transformed data
            log_msg = f"Calling get_report_data for report {report_id}..."
            frappe.logger().info(log_msg)
            logs.append(log_msg)
            
            result = get_report_data(report_id=report_id)
            
            log_msg = f"✅ Got report data from admin API, success={result.get('success')}"
            frappe.logger().info(log_msg)
            logs.append(log_msg)
            
            # Add approval info and PDF file path to result
            if result.get('success') and result.get('data'):
                result['data']['is_approved'] = report.is_approved or 0
                result['data']['pdf_file'] = report.pdf_file or None
                result['data']['approved_by'] = report.approved_by or None
                result['data']['approved_at'] = report.approved_at or None
                
                log_msg = f"✓ Added approval info: is_approved={result['data']['is_approved']}, pdf_file={result['data']['pdf_file']}"
                frappe.logger().info(log_msg)
                logs.append(log_msg)
                
                # Add logs to result
                if not result.get('logs'):
                    result['logs'] = []
                result['logs'].extend(logs)
            else:
                # If get_report_data failed, add our logs to its response
                if not result.get('logs'):
                    result['logs'] = []
                result['logs'].extend(logs)
                
                log_msg = f"❌ get_report_data returned success=False, message={result.get('message')}"
                frappe.logger().error(log_msg)
                logs.append(log_msg)
            
            return result
            
        except Exception as e:
            log_msg = f"❌ Error in get_report_data: {str(e)}"
            frappe.logger().error(log_msg)
            frappe.logger().error(frappe.get_traceback())
            logs.append(log_msg)
            logs.append(frappe.get_traceback())
            raise
        finally:
            # Restore original user and permission state
            frappe.set_user(current_user)
            frappe.flags.ignore_permissions = old_ignore_permissions
            log_msg = f"🔄 Restored user to {current_user} and ignore_permissions to {old_ignore_permissions}"
            frappe.logger().info(log_msg)
            logs.append(log_msg)
        
    except frappe.PermissionError as pe:
        log_msg = f"❌ Permission denied: {str(pe)}"
        frappe.logger().error(log_msg)
        frappe.logger().error(frappe.get_traceback())
        logs.append(log_msg)
        logs.append(frappe.get_traceback())
        return error_response(
            message="You do not have permission to view this report card",
            code="PERMISSION_DENIED",
            logs=logs
        )
    except Exception as e:
        log_msg = f"❌ Error in get_report_card_detail: {str(e)} (type: {type(e).__name__})"
        frappe.logger().error(log_msg)
        frappe.logger().error(frappe.get_traceback())
        logs.append(log_msg)
        logs.append(frappe.get_traceback())
        return error_response(
            message=f"Error fetching report card detail: {str(e)}",
            code="SERVER_ERROR",
            logs=logs
        )


@frappe.whitelist(allow_guest=False)
def get_report_card_images():
    """
    Get list of PNG images for a report card (parent view)
    
    Query params:
        - report_id: Report card ID
    
    Returns:
        List of image URLs for each page
    """
    import os
    import glob
    
    try:
        # Get report_id from request - try all possible sources
        report_id = None
        
        # Try GET query parameters (frappe.request.args)
        if hasattr(frappe, 'request') and hasattr(frappe.request, 'args'):
            report_id = frappe.request.args.get("report_id")
        
        # Try form_dict (POST data or query params)
        if not report_id:
            report_id = frappe.form_dict.get("report_id")
        
        # Try local.form_dict
        if not report_id:
            report_id = (frappe.local.form_dict or {}).get("report_id")
        
        frappe.logger().info(f"🔍 [Parent Portal] get_report_card_images debug:")
        frappe.logger().info(f"   - request.args: {getattr(frappe.request, 'args', 'NOT_FOUND')}")
        frappe.logger().info(f"   - form_dict: {frappe.form_dict}")
        frappe.logger().info(f"   - local.form_dict: {frappe.local.form_dict}")
        frappe.logger().info(f"   - Extracted report_id: {repr(report_id)}")
        
        if not report_id or report_id == "":
            frappe.logger().error(f"❌ report_id not found in parent portal request")
            return error_response(
                message="Missing report_id",
                code="MISSING_PARAMS",
                logs=["report_id is required"]
            )
        
        frappe.logger().info(f"📸 [Parent Portal] get_report_card_images called for report: {report_id}, parent: {frappe.session.user}")
        
        # Get report
        try:
            report = frappe.get_doc("SIS Student Report Card", report_id, ignore_permissions=True)
        except frappe.DoesNotExistError:
            return error_response(
                message="Báo cáo học tập không được tìm thấy",
                code="NOT_FOUND",
                logs=[f"Report {report_id} not found"]
            )
        
        # Verify parent has access to this student
        parent_email = frappe.session.user
        parent_student_ids = _get_parent_student_ids(parent_email)
        
        if report.student_id not in parent_student_ids:
            frappe.logger().error(f"❌ Parent {parent_email} does not have access to student {report.student_id}")
            return error_response(
                message="Bạn không có quyền xem báo cáo học tập này",
                code="PERMISSION_DENIED",
                logs=[f"Student {report.student_id} not in parent's student list: {parent_student_ids}"]
            )
        
        # Check if report is approved
        if not report.is_approved:
            return error_response(
                message="Báo cáo học tập này chưa được phê duyệt",
                code="NOT_APPROVED",
                logs=[f"Report {report_id} is not approved yet"]
            )
        
        # Get student code
        try:
            student = frappe.get_doc("CRM Student", report.student_id, ignore_permissions=True)
            student_code = student.student_code or report.student_id
        except:
            student_code = report.student_id
        
        # Debug: Log all report fields to find the correct ones
        frappe.logger().info(f"   📋 Report fields debug:")
        frappe.logger().info(f"      - school_year: {getattr(report, 'school_year', 'NOT_FOUND')}")
        frappe.logger().info(f"      - academic_year: {getattr(report, 'academic_year', 'NOT_FOUND')}")
        frappe.logger().info(f"      - semester_part: {getattr(report, 'semester_part', 'NOT_FOUND')}")
        frappe.logger().info(f"      - semester: {getattr(report, 'semester', 'NOT_FOUND')}")
        
        # Extract school year and semester info
        # Try multiple field names for school year
        school_year = (
            getattr(report, 'school_year', None) or 
            getattr(report, 'academic_year', None) or 
            'unknown'
        )
        
        # Try multiple field names for semester
        semester_part = (
            getattr(report, 'semester_part', None) or 
            getattr(report, 'semester', None) or 
            'semester_1'
        )
        
        frappe.logger().info(f"   - student_code: {student_code}")
        frappe.logger().info(f"   - school_year: {school_year}")
        frappe.logger().info(f"   - semester_part: {semester_part}")
        
        # Build folder path: /files/reportcard/{student_code}/{schoolYear}/{semester_part}/
        folder_path = f"/files/reportcard/{student_code}/{school_year}/{semester_part}"
        physical_path = frappe.get_site_path('public', 'files', 'reportcard', student_code, school_year, semester_part)
        
        frappe.logger().info(f"   📁 Looking for images in: {physical_path}")
        
        # Check if folder exists
        if not os.path.exists(physical_path):
            frappe.logger().info(f"   ⚠️ Folder not found: {physical_path}")
            return success_response(
                data={
                    "report_id": report_id,
                    "student_code": student_code,
                    "school_year": school_year,
                    "semester_part": semester_part,
                    "images": [],
                    "total_pages": 0,
                    "has_images": False,
                    "folder_path": folder_path
                },
                message="No images found yet. Please wait for approval.",
                logs=[f"Folder not found: {physical_path}"]
            )
        
        # Find all PNG files in folder
        png_files = glob.glob(os.path.join(physical_path, "page_*.png"))
        png_files.sort()  # Sort by filename (page_1.png, page_2.png, ...)
        
        frappe.logger().info(f"   📸 Found {len(png_files)} PNG files")
        
        # Build image URLs
        image_urls = []
        for idx, file_path in enumerate(png_files, start=1):
            filename = os.path.basename(file_path)
            url = f"{folder_path}/{filename}"
            image_urls.append({
                "page": idx,
                "filename": filename,
                "url": url
            })
        
        frappe.logger().info(f"✅ [Parent Portal] Found {len(image_urls)} images for report {report_id}")
        
        return success_response(
            data={
                "report_id": report_id,
                "student_code": student_code,
                "school_year": school_year,
                "semester_part": semester_part,
                "images": image_urls,
                "total_pages": len(image_urls),
                "has_images": True,
                "folder_path": folder_path
            },
            message=f"Found {len(image_urls)} pages",
            logs=[f"Report {report_id}: {len(image_urls)} images found"]
        )
        
    except Exception as e:
        frappe.logger().error(f"❌ [Parent Portal] Error in get_report_card_images: {str(e)}")
        frappe.logger().error(frappe.get_traceback())
        return error_response(
            message=f"Lỗi khi lấy ảnh báo cáo: {str(e)}",
            code="SERVER_ERROR",
            logs=[str(e), frappe.get_traceback()]
        )

