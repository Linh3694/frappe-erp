"""
Contact Log API for Parent Portal
Parents can view contact logs sent by teachers
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


def _get_teacher_full_name(user_email):
    """Get teacher's full name from User doctype"""
    if not user_email:
        print(f"❌ No user_email provided")
        return None

    try:
        print(f"🔍 Getting full_name for user: {user_email}")
        full_name = frappe.db.get_value("User", user_email, "full_name")
        print(f"✅ Got full_name: {full_name}")
        return full_name
    except Exception as e:
        print(f"❌ Error getting full_name for {user_email}: {str(e)}")
        return None


def _get_teacher_info(user_email):
    """Get teacher's detailed info including gender and avatar from SIS Teacher and User doctypes"""
    if not user_email:
        print(f"❌ No user_email provided")
        return None

    try:
        print(f"🔍 Getting teacher info for user: {user_email}")

        # Get SIS Teacher record
        teacher_records = frappe.get_all(
            "SIS Teacher",
            filters={"user_id": user_email},
            fields=["name", "gender"],
            limit=1
        )

        teacher_info = None
        if teacher_records:
            teacher_doc = teacher_records[0]
            teacher_info = {
                "teacher_id": teacher_doc.name,
                "user_id": user_email,
                "gender": teacher_doc.gender
            }

            # Get user information including avatar
            try:
                user_info = frappe.get_all(
                    "User",
                    fields=[
                        "name",
                        "full_name",
                        "first_name",
                        "last_name",
                        "user_image",
                        "employee_code",
                        "employee_id"
                    ],
                    filters={"name": user_email},
                    limit=1
                )

                if user_info:
                    user = user_info[0]
                    teacher_info.update({
                        "full_name": user.get("full_name"),
                        "first_name": user.get("first_name"),
                        "last_name": user.get("last_name"),
                        "avatar_url": user.get("user_image"),  # user_image is the avatar field
                        "employee_code": user.get("employee_code"),
                        "employee_id": user.get("employee_id")
                    })
                    print(f"✅ Got teacher info: {user.get('full_name')}, gender: {teacher_doc.gender}, avatar: {user.get('user_image')}")
                else:
                    print(f"⚠️ No user info found for {user_email}")
            except Exception as user_error:
                print(f"❌ Error getting user info for {user_email}: {str(user_error)}")
        else:
            print(f"⚠️ No SIS Teacher record found for {user_email}")

        return teacher_info
    except Exception as e:
        print(f"❌ Error getting teacher info for {user_email}: {str(e)}")
        return None


def _get_class_info(class_id):
    """Get class information including homeroom teachers with detailed info"""
    try:
        print(f"🔍 Getting class info for {class_id}")
        class_doc = frappe.get_doc("SIS Class", class_id)
        print(f"📚 Class doc loaded: {class_doc.name}, title: {class_doc.title}")

        homeroom_teacher = None
        vice_homeroom_teacher = None

        if class_doc.homeroom_teacher:
            print(f"👨‍🏫 Processing homeroom teacher: {class_doc.homeroom_teacher}")
            # Get teacher's user email first
            teacher_user = frappe.db.get_value("SIS Teacher", class_doc.homeroom_teacher, "user_id")
            print(f"📧 Homeroom teacher user_id: {teacher_user}")
            if teacher_user:
                homeroom_teacher = _get_teacher_info(teacher_user)
                print(f"🏷️ Homeroom teacher info: {homeroom_teacher}")

        if class_doc.vice_homeroom_teacher:
            print(f"👨‍🏫 Processing vice homeroom teacher: {class_doc.vice_homeroom_teacher}")
            # Get teacher's user email first
            teacher_user = frappe.db.get_value("SIS Teacher", class_doc.vice_homeroom_teacher, "user_id")
            print(f"📧 Vice homeroom teacher user_id: {teacher_user}")
            if teacher_user:
                vice_homeroom_teacher = _get_teacher_info(teacher_user)
                print(f"🏷️ Vice homeroom teacher info: {vice_homeroom_teacher}")

        result = {
            "name": class_doc.name,
            "class_name": class_doc.title,
            "homeroom_teacher": homeroom_teacher,
            "vice_homeroom_teacher": vice_homeroom_teacher
        }
        print(f"✅ Class info result: {result}")
        return result
    except Exception as e:
        print(f"⚠️ Error getting class info for {class_id}: {str(e)}")
        return {
            "name": class_id,
            "class_name": class_id,
            "homeroom_teacher": None,
            "vice_homeroom_teacher": None
        }


