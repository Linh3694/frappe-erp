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


@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def get_subjects_by_students_in_classes():
    """
    Get ALL subjects for students in selected classes/grades
    
    This API differs from get_subjects_by_classes in that it:
    1. Filters classes by grade (if grade_ids provided) - JOIN with SIS Class
    2. Identifies students in the filtered classes
    3. Returns ALL subjects these students are enrolled in (including subjects from other classes like Mixed classes)
    4. Filters subjects by program_type (VN/INTL) based on curriculum_id
    
    This is useful for Mixed classes where students from multiple grades study together,
    ensuring report cards only include the correct students while showing all their subjects.
    
    Parameters:
    - class_ids: List of class IDs to filter students
    - grade_ids: Optional list of grade IDs to further filter students (to avoid mixed-grade students)
    - program_type: Optional 'vn' or 'intl' to filter subjects by curriculum
    
    Returns:
    - List of unique subjects that the filtered students are studying
    """
    try:
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
            frappe.logger().warning(f"No campus found for user {frappe.session.user}, using default: {campus_id}")
        
        # Curriculum mapping based on program type
        CURRICULUM_MAPPING = {
            'vn': ['SIS_CURRICULUM-00219', 'SIS_CURRICULUM-01333'],  # Chương trình Việt Nam + Phát triển toàn diện
            'intl': ['SIS_CURRICULUM-00011']  # Chương trình Quốc tế
        }
        
        # Get class_ids, grade_ids, and program_type from request
        class_ids = None
        grade_ids = None
        program_type = None
        
        # Try from form_dict first
        if frappe.form_dict.get('class_ids'):
            class_ids = frappe.form_dict.get('class_ids')
            if isinstance(class_ids, str):
                try:
                    class_ids = json.loads(class_ids)
                except json.JSONDecodeError:
                    class_ids = [class_ids]
        
        if frappe.form_dict.get('grade_ids'):
            grade_ids = frappe.form_dict.get('grade_ids')
            if isinstance(grade_ids, str):
                try:
                    grade_ids = json.loads(grade_ids)
                except json.JSONDecodeError:
                    grade_ids = [grade_ids]
        
        if frappe.form_dict.get('program_type'):
            program_type = frappe.form_dict.get('program_type')
        
        # Try from JSON payload
        if frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
                if not class_ids:
                    class_ids = json_data.get('class_ids', [])
                if not grade_ids:
                    grade_ids = json_data.get('grade_ids', [])
                if not program_type:
                    program_type = json_data.get('program_type')
            except (json.JSONDecodeError, TypeError, AttributeError, UnicodeDecodeError):
                pass
        
        if not class_ids or len(class_ids) == 0:
            return validation_error_response("Validation failed", {"class_ids": ["At least one class ID is required"]})
        
        # Make sure class_ids is a list
        if not isinstance(class_ids, list):
            class_ids = [class_ids]
        
        # Make sure grade_ids is a list if provided
        if grade_ids and not isinstance(grade_ids, list):
            grade_ids = [grade_ids]
        
        # STEP 1: If grade filter is provided, first filter classes by grade
        # Because SIS Student Subject doesn't have education_grade, we need to JOIN with SIS Class
        filtered_class_ids = class_ids
        
        if grade_ids and len(grade_ids) > 0:
            # Get classes that match both class_ids AND grade_ids
            class_grade_filters = {
                "campus_id": campus_id,
                "name": ["in", class_ids],
                "education_grade": ["in", grade_ids]
            }
            
            frappe.logger().info(f"[get_subjects_by_students_in_classes] Filtering classes by grades: {grade_ids}")
            
            filtered_classes = frappe.get_all(
                "SIS Class",
                fields=["name"],
                filters=class_grade_filters
            )
            
            filtered_class_ids = [c["name"] for c in filtered_classes]
            
            if not filtered_class_ids:
                frappe.logger().info(f"[get_subjects_by_students_in_classes] No classes found matching grades {grade_ids}")
                return list_response([], f"No classes found matching the selected grades")
            
            frappe.logger().info(f"[get_subjects_by_students_in_classes] Filtered to {len(filtered_class_ids)} classes matching grades")
        
        # STEP 2: Get students in the filtered classes
        student_filters = {
            "campus_id": campus_id,
            "class_id": ["in", filtered_class_ids]
        }
        
        frappe.logger().info(f"[get_subjects_by_students_in_classes] Finding students with filters: {student_filters}")
        
        students_in_classes = frappe.get_all(
            "SIS Student Subject",
            fields=["student_id"],
            filters=student_filters,
            distinct=True
        )
        
        if not students_in_classes:
            frappe.logger().info(f"[get_subjects_by_students_in_classes] No students found for classes {class_ids} and grades {grade_ids}")
            return list_response([], "No students found for the selected classes and grades")
        
        student_ids = [s["student_id"] for s in students_in_classes]
        frappe.logger().info(f"[get_subjects_by_students_in_classes] Found {len(student_ids)} students: {student_ids[:5]}...")
        
        # STEP 3: Get ALL subjects for these students (from all their classes)
        subject_filters = {
            "campus_id": campus_id,
            "student_id": ["in", student_ids]
        }
        
        frappe.logger().info(f"[get_subjects_by_students_in_classes] Step 3: Finding all subjects for {len(student_ids)} students")
        
        # Get unique actual_subject_id for these students
        student_subjects = frappe.get_all(
            "SIS Student Subject",
            fields=["actual_subject_id"],
            filters=subject_filters,
            distinct=True
        )
        
        # Collect all unique actual subject IDs
        actual_subject_ids = set()
        for record in student_subjects:
            if record.get("actual_subject_id"):
                actual_subject_ids.add(record["actual_subject_id"])
        
        if not actual_subject_ids:
            frappe.logger().info(f"[get_subjects_by_students_in_classes] No subjects found for students")
            return list_response([], "No subjects found for students in the selected classes")
        
        frappe.logger().info(f"[get_subjects_by_students_in_classes] Found {len(actual_subject_ids)} unique subjects")
        
        # STEP 4: Get actual subject details from SIS Actual Subject table
        # Add curriculum filter if program_type is provided
        curriculum_filter = ""
        query_params = [campus_id]
        
        if program_type and program_type in CURRICULUM_MAPPING:
            curriculum_ids = CURRICULUM_MAPPING[program_type]
            curriculum_placeholders = ','.join(['%s'] * len(curriculum_ids))
            curriculum_filter = f" AND s.curriculum_id IN ({curriculum_placeholders})"
            query_params.extend(curriculum_ids)
            frappe.logger().info(f"[get_subjects_by_students_in_classes] Filtering by program_type '{program_type}' -> curriculums: {curriculum_ids}")
        
        # Add actual_subject_ids to query params
        query_params.extend(actual_subject_ids)
        
        subjects_query = """
            SELECT DISTINCT
                s.name,
                s.title_vn,
                s.title_en,
                s.education_stage_id,
                s.curriculum_id,
                s.campus_id
            FROM `tabSIS Actual Subject` s
            WHERE s.campus_id = %s{curriculum_filter} AND s.name IN ({subject_placeholders})
            ORDER BY s.title_vn ASC
        """.format(
            curriculum_filter=curriculum_filter,
            subject_placeholders=','.join(['%s'] * len(actual_subject_ids))
        )
        
        subjects = frappe.db.sql(
            subjects_query, 
            tuple(query_params), 
            as_dict=True
        )
        
        # Format the response
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
        
        program_type_msg = f" (program_type: {program_type})" if program_type else ""
        frappe.logger().info(f"[get_subjects_by_students_in_classes] Returning {len(formatted_subjects)} subjects for {len(student_ids)} students from {len(class_ids)} classes{program_type_msg}")
        
        return list_response(
            formatted_subjects, 
            f"Found {len(formatted_subjects)} unique subjects for {len(student_ids)} students in {len(class_ids)} classes{program_type_msg}"
        )
        
    except Exception as e:
        frappe.log_error(f"Error fetching subjects by students in classes: {str(e)}")
        return error_response(f"Error fetching subjects by students in classes: {str(e)}")


