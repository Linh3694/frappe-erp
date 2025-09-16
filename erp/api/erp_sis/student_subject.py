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


@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def get_subjects_by_classes():
    """
    Get unique subjects from SIS Student Subject based on selected classes/grades
    Returns subjects with their details for report card configuration
    """
    try:
        # Get current user's campus information from roles
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
            frappe.logger().warning(f"No campus found for user {frappe.session.user}, using default: {campus_id}")
        
        # Get class_ids from request
        class_ids = None
        
        # Try from form_dict first
        if frappe.form_dict.get('class_ids'):
            class_ids = frappe.form_dict.get('class_ids')
            if isinstance(class_ids, str):
                try:
                    class_ids = json.loads(class_ids)
                except json.JSONDecodeError:
                    class_ids = [class_ids]  # Single class ID as string
        
        # Try from JSON payload
        if not class_ids and frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
                class_ids = json_data.get('class_ids', [])
            except (json.JSONDecodeError, TypeError, AttributeError, UnicodeDecodeError):
                pass
        
        if not class_ids or len(class_ids) == 0:
            return validation_error_response("Validation failed", {"class_ids": ["At least one class ID is required"]})
        
        # Make sure class_ids is a list
        if not isinstance(class_ids, list):
            class_ids = [class_ids]
        
        # Query SIS Student Subject to get unique subjects for the given classes
        filters = {
            "campus_id": campus_id,
            "class_id": ["in", class_ids]
        }
        
        # Get unique subject_id and actual_subject_id combinations
        student_subjects = frappe.get_all(
            "SIS Student Subject",
            fields=["subject_id", "actual_subject_id"],
            filters=filters,
            distinct=True
        )
        
        # Collect all unique subject IDs (both subject_id and actual_subject_id)
        subject_ids = set()
        for record in student_subjects:
            if record.get("subject_id"):
                subject_ids.add(record["subject_id"])
            if record.get("actual_subject_id"):
                subject_ids.add(record["actual_subject_id"])
        
        if not subject_ids:
            return list_response([], "No subjects found for the selected classes")
        
        # Get subject details from SIS Subject table
        subjects_query = """
            SELECT DISTINCT
                s.name,
                s.title as title_vn,
                '' as title_en,
                s.education_stage,
                s.timetable_subject_id,
                s.actual_subject_id,
                s.campus_id,
                COALESCE(ts.title_vn, '') as timetable_subject_name,
                COALESCE(act.title_vn, '') as actual_subject_name
            FROM `tabSIS Subject` s
            LEFT JOIN `tabSIS Timetable Subject` ts ON s.timetable_subject_id = ts.name AND ts.campus_id = s.campus_id
            LEFT JOIN `tabSIS Actual Subject` act ON s.actual_subject_id = act.name AND act.campus_id = s.campus_id
            WHERE s.campus_id = %s AND s.name IN ({})
            ORDER BY s.title ASC
        """.format(','.join(['%s'] * len(subject_ids)))
        
        subjects = frappe.db.sql(
            subjects_query, 
            (campus_id,) + tuple(subject_ids), 
            as_dict=True
        )
        
        # Format the response to include both title variations
        formatted_subjects = []
        for subject in subjects:
            formatted_subjects.append({
                "name": subject["name"],
                "title": subject["title_vn"] or subject["name"],
                "title_vn": subject["title_vn"] or subject["name"],
                "title_en": subject["title_en"] or subject["title_vn"] or subject["name"],
                "education_stage": subject["education_stage"],
                "timetable_subject_id": subject["timetable_subject_id"],
                "actual_subject_id": subject["actual_subject_id"],
                "timetable_subject_name": subject["timetable_subject_name"],
                "actual_subject_name": subject["actual_subject_name"],
                "campus_id": subject["campus_id"]
            })
        
        return list_response(
            formatted_subjects, 
            f"Found {len(formatted_subjects)} unique subjects for {len(class_ids)} classes"
        )
        
    except Exception as e:
        frappe.log_error(f"Error fetching subjects by classes: {str(e)}")
        return error_response(f"Error fetching subjects by classes: {str(e)}")


@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def get_students_by_classes():
    """
    Get unique students from SIS Student Subject based on selected classes/grades
    For debugging and verification purposes
    """
    try:
        campus_id = get_current_campus_from_context() or "campus-1"
        
        # Get class_ids from request (same logic as above)
        class_ids = None
        
        if frappe.form_dict.get('class_ids'):
            class_ids = frappe.form_dict.get('class_ids')
            if isinstance(class_ids, str):
                try:
                    class_ids = json.loads(class_ids)
                except json.JSONDecodeError:
                    class_ids = [class_ids]
        
        if not class_ids and frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
                class_ids = json_data.get('class_ids', [])
            except (json.JSONDecodeError, TypeError, AttributeError, UnicodeDecodeError):
                pass
        
        if not class_ids or len(class_ids) == 0:
            return validation_error_response("Validation failed", {"class_ids": ["At least one class ID is required"]})
        
        if not isinstance(class_ids, list):
            class_ids = [class_ids]
        
        # Query to get unique students
        filters = {
            "campus_id": campus_id,
            "class_id": ["in", class_ids]
        }
        
        students = frappe.get_all(
            "SIS Student Subject",
            fields=["student_id"],
            filters=filters,
            distinct=True
        )
        
        return list_response(
            [s["student_id"] for s in students], 
            f"Found {len(students)} unique students for {len(class_ids)} classes"
        )
        
    except Exception as e:
        frappe.log_error(f"Error fetching students by classes: {str(e)}")
        return error_response(f"Error fetching students by classes: {str(e)}")


