"""
Parent Portal Subject API
Handles subject information retrieval for parent portal
"""

import frappe
from frappe import _
import json
from erp.utils.api_response import validation_error_response, list_response, error_response


@frappe.whitelist()
def get_subject_info(subject_id):
    """
    Get detailed subject information including assignments and curriculum

    Args:
        subject_id: Subject document name (SIS Subject)

    Returns:
        dict: Subject information with assignments and curriculum details
    """
    logs = []

    try:
        if not subject_id:
            return validation_error_response("Subject ID is required", {"subject_id": ["Required"]})

        # Get subject basic information
        subject = frappe.get_doc("SIS Subject", subject_id)

        if not subject:
            return error_response("Subject not found")

        logs.append(f"Found subject: {subject.title}")

        # Get subject assignments (teachers assigned to this subject)
        assignments = frappe.get_all(
            "SIS Subject Assignment",
            filters={"actual_subject_id": subject.actual_subject_id},
            fields=[
                "name",
                "teacher_id",
                "class_id",
                "actual_subject_id"
            ]
        )

        logs.append(f"Found {len(assignments)} subject assignments")

        # Get teacher details for assignments
        teacher_assignments = []
        for assignment in assignments:
            teacher_info = None
            if assignment.teacher_id:
                teacher_doc = frappe.get_doc("SIS Teacher", assignment.teacher_id)
                teacher_info = {
                    "teacher_id": teacher_doc.name,
                    "teacher_name": teacher_doc.teacher_name,
                    "teacher_email": teacher_doc.email,
                    "class_id": assignment.class_id
                }

            teacher_assignments.append({
                "assignment_id": assignment.name,
                "teacher": teacher_info,
                "class_id": assignment.class_id
            })

        # Get curriculum information
        curriculum_info = None
        if subject.subcurriculum_id:
            try:
                subcurriculum = frappe.get_doc("SIS Sub Curriculum", subject.subcurriculum_id)
                curriculum_info = {
                    "subcurriculum_id": subcurriculum.name,
                    "subcurriculum_title": subcurriculum.title,
                    "curriculum_id": subcurriculum.curriculum_id if hasattr(subcurriculum, 'curriculum_id') else None
                }

                # Get main curriculum if available
                if curriculum_info.get("curriculum_id"):
                    try:
                        curriculum = frappe.get_doc("SIS Curriculum", curriculum_info["curriculum_id"])
                        curriculum_info["curriculum_title"] = curriculum.title
                    except Exception as e:
                        logs.append(f"Could not get curriculum details: {str(e)}")

            except Exception as e:
                logs.append(f"Could not get subcurriculum details: {str(e)}")

        # Get room information if available
        room_info = None
        if subject.room_id:
            try:
                room = frappe.get_doc("ERP Administrative Room", subject.room_id)
                room_info = {
                    "room_id": room.name,
                    "room_title": room.title or room.room_number
                }
            except Exception as e:
                logs.append(f"Could not get room details: {str(e)}")

        # Prepare response data
        subject_data = {
            "subject_id": subject.name,
            "title": subject.title,
            "campus_id": subject.campus_id,
            "education_stage": subject.education_stage,
            "timetable_subject_id": subject.timetable_subject_id,
            "actual_subject_id": subject.actual_subject_id,
            "room": room_info,
            "curriculum": curriculum_info,
            "assignments": teacher_assignments
        }

        logs.append("Subject information retrieved successfully")

        return {
            "success": True,
            "message": "Subject information retrieved successfully",
            "data": subject_data,
            "logs": logs
        }

    except frappe.DoesNotExistError:
        return error_response("Subject not found")

    except Exception as e:
        logs.append(f"Error retrieving subject info: {str(e)}")
        return error_response(f"An error occurred: {str(e)}", logs=logs)


