"""
Report Card API for Parent Portal
Parents can view their children's report cards
"""

import json
import frappe
from frappe import _
from erp.utils.api_response import success_response, error_response


def _get_parent_student_ids(parent_email):
    """Get all student IDs for a parent"""
    # Parent email format: guardian_id@parent.wellspring.edu.vn
    guardian_id = parent_email.split('@')[0]
    
    # Find guardian
    guardians = frappe.get_all(
        "CRM Guardian",
        filters={"guardian_id": guardian_id},
        fields=["name"],
        limit=1
    )
    
    if not guardians:
        return []
    
    guardian_name = guardians[0]['name']
    
    # Find students through family relationships
    relationships = frappe.get_all(
        "CRM Family Relationship",
        filters={"guardian": guardian_name},
        fields=["student"],
        pluck="student"
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
        
        # Build filters
        filters = {"student_id": student_id}
        
        if school_year:
            filters["school_year"] = school_year
        
        if semester_part:
            filters["semester_part"] = semester_part
        
        # Query report cards
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
            order_by="school_year desc, semester_part desc, modified desc"
        )
        
        # Get additional info for each report card
        enriched_reports = []
        for report in report_cards:
            # Get class info
            class_info = frappe.db.get_value(
                "SIS Class",
                report["class_id"],
                ["short_title", "title"],
                as_dict=True
            ) or {}
            
            enriched_reports.append({
                "name": report["name"],
                "title": report["title"],
                "template_id": report["template_id"],
                "form_id": report["form_id"],
                "class_id": report["class_id"],
                "class_short_title": class_info.get("short_title", ""),
                "class_code": class_info.get("title", ""),
                "student_id": report["student_id"],
                "school_year": report["school_year"],
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
        
        frappe.logger().info(f"📖 get_report_card_detail called:")
        frappe.logger().info(f"   - report_id: {report_id}")
        frappe.logger().info(f"   - parent_email: {frappe.session.user}")
        
        if not report_id:
            return error_response(
                message="Missing report_id",
                code="MISSING_PARAMS",
                logs=["report_id is required"]
            )
        
        # Get report card basic info to verify access
        report = frappe.get_doc("SIS Student Report Card", report_id)
        
        if not report:
            return error_response(
                message="Report card not found",
                code="NOT_FOUND",
                logs=[f"Report {report_id} not found"]
            )
        
        # Verify parent has access to this student
        parent_email = frappe.session.user
        parent_student_ids = _get_parent_student_ids(parent_email)
        
        if report.student_id not in parent_student_ids:
            return error_response(
                message="You do not have permission to view this report card",
                code="PERMISSION_DENIED",
                logs=[f"Student {report.student_id} not in parent's student list"]
            )
        
        # Use the existing report_card_render API to get structured data
        from erp.api.erp_sis.report_card_render import get_report_data
        
        # Call the existing API (it expects report_id in form_dict)
        original_form_dict = frappe.form_dict.copy()
        frappe.form_dict['report_id'] = report_id
        
        try:
            result = get_report_data(report_id=report_id)
            frappe.logger().info(f"✅ Got report data from render API")
            return result
        finally:
            # Restore original form_dict
            frappe.form_dict = original_form_dict
        
    except frappe.PermissionError:
        frappe.logger().error(f"❌ Permission denied for report {report_id}")
        return error_response(
            message="You do not have permission to view this report card",
            code="PERMISSION_DENIED",
            logs=["Permission denied"]
        )
    except Exception as e:
        frappe.logger().error(f"❌ Error in get_report_card_detail: {str(e)}")
        frappe.logger().error(frappe.get_traceback())
        return error_response(
            message=f"Error fetching report card detail: {str(e)}",
            code="SERVER_ERROR",
            logs=[str(e), frappe.get_traceback()]
        )