def _initialize_report_data_from_template(template, student_id: str, class_id: str) -> dict:
    """
    Initialize full data structure for Student Report Card based on template configuration
    This ensures Final View always shows all required fields (filled or empty)
    """
    data = {}
    
    try:
        # Get all actual subjects for this student from SIS Student Subject
        # IMPORTANT: Get subjects from ALL classes this student is enrolled in, including mixed classes
        # This ensures mixed class subjects are included in the report card
        campus_id = template.campus_id
        student_subjects = frappe.get_all(
            "SIS Student Subject",
            fields=["actual_subject_id"],
            filters={
                "campus_id": campus_id,
                "student_id": student_id  # Get ALL subjects for this student across all classes
            },
            distinct=True
        )
        
        # Get actual subject details - these are subjects the student ACTUALLY studies
        actual_subject_ids = [s["actual_subject_id"] for s in student_subjects if s.get("actual_subject_id")]

        # DEBUG: Log actual subjects for this student
        print(f"DEBUG_REPORT_INIT: Student {student_id} in class {class_id} studies {len(actual_subject_ids)} subjects: {actual_subject_ids[:3]}...")  # Limit log size

        # If template has specific subjects config, only include subjects that are BOTH:
        # 1. Configured in template AND
        # 2. Actually studied by this student
        template_actual_subject_ids = []
        if hasattr(template, 'subjects') and template.subjects:
            template_actual_subject_ids = [s.subject_id for s in template.subjects if s.subject_id]
            print(f"DEBUG_REPORT_INIT: Template has {len(template_actual_subject_ids)} configured subjects")

            # CRITICAL: Only include subjects that student actually studies AND are in template
            original_count = len(actual_subject_ids)
            actual_subject_ids = [sid for sid in actual_subject_ids if sid in template_actual_subject_ids]
            filtered_count = len(actual_subject_ids)

            print(f"DEBUG_REPORT_INIT: After template filter: {original_count} -> {filtered_count} subjects for student {student_id}")
            if original_count != filtered_count:
                print(f"DEBUG_REPORT_INIT: WARNING - Student {student_id} missing {original_count - filtered_count} template subjects")

        print(f"DEBUG_REPORT_INIT: Final actual_subject_ids for {student_id}: {actual_subject_ids[:3]}...")
        
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

            # DEBUG: Log template scores subjects
            if hasattr(template, 'scores') and template.scores:
                template_score_subject_ids = [s.subject_id for s in template.scores if s.subject_id]
                print(f"DEBUG_REPORT_INIT: Template has {len(template_score_subject_ids)} score subjects")

            # If template has scores config, use that structure with actual subjects
            if hasattr(template, 'scores') and template.scores:
                included_count = 0
                excluded_count = 0
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
                        included_count += 1
                    else:
                        excluded_count += 1
                        print(f"DEBUG_REPORT_INIT: EXCLUDED score subject {actual_subject_id} - student doesn't study it")

                print(f"DEBUG_REPORT_INIT: Scores section: included {included_count}, excluded {excluded_count} subjects")
            
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
                    if actual_subject_id in actual_subject_ids:
                        subcurriculum_id = getattr(subject_config, 'subcurriculum_id', None) or 'none'
                        subcurriculum_title_en = 'General Program'
                        
                        # Fetch subcurriculum title if ID exists
                        if subcurriculum_id and subcurriculum_id != 'none':
                            try:
                                subcurriculum_doc = frappe.get_doc("SIS Sub Curriculum", subcurriculum_id)
                                subcurriculum_title_en = subcurriculum_doc.title_en or subcurriculum_doc.title_vn or subcurriculum_id
                                frappe.logger().info(f"Found subcurriculum: {subcurriculum_id} -> {subcurriculum_title_en}")
                            except Exception as e:
                                frappe.logger().error(f"Failed to fetch subcurriculum {subcurriculum_id}: {str(e)}")
                                subcurriculum_title_en = subcurriculum_id  # Fallback to ID if doc not found
                        
                        scoreboard_data = {
                            "subject_title": subjects_info.get(actual_subject_id, actual_subject_id),
                            "subcurriculum_id": subcurriculum_id,
                            "subcurriculum_title_en": subcurriculum_title_en,  # ← Added this field
                            "intl_comment": getattr(subject_config, 'intl_comment', None) or '',
                            "main_scores": {}
                        }
                        
                        # Initialize main scores structure from JSON scoreboard
                        if hasattr(subject_config, 'scoreboard') and subject_config.scoreboard:
                            try:
                                # Parse JSON scoreboard if it's a string
                                if isinstance(subject_config.scoreboard, str):
                                    import json
                                    scoreboard_obj = json.loads(subject_config.scoreboard)
                                else:
                                    scoreboard_obj = subject_config.scoreboard
                                
                                # Process main_scores if exists
                                if scoreboard_obj and "main_scores" in scoreboard_obj:
                                    for main_score in scoreboard_obj["main_scores"]:
                                        main_title = main_score.get("title", "")
                                        if main_title:
                                            scoreboard_data["main_scores"][main_title] = {
                                                "weight": main_score.get("weight", 0),
                                                "components": {},
                                                "final_score": None
                                            }
                                            
                                            # Initialize components
                                            if "components" in main_score:
                                                for component in main_score["components"]:
                                                    comp_title = component.get("title", "")
                                                    if comp_title:
                                                        scoreboard_data["main_scores"][main_title]["components"][comp_title] = {
                                                            "weight": component.get("weight", 0),
                                                            "score": None
                                                        }
                            except (json.JSONDecodeError, AttributeError, KeyError) as e:
                                frappe.logger().error(f"Error parsing scoreboard for subject {actual_subject_id}: {str(e)}")
                                # Initialize empty structure on error
                                pass
                        
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
