# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import nowdate, get_datetime, now
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
        
        # Get unique actual_subject_id only for report card consistency
        student_subjects = frappe.get_all(
            "SIS Student Subject",
            fields=["actual_subject_id"],
            filters=filters,
            distinct=True
        )
        
        # Collect all unique actual subject IDs only
        actual_subject_ids = set()
        for record in student_subjects:
            if record.get("actual_subject_id"):
                actual_subject_ids.add(record["actual_subject_id"])
        
        if not actual_subject_ids:
            return list_response([], "No actual subjects found for the selected classes")
        
        # Get actual subject details from SIS Actual Subject table
        subjects_query = """
            SELECT DISTINCT
                s.name,
                s.title_vn,
                s.title_en,
                s.education_stage_id,
                s.curriculum_id,
                s.campus_id
            FROM `tabSIS Actual Subject` s
            WHERE s.campus_id = %s AND s.name IN ({})
            ORDER BY s.title_vn ASC
        """.format(','.join(['%s'] * len(actual_subject_ids)))
        
        subjects = frappe.db.sql(
            subjects_query, 
            (campus_id,) + tuple(actual_subject_ids), 
            as_dict=True
        )
        
        # Format the response for actual subjects only
        formatted_subjects = []
        for subject in subjects:
            formatted_subjects.append({
                "name": subject["name"],
                "title": subject["title_vn"] or subject["name"],
                "title_vn": subject["title_vn"] or subject["name"],
                "title_en": subject["title_en"] or subject["title_vn"] or subject["name"],
                "education_stage_id": subject["education_stage_id"],
                "curriculum_id": subject["curriculum_id"],
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


def _initialize_report_data_from_template(template, student_id: str, class_id: str) -> dict:
    """
    Initialize full data structure for Student Report Card based on template configuration
    This ensures Final View always shows all required fields (filled or empty)
    """
    data = {}
    
    try:
        # Get all actual subjects for this student from SIS Student Subject
        campus_id = template.campus_id
        student_subjects = frappe.get_all(
            "SIS Student Subject",
            fields=["actual_subject_id"],
            filters={
                "campus_id": campus_id,
                "class_id": class_id,
                "student_id": student_id
            },
            distinct=True
        )
        
        # Get actual subject details and filter by template subjects config if available
        actual_subject_ids = [s["actual_subject_id"] for s in student_subjects if s.get("actual_subject_id")]
        
        # If template has specific subjects config, only include those (assume template now uses actual_subject_id)
        template_actual_subject_ids = []
        if hasattr(template, 'subjects') and template.subjects:
            template_actual_subject_ids = [s.subject_id for s in template.subjects if s.subject_id]
            # Filter actual_subject_ids to only include those configured in template
            actual_subject_ids = [sid for sid in actual_subject_ids if sid in template_actual_subject_ids]
        
        # Get actual subject names/titles for reference
        subjects_info = {}
        if actual_subject_ids:
            subjects_data = frappe.get_all(
                "SIS Actual Subject",
                fields=["name", "title_vn as title"],
                filters={"name": ["in", actual_subject_ids]}
            )
            subjects_info = {s["name"]: s["title"] for s in subjects_data}
        
        # 1. Initialize Scores section (VN program)
        if getattr(template, 'scores_enabled', False):
            scores = {}
            
            # If template has scores config, use that structure with actual subjects
            if hasattr(template, 'scores') and template.scores:
                for score_config in template.scores:
                    actual_subject_id = score_config.subject_id
                    if actual_subject_id in actual_subject_ids:
                        scores[actual_subject_id] = {
                            "subject_title": subjects_info.get(actual_subject_id, actual_subject_id),
                            "display_name": score_config.display_name or subjects_info.get(actual_subject_id, actual_subject_id),
                            "subject_type": score_config.subject_type or "Môn tính điểm",
                            "hs1_scores": [],  # List of individual scores
                            "hs2_scores": [],
                            "hs3_scores": [],
                            "hs1_average": None,
                            "hs2_average": None,
                            "hs3_average": None,
                            "final_average": None,
                            "weight1_count": getattr(score_config, "weight1_count", 1) or 1,
                            "weight2_count": getattr(score_config, "weight2_count", 1) or 1,
                            "weight3_count": getattr(score_config, "weight3_count", 1) or 1
                        }
            
            data["scores"] = scores
        
        # 2. Initialize Homeroom section
        if getattr(template, 'homeroom_enabled', False):
            homeroom = {
                "conduct": "",
                "conduct_year": "" if getattr(template, 'homeroom_conduct_year_enabled', False) else None,
                "comments": {}
            }
            
            # Initialize homeroom comments structure based on template
            if hasattr(template, 'homeroom_titles') and template.homeroom_titles:
                for title_config in template.homeroom_titles:
                    if title_config.title:
                        homeroom["comments"][title_config.title] = ""
            
            data["homeroom"] = homeroom
        
        # 3. Initialize Subject Evaluation section (VN program)
        if getattr(template, 'subject_eval_enabled', False):
            subject_eval = {}
            
            # Initialize for each actual subject configured in template
            if hasattr(template, 'subjects') and template.subjects:
                for subject_config in template.subjects:
                    actual_subject_id = subject_config.subject_id
                    if actual_subject_id in actual_subject_ids:
                        subject_data = {
                            "subject_title": subjects_info.get(actual_subject_id, actual_subject_id),
                            "test_points": {},
                            "criteria_scores": {},
                            "scale_scores": {},
                            "comments": {}
                        }
                        
                        # Initialize test points if enabled
                        if subject_config.test_point_enabled and hasattr(subject_config, 'test_point_titles'):
                            for title_config in subject_config.test_point_titles:
                                if title_config.title:
                                    subject_data["test_points"][title_config.title] = ""
                        
                        # Initialize criteria scores (rubric evaluation)
                        if subject_config.rubric_enabled:
                            # Load actual criteria structure from template
                            if hasattr(subject_config, 'criteria_id') and subject_config.criteria_id:
                                try:
                                    criteria_doc = frappe.get_doc("SIS Evaluation Criteria", subject_config.criteria_id)
                                    if hasattr(criteria_doc, 'options') and criteria_doc.options:
                                        for opt in criteria_doc.options:
                                            criteria_name = opt.get("name", "") or opt.get("title", "")
                                            if criteria_name:
                                                subject_data["criteria_scores"][criteria_name] = ""
                                except:
                                    pass
                            
                            # Scale scores can be initialized as empty for now
                            subject_data["scale_scores"] = {}
                        
                        # Initialize comment titles structure
                        if subject_config.comment_title_enabled:
                            # Load actual comment structure from template
                            if hasattr(subject_config, 'comment_title_id') and subject_config.comment_title_id:
                                try:
                                    comment_doc = frappe.get_doc("SIS Comment Title", subject_config.comment_title_id)
                                    if hasattr(comment_doc, 'options') and comment_doc.options:
                                        for opt in comment_doc.options:
                                            comment_name = opt.get("name", "") or opt.get("title", "")
                                            if comment_name:
                                                subject_data["comments"][comment_name] = ""
                                except:
                                    pass
                        
                        subject_eval[actual_subject_id] = subject_data
            
            data["subject_eval"] = subject_eval
        
        # 4. Initialize INTL program sections
        if template.program_type == 'intl':
            # Initialize INTL scoreboard structure
            intl_scoreboard = {}
            
            if hasattr(template, 'subjects') and template.subjects:
                for subject_config in template.subjects:
                    actual_subject_id = subject_config.subject_id
                    if actual_subject_id in actual_subject_ids and hasattr(subject_config, 'scoreboard'):
                        scoreboard_data = {
                            "subject_title": subjects_info.get(actual_subject_id, actual_subject_id),
                            "main_scores": {}
                        }
                        
                        # Initialize main scores structure
                        if subject_config.scoreboard and hasattr(subject_config.scoreboard, 'main_scores'):
                            for main_score in subject_config.scoreboard.main_scores:
                                main_title = main_score.title
                                scoreboard_data["main_scores"][main_title] = {
                                    "weight": main_score.weight,
                                    "components": {},
                                    "final_score": None
                                }
                                
                                # Initialize components
                                if hasattr(main_score, 'components'):
                                    for component in main_score.components:
                                        scoreboard_data["main_scores"][main_title]["components"][component.title] = {
                                            "weight": component.weight,
                                            "score": None
                                        }
                        
                        intl_scoreboard[actual_subject_id] = scoreboard_data
            
            data["intl_scoreboard"] = intl_scoreboard
            
            # Initialize INTL overall marks and comments
            if getattr(template, 'intl_overall_mark_enabled', False):
                data["intl_overall_mark"] = None
            
            if getattr(template, 'intl_overall_grade_enabled', False):
                data["intl_overall_grade"] = ""
            
            if getattr(template, 'intl_comment_enabled', False):
                data["intl_comment"] = ""
        
        # 5. Add metadata
        data["_metadata"] = {
            "initialized_at": now(),
            "template_id": template.name,
            "student_id": student_id,
            "class_id": class_id,
            "total_subjects": len(actual_subject_ids),
            "program_type": template.program_type
        }
        
        return data
        
    except Exception as e:
        frappe.log_error(f"Error initializing report data: {str(e)}")
        # Fallback to minimal structure
        return {
            "_metadata": {
                "initialized_at": now(),
                "template_id": template.name,
                "student_id": student_id,
                "class_id": class_id,
                "error": str(e)
            }
        }


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
                    
                    # Initialize full data structure based on template
                    initial_data = _initialize_report_data_from_template(template, student_id, class_id)
                    
                    # Create new report card
                    report_doc = frappe.get_doc({
                        "doctype": "SIS Student Report Card",
                        "title": template.title,
                        "template_id": template.name,
                        "form_id": template.form_id or "",
                        "class_id": class_id,
                        "student_id": student_id,
                        "school_year": template.school_year,
                        "semester_part": template.semester_part,
                        "status": "draft",
                        "campus_id": campus_id,
                        "data_json": json.dumps(initial_data),
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