@frappe.whitelist(allow_guest=False, methods=["POST"])
def create_student_reports_for_template():
    """
    Create Student Report Cards for all students in selected grades/classes
    Based on a report card template
    """
    try:
        campus_id = get_current_campus_from_context() or "campus-1"
        
        # Get parameters from request
        data = {}
        if frappe.request.data:
            try:
                data = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
            except (json.JSONDecodeError, TypeError, AttributeError, UnicodeDecodeError):
                pass
        
        # Extract required parameters
        template_id = data.get('template_id')
        class_ids = data.get('class_ids', [])
        
        if not template_id:
            return validation_error_response("Validation failed", {"template_id": ["Template ID is required"]})
        
        if not class_ids or len(class_ids) == 0:
            return validation_error_response("Validation failed", {"class_ids": ["At least one class ID is required"]})
        
        if not isinstance(class_ids, list):
            class_ids = [class_ids]
        
        # Get template details
        try:
            template = frappe.get_doc("SIS Report Card Template", template_id)
            if template.campus_id != campus_id:
                return forbidden_response("Template access denied")
        except frappe.DoesNotExistError:
            return not_found_response("Report card template not found")
        
        # Get unique students from SIS Student Subject
        filters = {
            "campus_id": campus_id,
            "class_id": ["in", class_ids]
        }
        
        student_subjects = frappe.get_all(
            "SIS Student Subject",
            fields=["student_id", "class_id"],
            filters=filters,
            distinct=True
        )
        
        if not student_subjects:
            return list_response([], "No students found for the selected classes")
        
        # Group students by class for processing
        students_by_class = {}
        for record in student_subjects:
            class_id = record["class_id"]
            student_id = record["student_id"]
            
            if class_id not in students_by_class:
                students_by_class[class_id] = []
            
            if student_id not in [s["student_id"] for s in students_by_class[class_id]]:
                students_by_class[class_id].append({
                    "student_id": student_id,
                    "class_id": class_id
                })
        
        created_reports = []
        failed_students = []
        skipped_students = []
        
        # Create reports for each student
        for class_id, students in students_by_class.items():
            for student_record in students:
                student_id = student_record["student_id"]
                
                try:
                    # Check if report already exists for this combination
                    # Validation: same student + school_year + semester_part + program_type should not have multiple reports
                    existing_filters = {
                        "student_id": student_id,
                        "school_year": template.school_year,
                        "semester_part": template.semester_part,
                        "campus_id": campus_id,
                    }
                    
                    # Check by program_type through template
                    existing_reports = frappe.get_all(
                        "SIS Student Report Card",
                        fields=["name", "template_id"],
                        filters=existing_filters
                    )
                    
                    # Check if any existing report has the same program_type
                    program_conflict = False
                    for existing in existing_reports:
                        try:
                            existing_template = frappe.get_doc("SIS Report Card Template", existing["template_id"])
                            if existing_template.program_type == template.program_type:
                                program_conflict = True
                                break
                        except:
                            continue
                    
                    if program_conflict:
                        skipped_students.append({
                            "student_id": student_id,
                            "class_id": class_id,
                            "reason": f"Report already exists for {template.program_type} program in {template.semester_part}"
                        })
                        frappe.logger().info(f"Report already exists for student {student_id} in {template.program_type} program, skipping")
                        continue
                    
                    # Get student name for title
                    try:
                        student_doc = frappe.get_doc("CRM Student", student_id)
                        student_name = getattr(student_doc, "student_name", None) or getattr(student_doc, "full_name", None) or student_id
                    except:
                        student_name = student_id
                    
                    # Create new report card
                    report_doc = frappe.get_doc({
                        "doctype": "SIS Student Report Card",
                        "title": f"{template.title} - {student_name}",
                        "template_id": template.name,
                        "form_id": template.form_id or "",
                        "class_id": class_id,
                        "student_id": student_id,
                        "school_year": template.school_year,
                        "semester_part": template.semester_part,
                        "status": "draft",
                        "campus_id": campus_id,
                        "data_json": json.dumps({}),
                    })
                    
                    report_doc.insert(ignore_permissions=True)
                    created_reports.append({
                        "report_id": report_doc.name,
                        "student_id": student_id,
                        "class_id": class_id
                    })
                    
                except Exception as e:
                    failed_students.append({
                        "student_id": student_id,
                        "class_id": class_id,
                        "error": str(e)
                    })
                    frappe.log_error(f"Failed to create report for student {student_id}: {str(e)}")
        
        frappe.db.commit()
        
        return success_response(
            data={
                "created": created_reports,
                "failed": failed_students,
                "skipped": skipped_students,
                "summary": {
                    "total_students": sum(len(students) for students in students_by_class.values()),
                    "created_count": len(created_reports),
                    "failed_count": len(failed_students),
                    "skipped_count": len(skipped_students)
                }
            },
            message=f"Created {len(created_reports)} student report cards. {len(skipped_students)} skipped (duplicates), {len(failed_students)} failed."
        )
        
    except Exception as e:
        frappe.log_error(f"Error creating student reports: {str(e)}")
        return error_response(f"Error creating student reports: {str(e)}")