@frappe.whitelist(allow_guest=False, methods=["POST"])
def get_student_contact_logs():
    """
    Get contact logs for a student (parent view)
    Only shows logs with status "Sent" (not Draft or Recalled)
    """
    try:
        # Get request body - try multiple methods
        body = {}
        try:
            request_data = frappe.request.get_data(as_text=True)
            if request_data:
                body = json.loads(request_data)
        except Exception:
            # Fallback to form_dict
            body = frappe.form_dict
        
        student_id = body.get('student_id')
        limit = int(body.get('limit', 50))
        offset = int(body.get('offset', 0))
        
        print(f"📞 get_student_contact_logs called:")
        print(f"   - student_id: {student_id}")
        print(f"   - parent_email: {frappe.session.user}")
        
        if not student_id:
            return error_response(message="Missing student_id", code="MISSING_PARAMS")
        
        # Verify parent has access to this student
        parent_email = frappe.session.user
        parent_student_ids = _get_parent_student_ids(parent_email)
        
        if student_id not in parent_student_ids:
            return error_response(
                message="You do not have permission to view this student's contact logs",
                code="PERMISSION_DENIED"
            )
        
        # Get student info
        student_name = frappe.db.get_value("CRM Student", student_id, "student_name")
        
        # Query contact logs with status "Sent" only
        logs = frappe.get_all(
            "SIS Class Log Student",
            filters={
                "student_id": student_id,
                "contact_log_status": "Sent"  # Only show sent logs
            },
            fields=[
                "name",
                "student_id",
                "class_student_id",
                "subject_id",
                "badges",
                "contact_log_comment",
                "contact_log_status",
                "contact_log_sent_by",
                "contact_log_sent_at",
                "contact_log_viewed_count"
            ],
            order_by="contact_log_sent_at DESC",
            limit_start=offset,
            limit_page_length=limit
        )
        
        # Enrich logs with class and teacher information
        enriched_logs = []
        for log in logs:
            # Get class info from class_student_id
            class_student = frappe.get_doc("SIS Class Student", log['class_student_id'])
            class_info = _get_class_info(class_student.class_id)
            
            # Get log date from subject
            log_date = None
            if log['subject_id']:
                log_date = frappe.db.get_value("SIS Class Log Subject", log['subject_id'], "log_date")
            
            enriched_log = {
                **log,
                "student_name": student_name,
                "class_id": class_info['name'],
                "class_name": class_info['class_name'],
                "homeroom_teacher": class_info['homeroom_teacher'],
                "vice_homeroom_teacher": class_info['vice_homeroom_teacher'],
                "log_date": str(log_date) if log_date else None
            }
            enriched_logs.append(enriched_log)
        
        return success_response(
            message=f"Found {len(enriched_logs)} contact logs",
            data={
                "logs": enriched_logs,
                "total": len(enriched_logs),
                "student_name": student_name
            }
        )
    
    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        print(f"❌ get_student_contact_logs error: {str(e)}")
        print(error_detail)
        # Don't use frappe.log_error to avoid nested CharacterLengthExceededError
        return error_response(
            message=f"Failed to get contact logs: {str(e)[:200]}",
            code="GET_LOGS_ERROR"
        )


@frappe.whitelist(allow_guest=False, methods=["POST"])
def mark_viewed():
    """
    Mark a contact log as viewed by parent
    Increments the viewed count
    """
    try:
        # Get request body - try multiple methods
        body = {}
        try:
            request_data = frappe.request.get_data(as_text=True)
            if request_data:
                body = json.loads(request_data)
        except Exception:
            # Fallback to form_dict
            body = frappe.form_dict
        
        log_id = body.get('log_id')
        
        print(f"👁️ mark_viewed called for log_id: {log_id}")
        
        if not log_id:
            return error_response(message="Missing log_id", code="MISSING_PARAMS")
        
        # Get log
        log = frappe.get_doc("SIS Class Log Student", log_id)
        
        # Verify parent has access to this student
        parent_email = frappe.session.user
        parent_student_ids = _get_parent_student_ids(parent_email)
        
        if log.student_id not in parent_student_ids:
            return error_response(
                message="You do not have permission to view this contact log",
                code="PERMISSION_DENIED"
            )
        
        # Increment viewed count
        current_count = log.contact_log_viewed_count or 0
        new_count = current_count + 1
        log.contact_log_viewed_count = new_count
        log.save(ignore_permissions=True)  # Parent doesn't have write permission, but should be able to mark as viewed
        
        frappe.db.commit()
        
        print(f"✅ Marked log {log_id} as viewed: {current_count} -> {new_count}")
        
        return success_response(
            message="Marked as viewed",
            data={"viewed_count": log.contact_log_viewed_count}
        )
    
    except Exception as e:
        frappe.log_error(f"mark_viewed error: {str(e)}")
        return error_response(
            message="Failed to mark as viewed",
            code="MARK_VIEWED_ERROR"
        )