@frappe.whitelist()
def get_subjects_by_class(class_id):
    """
    Get all subjects for a specific class with assignment information

    Args:
        class_id: Class document name

    Returns:
        dict: List of subjects with teacher assignments
    """
    logs = []

    try:
        if not class_id:
            return validation_error_response("Class ID is required", {"class_id": ["Required"]})

        # Get subjects assigned to this class through timetable
        timetable_subjects = frappe.get_all(
            "SIS Timetable",
            filters={"class_id": class_id},
            fields=[
                "subject_id",
                "teacher_1_id",
                "teacher_2_id"
            ],
            group_by="subject_id"
        )

        subjects_data = []

        for ts in timetable_subjects:
            try:
                subject = frappe.get_doc("SIS Subject", ts.subject_id)
                logs.append(f"Processing subject: {subject.title}")

                # Get teacher information
                teachers = []
                if ts.teacher_1_id:
                    try:
                        teacher1 = frappe.get_doc("SIS Teacher", ts.teacher_1_id)
                        teachers.append({
                            "teacher_id": teacher1.name,
                            "teacher_name": teacher1.teacher_name,
                            "teacher_email": teacher1.email,
                            "role": "primary"
                        })
                    except:
                        pass

                if ts.teacher_2_id:
                    try:
                        teacher2 = frappe.get_doc("SIS Teacher", ts.teacher_2_id)
                        teachers.append({
                            "teacher_id": teacher2.name,
                            "teacher_name": teacher2.teacher_name,
                            "teacher_email": teacher2.email,
                            "role": "secondary"
                        })
                    except:
                        pass

                subjects_data.append({
                    "subject_id": subject.name,
                    "title": subject.title,
                    "timetable_subject_id": subject.timetable_subject_id,
                    "actual_subject_id": subject.actual_subject_id,
                    "teachers": teachers
                })

            except Exception as e:
                logs.append(f"Error processing subject {ts.subject_id}: {str(e)}")
                continue

        logs.append(f"Retrieved {len(subjects_data)} subjects for class {class_id}")

        return {
            "success": True,
            "message": f"Retrieved {len(subjects_data)} subjects",
            "data": {
                "class_id": class_id,
                "subjects": subjects_data
            },
            "logs": logs
        }

    except Exception as e:
        logs.append(f"Error retrieving subjects by class: {str(e)}")
        return error_response(f"An error occurred: {str(e)}", logs=logs)


@frappe.whitelist()
def get_subject_curriculum_and_teacher(subject_id, class_id):
    """
    Get curriculum information for a subject and find the teacher assigned to teach it for a specific class

    Args:
        subject_id: Subject document name (SIS Subject)
        class_id: Class document name

    Returns:
        dict: Curriculum info and teacher assignment for the subject-class combination
    """
    logs = []

    try:
        logs.append(f"🔍 Received parameters - subject_id: '{subject_id}' (type: {type(subject_id)}), class_id: '{class_id}' (type: {type(class_id)})")

        if not subject_id:
            logs.append(f"❌ Subject ID validation failed: subject_id is falsy")
            return error_response("Subject ID is required", errors={"subject_id": ["Required"]}, logs=logs)
        if not class_id:
            logs.append(f"❌ Class ID validation failed: class_id is falsy")
            return error_response("Class ID is required", errors={"class_id": ["Required"]}, logs=logs)

        # Get subject basic information
        subject = frappe.get_doc("SIS Subject", subject_id)

        if not subject:
            return error_response("Subject not found")

        logs.append(f"Found subject: {subject.title}")

        # Get curriculum information
        curriculum_info = None
        if subject.subcurriculum_id:
            try:
                subcurriculum = frappe.get_doc("SIS Sub Curriculum", subject.subcurriculum_id)
                curriculum_info = {
                    "subcurriculum_id": subcurriculum.name,
                    "subcurriculum_title": subcurriculum.title,
                    "curriculum_id": subcurriculum.curriculum_id if hasattr(subcurriculum, 'curriculum_id') else None
                }

                # Get main curriculum if available
                if curriculum_info.get("curriculum_id"):
                    try:
                        curriculum = frappe.get_doc("SIS Curriculum", curriculum_info["curriculum_id"])
                        curriculum_info["curriculum_title"] = curriculum.title
                    except Exception as e:
                        logs.append(f"Could not get curriculum details: {str(e)}")

            except Exception as e:
                logs.append(f"Could not get subcurriculum details: {str(e)}")

        # Find teacher assignment for this subject and class
        teacher_assignment = None
        teacher_info = None

        # Query SIS Subject Assignment to find teacher for this subject and class
        assignments = frappe.get_all(
            "SIS Subject Assignment",
            filters={
                "actual_subject_id": subject.actual_subject_id,
                "class_id": class_id
            },
            fields=[
                "name",
                "teacher_id",
                "class_id",
                "actual_subject_id"
            ]
        )

        logs.append(f"Found {len(assignments)} assignments for subject {subject.actual_subject_id} in class {class_id}")

        if assignments:
            assignment = assignments[0]  # Take the first assignment
            teacher_assignment = {
                "assignment_id": assignment.name,
                "class_id": assignment.class_id,
                "actual_subject_id": assignment.actual_subject_id
            }

            # Get teacher details
            if assignment.teacher_id:
                try:
                    teacher_doc = frappe.get_doc("SIS Teacher", assignment.teacher_id)
                    teacher_info = {
                        "teacher_id": teacher_doc.name,
                        "teacher_name": teacher_doc.teacher_name,
                        "teacher_email": teacher_doc.email,
                        "teacher_phone": getattr(teacher_doc, 'phone', None)
                    }
                    logs.append(f"Found teacher: {teacher_doc.teacher_name}")
                except Exception as e:
                    logs.append(f"Could not get teacher details: {str(e)}")
            else:
                logs.append("No teacher assigned for this subject and class")
        else:
            logs.append(f"No subject assignment found for subject {subject.actual_subject_id} in class {class_id}")

        # Prepare response data
        response_data = {
            "subject_id": subject.name,
            "subject_title": subject.title,
            "actual_subject_id": subject.actual_subject_id,
            "class_id": class_id,
            "curriculum": curriculum_info,
            "teacher_assignment": teacher_assignment,
            "teacher": teacher_info
        }

        logs.append("Subject curriculum and teacher information retrieved successfully")

        return {
            "success": True,
            "message": "Subject curriculum and teacher information retrieved successfully",
            "data": response_data,
            "logs": logs
        }

    except frappe.DoesNotExistError:
        return error_response("Subject not found")

    except Exception as e:
        logs.append(f"Error retrieving subject curriculum and teacher: {str(e)}")
        return error_response(f"An error occurred: {str(e)}", logs=logs)


@frappe.whitelist()
def get_student_subject_teachers():
    """
    Get all subject teachers for a specific student

    Args:
        student_id: Student document name (CRM Student) - passed via frappe.form_dict

    Returns:
        dict: List of subjects with their assigned teachers
    """
    logs = []

    try:
        # Get student_id from frappe form data or request args
        student_id = frappe.form_dict.get('student_id')

        # Also try to get from request args
        if not student_id:
            student_id = frappe.request.args.get('student_id') if hasattr(frappe.request, 'args') else None

        if not student_id:
            return validation_error_response("Student ID is required", {"student_id": ["Required"]})

        logs.append(f"🔍 Getting subject teachers for student: {student_id}")

        # Step 1: Get all classes for this student
        class_students = frappe.get_all(
            "SIS Class Student",
            filters={"student_id": student_id},
            fields=["class_id", "school_year_id"],
            ignore_permissions=True
        )

        if not class_students:
            logs.append("⚠️ No classes found for student")
            return list_response(
                data=[],
                message="No classes found for student",
                logs=logs
            )

        class_ids = [cs.class_id for cs in class_students if cs.class_id]
        logs.append(f"✅ Found {len(class_ids)} classes for student: {class_ids}")

        # Step 2: Get all subject assignments for these classes
        # Query trực tiếp từ SIS Subject Assignment thay vì đi qua SIS Student Subject
        # Cách này lấy được TẤT CẢ môn học được dạy trong lớp, không phụ thuộc vào việc
        # học sinh đã có records trong SIS Student Subject hay chưa
        subject_assignments = frappe.db.sql("""
            SELECT DISTINCT
                sa.actual_subject_id,
                sa.class_id,
                sa.teacher_id
            FROM `tabSIS Subject Assignment` sa
            WHERE sa.class_id IN %(class_ids)s
            ORDER BY sa.actual_subject_id, sa.class_id
        """, {"class_ids": class_ids}, as_dict=True)

        if not subject_assignments:
            logs.append("⚠️ No subject assignments found for these classes")
            return list_response(
                data=[],
                message="No subject assignments found",
                logs=logs
            )

        logs.append(f"✅ Found {len(subject_assignments)} subject assignments")

        # Step 3: Group by actual_subject_id and class_id, collect all teachers
        subject_groups = {}
        for sa in subject_assignments:
            if not sa.actual_subject_id:
                continue
            
            key = f"{sa.actual_subject_id}_{sa.class_id}"
            if key not in subject_groups:
                subject_groups[key] = {
                    "actual_subject_id": sa.actual_subject_id,
                    "class_id": sa.class_id,
                    "teacher_ids": []
                }
            
            # Collect all teachers for this subject-class combination
            if sa.teacher_id and sa.teacher_id not in subject_groups[key]["teacher_ids"]:
                subject_groups[key]["teacher_ids"].append(sa.teacher_id)

        logs.append(f"✅ Grouped into {len(subject_groups)} unique subject-class combinations")

        # Step 4: Build response with subject and teacher info
        subject_teachers = []
        
        for key, group in subject_groups.items():
            try:
                # Get actual subject details
                actual_subject = frappe.get_doc("SIS Actual Subject", group["actual_subject_id"])
                actual_subject_name = actual_subject.title_vn or actual_subject.title_en

                # Get first teacher info (or None if no teachers assigned)
                teacher_info = None
                if group["teacher_ids"]:
                    teacher_id = group["teacher_ids"][0]  # Lấy teacher đầu tiên
                    try:
                        teacher_doc = frappe.get_doc("SIS Teacher", teacher_id)

                        # Get user info for avatar and full name
                        user_info = None
                        if teacher_doc.user_id:
                            try:
                                user = frappe.get_doc("User", teacher_doc.user_id)
                                user_info = {
                                    "full_name": getattr(user, 'full_name', ''),
                                    "email": getattr(user, 'email', ''),
                                    "user_image": getattr(user, 'user_image', None),
                                    "mobile_no": getattr(user, 'mobile_no', ''),
                                    "phone": getattr(user, 'phone', '')
                                }
                            except Exception as e:
                                logs.append(f"⚠️ Could not get user info for teacher {teacher_id}: {str(e)}")

                        teacher_info = {
                            "teacher_id": teacher_doc.name,
                            "teacher_name": getattr(teacher_doc, 'teacher_name', ''),
                            "teacher_code": getattr(teacher_doc, 'teacher_code', ''),
                            "email": user_info.get('email') if user_info else getattr(teacher_doc, 'email', ''),
                            "phone": user_info.get('mobile_no') or user_info.get('phone') if user_info else getattr(teacher_doc, 'phone', ''),
                            "avatar": user_info.get('user_image') if user_info and user_info.get('user_image') else None,
                            "full_name": user_info.get('full_name') if user_info else getattr(teacher_doc, 'teacher_name', '')
                        }

                    except Exception as e:
                        logs.append(f"⚠️ Could not get teacher {teacher_id}: {str(e)}")

                subject_teachers.append({
                    "actual_subject_id": group["actual_subject_id"],
                    "subject_name": actual_subject_name,
                    "class_id": group["class_id"],
                    "teacher": teacher_info
                })

            except Exception as e:
                logs.append(f"⚠️ Error processing subject {group['actual_subject_id']}: {str(e)}")
                continue

        # Sort by subject name
        subject_teachers.sort(key=lambda x: x.get('subject_name', ''))

        logs.append(f"✅ Retrieved {len(subject_teachers)} subject teachers for student")

        return {
            "success": True,
            "message": f"Retrieved {len(subject_teachers)} subject teachers",
            "data": subject_teachers,
            "logs": logs
        }

    except Exception as e:
        logs.append(f"❌ Error getting subject teachers: {str(e)}")
        return error_response(f"An error occurred: {str(e)}", logs=logs)
