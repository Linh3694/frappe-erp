# Copyright (c) 2025, Wellspring International School and contributors
# For license information, please see license.txt

"""
Feedback Admin API for Staff/Admin
Handles feedback management, assignment, SLA tracking, and reporting
"""

import frappe
from frappe import _
from frappe.utils import now, get_datetime, add_to_date
from datetime import datetime, timedelta
import json
from erp.utils.api_response import (
    success_response,
    error_response,
    list_response,
    single_item_response,
    validation_error_response
)


def _check_staff_permission():
    """Check if user has staff/admin permission"""
    user_roles = frappe.get_roles()
    allowed_roles = ["System Manager", "SIS Manager", "SIS Sales", "SIS IT"]

    if not any(role in allowed_roles for role in user_roles):
        frappe.throw(_("Bạn không có quyền truy cập API này"), frappe.PermissionError)


def _get_request_data():
    """Get request data from various sources (JSON body, form_dict, or multipart form)
    Following parent_portal/feedback.py pattern for better file upload support"""
    # Check if files exist AND not empty
    has_files = frappe.request.files and len(frappe.request.files) > 0
    
    if has_files:
        # FormData with files - use request.form (this is how Flask handles multipart)
        data = dict(frappe.request.form)
        frappe.logger().info(f"[_get_request_data] Using request.form (has {len(frappe.request.files)} files)")
    elif hasattr(frappe.request, 'is_json') and frappe.request.is_json:
        # JSON request - use request.json
        data = frappe.request.json or {}
        frappe.logger().info("[_get_request_data] Using request.json (JSON body)")
    else:
        # Try to get from JSON body manually
        data = {}
        try:
            if hasattr(frappe.request, 'data') and frappe.request.data:
                raw = frappe.request.data
                body = raw.decode('utf-8') if isinstance(raw, (bytes, bytearray)) else raw
                if body:
                    parsed = json.loads(body)
                    if isinstance(parsed, dict):
                        data.update(parsed)
                        frappe.logger().info("[_get_request_data] Using manual JSON parse")
        except (json.JSONDecodeError, AttributeError, TypeError) as e:
            frappe.logger().error(f"Error parsing JSON body: {str(e)}")
        
        # Fallback to form_dict
        if not data and frappe.local.form_dict:
            data = dict(frappe.local.form_dict)
            frappe.logger().info("[_get_request_data] Using form_dict (fallback)")
    
    frappe.logger().info(f"[_get_request_data] Final data keys: {list(data.keys())}")
    return data


def _calculate_business_hours_deadline(start_date, hours):
    """Calculate deadline in business hours (exclude Sat-Sun)"""
    deadline = get_datetime(start_date)
    hours_added = 0
    
    while hours_added < hours:
        deadline = deadline + timedelta(hours=1)
        # Skip weekends (Saturday=5, Sunday=6)
        if deadline.weekday() < 5:  # Monday-Friday
            hours_added += 1
    
    return deadline


@frappe.whitelist(allow_guest=False)
def admin_list():
    """List all feedback with filters for admin"""
    try:
        _check_staff_permission()
        
        data = frappe.local.form_dict
        request_args = frappe.request.args
        
        # Get pagination params
        page = int(data.get("page", request_args.get("page", 1)))
        page_length = int(data.get("page_length", request_args.get("page_length", 20)))
        offset = (page - 1) * page_length
        
        # Build filters
        filters = {}
        
        # Feedback type filter
        if data.get("feedback_type"):
            filters["feedback_type"] = data.get("feedback_type")
        
        # Status filter
        if data.get("status"):
            filters["status"] = data.get("status")
        
        # Department filter (only for Góp ý)
        if data.get("department"):
            filters["department"] = data.get("department")
        
        # Priority filter (only for Góp ý)
        if data.get("priority"):
            filters["priority"] = data.get("priority")
        
        # Rating filter (only for Đánh giá)
        if data.get("rating"):
            filters["rating"] = data.get("rating")
        
        # Assigned to filter
        if data.get("assigned_to"):
            filters["assigned_to"] = data.get("assigned_to")
        
        # Date range filter
        if data.get("date_from"):
            filters["submitted_at"] = [">=", data.get("date_from")]
        if data.get("date_to"):
            if "submitted_at" in filters:
                filters["submitted_at"] = ["between", [data.get("date_from"), data.get("date_to")]]
            else:
                filters["submitted_at"] = ["<=", data.get("date_to")]
        
        # Search query
        search_query = data.get("search") or request_args.get("search")
        search_filters = []
        if search_query:
            search_filters = [
                ["title", "like", f"%{search_query}%"],
                ["content", "like", f"%{search_query}%"],
                ["guardian", "like", f"%{search_query}%"]
            ]
        
        # Get feedback list
        feedback_list = frappe.get_all(
            "Feedback",
            filters=filters,
            or_filters=search_filters if search_filters else None,
            fields=[
                "name", "feedback_type", "title", "status", "priority",
                "rating", "rating_comment", "department",
                "guardian", "assigned_to", "assigned_date",
                "submitted_at", "last_updated", "closed_at",
                "conversation_count", "resolution_rating",
                "deadline", "sla_status", "first_response_date"
            ],
            order_by="submitted_at desc",
            limit=page_length,
            limit_start=offset
        )
        
        # Get guardian names for all feedback
        guardian_names = set([f.get("guardian") for f in feedback_list if f.get("guardian")])
        guardian_name_map = {}
        if guardian_names:
            guardians = frappe.get_all(
                "CRM Guardian",
                filters={"name": ["in", list(guardian_names)]},
                fields=["name", "guardian_name"]
            )
            guardian_name_map = {g["name"]: g.get("guardian_name") for g in guardians}
        
        # Get assigned user full names
        assigned_users = set([f.get("assigned_to") for f in feedback_list if f.get("assigned_to")])
        assigned_user_map = {}
        if assigned_users:
            users = frappe.get_all(
                "User",
                filters={"name": ["in", list(assigned_users)]},
                fields=["name", "full_name"]
            )
            assigned_user_map = {u["name"]: u.get("full_name") for u in users}
        
        # Calculate SLA status and add guardian_name, assigned_to_full_name for each feedback
        for feedback in feedback_list:
            # Add guardian_name
            if feedback.get("guardian"):
                feedback["guardian_name"] = guardian_name_map.get(feedback["guardian"], feedback["guardian"])
            
            # Add assigned_to_full_name
            if feedback.get("assigned_to"):
                feedback["assigned_to_full_name"] = assigned_user_map.get(feedback["assigned_to"], feedback["assigned_to"])
            
            # Calculate SLA status
            if feedback.get("deadline"):
                deadline_dt = get_datetime(feedback["deadline"])
                now_dt = get_datetime(now())
                hours_until_deadline = (deadline_dt - now_dt).total_seconds() / 3600
                
                if hours_until_deadline < 0:
                    feedback["sla_status"] = "Overdue"
                elif hours_until_deadline <= 6:
                    feedback["sla_status"] = "Warning"
                else:
                    feedback["sla_status"] = "On time"
        
        # Get total count
        total = frappe.db.count("Feedback", filters=filters)
        
        return success_response(
            data={
                "data": feedback_list,
                "total": total,
                "page": page,
                "page_length": page_length
            },
            message="Lấy danh sách feedback thành công"
        )
    
    except Exception as e:
        frappe.logger().error(f"Error listing feedback: {str(e)}")
        return error_response(
            message=f"Lỗi khi lấy danh sách feedback: {str(e)}",
            code="LIST_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def admin_get():
    """Get feedback detail for admin"""
    try:
        _check_staff_permission()
        
        data = frappe.local.form_dict
        request_args = frappe.request.args
        
        feedback_name = data.get("name") or request_args.get("name")
        if not feedback_name:
            return validation_error_response("name là bắt buộc", {"name": ["name là bắt buộc"]})
        
        # Get feedback
        feedback = frappe.get_doc("Feedback", feedback_name)
        feedback_data = feedback.as_dict()

        # Include all replies (including internal notes for admin)
        if feedback.replies:
            replies_data = []
            for reply in feedback.replies:
                reply_data = {
                    "content": reply.content,
                    "reply_by": reply.reply_by,
                    "reply_by_type": reply.reply_by_type,
                    "reply_date": reply.reply_date,
                    "is_internal": reply.is_internal,
                    "reply_by_full_name": None
                }
                # Get full_name for staff replies
                if reply.reply_by_type == "Staff" and reply.reply_by:
                    try:
                        reply_user = frappe.get_doc("User", reply.reply_by)
                        reply_data["reply_by_full_name"] = reply_user.full_name
                    except frappe.DoesNotExistError:
                        reply_data["reply_by_full_name"] = reply.reply_by
                # Get guardian name for guardian replies
                elif reply.reply_by_type == "Guardian" and feedback.guardian:
                    try:
                        guardian_doc = frappe.get_doc("CRM Guardian", feedback.guardian)
                        reply_data["reply_by_full_name"] = guardian_doc.guardian_name
                    except frappe.DoesNotExistError:
                        reply_data["reply_by_full_name"] = "Phụ huynh"
                replies_data.append(reply_data)
            feedback_data["replies"] = replies_data

        # Include assigned user information (full_name, jobtitle, avatar)
        if feedback.assigned_to:
            try:
                assigned_user = frappe.get_doc("User", feedback.assigned_to)
                feedback_data["assigned_to_full_name"] = assigned_user.full_name
                feedback_data["assigned_to_jobtitle"] = getattr(assigned_user, "job_title", None)
                feedback_data["assigned_to_avatar"] = assigned_user.user_image
            except frappe.DoesNotExistError:
                # If user not found, leave fields empty
                feedback_data["assigned_to_full_name"] = None
                feedback_data["assigned_to_jobtitle"] = None
                feedback_data["assigned_to_avatar"] = None

        # Include guardian information
        if feedback.guardian:
            try:
                guardian = frappe.get_doc("CRM Guardian", feedback.guardian)
                feedback_data["guardian_info"] = {
                    "name": guardian.guardian_name,
                    "phone_number": guardian.phone_number,
                    "email": guardian.email,
                    "students": []
                }

                # FIX: Lấy students từ CRM Family relationships (nguồn đúng)
                # KHÔNG dùng guardian.student_relationships vì có thể bị outdated
                family_relationships = frappe.db.sql("""
                    SELECT DISTINCT fr.student, fr.relationship_type, fr.key_person
                    FROM `tabCRM Family Relationship` fr
                    INNER JOIN `tabCRM Family` f ON fr.parent = f.name
                    WHERE fr.guardian = %(guardian)s 
                        AND fr.parentfield = 'relationships'
                        AND f.docstatus < 2
                """, {"guardian": feedback.guardian}, as_dict=True)
                
                # Lấy năm học hiện tại đang active (is_enable = 1)
                current_year = frappe.get_all(
                    "SIS School Year",
                    filters={"is_enable": 1},
                    fields=["name"],
                    order_by="creation desc",
                    limit=1
                )
                current_school_year_id = current_year[0].name if current_year else None
                
                students = []
                for relationship in family_relationships:
                    # Get student info from CRM Student and SIS Student doctypes
                    student_name = relationship.student
                    student_code = None
                    class_name = None
                    program = None

                    try:
                        # Get from CRM Student
                        crm_student = frappe.get_doc("CRM Student", relationship.student)
                        student_name = crm_student.student_name or relationship.student
                        student_code = crm_student.student_code

                        # Use CRM Student name as student_id for SIS Class Student (same as otp_auth.py)
                        # Get class info from SIS Class Student directly using CRM Student name
                        program = None  # Will be set if we can find SIS Student

                        student_classes = frappe.get_all("SIS Class Student",
                            filters={"student_id": relationship.student},  # Use CRM Student name directly
                            fields=["class_id"],
                            order_by="modified desc"
                        )

                        # Find the regular class of current school year
                        # QUAN TRỌNG: Chỉ lấy lớp của năm học hiện tại
                        class_name = None
                        for cs in student_classes:
                            if cs["class_id"]:
                                try:
                                    class_doc = frappe.get_doc("SIS Class", cs["class_id"])
                                    # Check if this is a regular class AND belongs to current school year
                                    if hasattr(class_doc, 'class_type') and class_doc.class_type == "regular":
                                        # Ưu tiên lớp của năm học hiện tại
                                        if current_school_year_id and hasattr(class_doc, 'school_year_id') and class_doc.school_year_id == current_school_year_id:
                                            class_name = class_doc.title
                                            break  # Found class of current school year
                                        # Fallback: nếu không có năm học hiện tại, lấy lớp mới nhất
                                        elif not current_school_year_id and not class_name:
                                            class_name = class_doc.title
                                except:
                                    continue

                    except frappe.DoesNotExistError:
                        # Student not found, use relationship student ID
                        student_name = relationship.student
                    except Exception as e:
                        # Any other error, log and use relationship student ID
                        frappe.logger().error(f"Error getting student {relationship.student}: {str(e)}")
                        student_name = relationship.student

                    # Get student photo from SIS Photo (same as otp_auth.py)
                    student_photo = None
                    photo_title = None

                    try:
                        # Lấy năm học hiện tại đang active
                        current_school_year = frappe.db.get_value(
                            "SIS School Year",
                            {"is_enable": 1},
                            "name",
                            order_by="start_date desc"
                        )
                        
                        # Ưu tiên: 1) Năm học hiện tại trước, 2) Upload date mới nhất, 3) Creation mới nhất
                        sis_photos = frappe.db.sql("""
                            SELECT photo, title, upload_date, school_year_id
                            FROM `tabSIS Photo`
                            WHERE student_id = %s
                                AND type = 'student'
                                AND status = 'Active'
                            ORDER BY 
                                CASE WHEN school_year_id = %s THEN 0 ELSE 1 END,
                                upload_date DESC,
                                creation DESC
                            LIMIT 1
                        """, (relationship.student, current_school_year), as_dict=True)

                        if sis_photos:
                            student_photo = sis_photos[0]["photo"]
                            photo_title = sis_photos[0]["title"]
                    except:
                        pass  # Photo is optional, don't fail if not found

                    student_info = {
                        "name": student_name,
                        "student_id": student_code or relationship.student,  # student_code from CRM Student, fallback to CRM Student ID
                        "relationship": relationship.relationship_type,
                        "class_name": class_name,
                        "program": program,
                        "photo": student_photo,
                        "photo_title": photo_title
                    }
                    students.append(student_info)

                feedback_data["guardian_info"]["students"] = students

            except frappe.DoesNotExistError:
                # Guardian not found, set empty info
                feedback_data["guardian_info"] = {
                    "name": feedback.guardian_name or feedback.guardian,
                    "phone_number": None,
                    "email": None,
                    "students": []
                }
        
        return single_item_response(data=feedback_data)
    
    except frappe.DoesNotExistError:
        return error_response(
            message="Feedback không tồn tại",
            code="NOT_FOUND"
        )
    except Exception as e:
        frappe.logger().error(f"Error getting feedback: {str(e)}")
        return error_response(
            message=f"Lỗi khi lấy feedback: {str(e)}",
            code="GET_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def assign():
    """Assign feedback to user"""
    try:
        _check_staff_permission()
        
        data = frappe.local.form_dict
        feedback_name = data.get("name")
        assigned_to = data.get("assigned_to")
        priority = data.get("priority")

        if not feedback_name:
            return validation_error_response("name là bắt buộc", {"name": ["name là bắt buộc"]})
        
        # Get feedback
        feedback = frappe.get_doc("Feedback", feedback_name)
        
        # Only assign Góp ý type
        if feedback.feedback_type != "Góp ý":
            return error_response(
                message="Chỉ có thể phân công feedback loại Góp ý",
                code="ASSIGN_NOT_ALLOWED"
            )
        
        # Update assignment
        if assigned_to:
            feedback.assigned_to = assigned_to
            feedback.assigned_date = now()
            
            # Save assigned user information
            try:
                assigned_user = frappe.get_doc("User", assigned_to)
                feedback.assigned_to_full_name = assigned_user.full_name
                feedback.assigned_to_jobtitle = getattr(assigned_user, "job_title", None)
                feedback.assigned_to_avatar = assigned_user.user_image
            except frappe.DoesNotExistError:
                # If user not found, set to None
                feedback.assigned_to_full_name = None
                feedback.assigned_to_jobtitle = None
                feedback.assigned_to_avatar = None
            
            # Calculate deadline based on priority
            if feedback.priority:
                priority_hours = {
                    "Khẩn cấp": 6,
                    "Cao": 12,
                    "Trung bình": 24,
                    "Thấp": 48
                }
                hours = priority_hours.get(feedback.priority, 24)
                feedback.deadline = _calculate_business_hours_deadline(now(), hours)
        
        # Update priority if provided
        if priority:
            feedback.priority = priority
            # Recalculate deadline if assigned
            if feedback.assigned_to:
                priority_hours = {
                    "Khẩn cấp": 6,
                    "Cao": 12,
                    "Trung bình": 24,
                    "Thấp": 48
                }
                hours = priority_hours.get(priority, 24)
                feedback.deadline = _calculate_business_hours_deadline(
                    feedback.assigned_date or now(),
                    hours
                )
        
        # Update status if needed
        if feedback.status == "Mới" and assigned_to:
            feedback.status = "Đang xử lý"
        
        feedback.save()
        frappe.db.commit()
        
        # Send push notification to assigned user
        try:
            if assigned_to:
                from erp.api.notification.feedback import send_feedback_assigned_notification
                send_feedback_assigned_notification(feedback, frappe.session.user)
        except Exception as notify_error:
            frappe.logger().error(f"Error sending assignment notification: {str(notify_error)}")
            # Don't fail the request if notification fails
        
        return success_response(
            data={"name": feedback.name},
            message="Phân công feedback thành công"
        )
    
    except frappe.DoesNotExistError:
        return error_response(
            message="Feedback không tồn tại",
            code="NOT_FOUND"
        )
    except Exception as e:
        frappe.logger().error(f"Error assigning feedback: {str(e)}")
        return error_response(
            message=f"Lỗi khi phân công feedback: {str(e)}",
            code="ASSIGN_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def assign_bulk():
    """Bulk assign feedback to users"""
    try:
        _check_staff_permission()
        
        data = frappe.local.form_dict
        feedback_names = data.get("feedback_names", [])
        assigned_to = data.get("assigned_to")
        priority = data.get("priority")

        if not feedback_names:
            return validation_error_response("feedback_names là bắt buộc", {"feedback_names": ["feedback_names là bắt buộc"]})
        if not assigned_to:
            return validation_error_response("assigned_to là bắt buộc", {"assigned_to": ["assigned_to là bắt buộc"]})
        
        success_count = 0
        error_count = 0
        
        for feedback_name in feedback_names:
            try:
                feedback = frappe.get_doc("Feedback", feedback_name)
                
                # Only assign Góp ý type
                if feedback.feedback_type != "Góp ý":
                    error_count += 1
                    continue
                
                feedback.assigned_to = assigned_to
                feedback.assigned_date = now()
                
                # Save assigned user information
                try:
                    assigned_user = frappe.get_doc("User", assigned_to)
                    feedback.assigned_to_full_name = assigned_user.full_name
                    feedback.assigned_to_jobtitle = getattr(assigned_user, "job_title", None)
                    feedback.assigned_to_avatar = assigned_user.user_image
                except frappe.DoesNotExistError:
                    # If user not found, set to None
                    feedback.assigned_to_full_name = None
                    feedback.assigned_to_jobtitle = None
                    feedback.assigned_to_avatar = None
                
                # Update priority if provided
                if priority:
                    feedback.priority = priority
                
                # Calculate deadline
                priority_hours = {
                    "Khẩn cấp": 6,
                    "Cao": 12,
                    "Trung bình": 24,
                    "Thấp": 48
                }
                hours = priority_hours.get(feedback.priority or "Trung bình", 24)
                feedback.deadline = _calculate_business_hours_deadline(now(), hours)
                
                # Update status
                if feedback.status == "Mới":
                    feedback.status = "Đang xử lý"
                
                feedback.save()
                success_count += 1
            
            except Exception as e:
                frappe.logger().error(f"Error assigning feedback {feedback_name}: {str(e)}")
                error_count += 1
        
        frappe.db.commit()
        
        return success_response(
            data={
                "success_count": success_count,
                "error_count": error_count
            },
            message=f"Phân công thành công {success_count} feedback, lỗi {error_count} feedback"
        )
    
    except Exception as e:
        frappe.logger().error(f"Error bulk assigning feedback: {str(e)}")
        return error_response(
            message=f"Lỗi khi phân công hàng loạt: {str(e)}",
            code="BULK_ASSIGN_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def update_priority():
    """Update priority for feedback"""
    try:
        _check_staff_permission()
        
        data = frappe.local.form_dict
        feedback_name = data.get("name")
        priority = data.get("priority")

        if not feedback_name:
            return validation_error_response("name là bắt buộc", {"name": ["name là bắt buộc"]})
        if not priority:
            return validation_error_response("priority là bắt buộc", {"priority": ["priority là bắt buộc"]})
        
        # Get feedback
        feedback = frappe.get_doc("Feedback", feedback_name)
        
        # Only update priority for Góp ý
        if feedback.feedback_type != "Góp ý":
            return error_response(
                message="Chỉ có thể cập nhật độ ưu tiên cho feedback loại Góp ý",
                code="UPDATE_NOT_ALLOWED"
            )
        
        feedback.priority = priority
        
        # Recalculate deadline if assigned
        if feedback.assigned_to:
            priority_hours = {
                "Khẩn cấp": 6,
                "Cao": 12,
                "Trung bình": 24,
                "Thấp": 48
            }
            hours = priority_hours.get(priority, 24)
            feedback.deadline = _calculate_business_hours_deadline(
                feedback.assigned_date or feedback.submitted_at or now(),
                hours
            )
        
        feedback.save()
        frappe.db.commit()
        
        return success_response(
            data={"name": feedback.name},
            message="Cập nhật độ ưu tiên thành công"
        )
    
    except frappe.DoesNotExistError:
        return error_response(
            message="Feedback không tồn tại",
            code="NOT_FOUND"
        )
    except Exception as e:
        frappe.logger().error(f"Error updating priority: {str(e)}")
        return error_response(
            message=f"Lỗi khi cập nhật độ ưu tiên: {str(e)}",
            code="UPDATE_PRIORITY_ERROR"
        )


def _process_staff_attachments(feedback_name, reply_index=None):
    """Process file attachments from frappe.request.files for staff reply"""
    attachment_urls = []

    if not frappe.request.files:
        return attachment_urls

    for file_key, file_list in frappe.request.files.items(multi=True):
        if not isinstance(file_list, list):
            file_list = [file_list]
            
        for file_obj in file_list:
            if file_obj and file_obj.filename:
                try:
                    file_content = file_obj.read()
                    if not file_content:
                        continue

                    # Generate unique filename
                    import uuid
                    unique_id = str(uuid.uuid4())[:8]
                    original_name = file_obj.filename
                    name_parts = original_name.rsplit('.', 1)
                    if len(name_parts) == 2:
                        new_filename = f"{name_parts[0]}_{unique_id}.{name_parts[1]}"
                    else:
                        new_filename = f"{original_name}_{unique_id}"

                    file_doc = frappe.get_doc({
                        "doctype": "File",
                        "file_name": new_filename,
                        "content": file_content,
                        "attached_to_doctype": "Feedback",
                        "attached_to_name": feedback_name,
                        "attached_to_field": "replies",
                        "is_private": 0  # Public file để mobile có thể hiển thị
                    })
                    file_doc.insert(ignore_permissions=True)

                    file_url = file_doc.file_url
                    if file_url:
                        attachment_urls.append(file_url)

                except Exception as e:
                    frappe.logger().error(f"Error processing staff attachment {file_key}: {str(e)}")

    return attachment_urls


@frappe.whitelist(allow_guest=False)
def add_reply():
    """Add reply to feedback (staff only)"""
    try:
        _check_staff_permission()
        
        data = _get_request_data()
        feedback_name = data.get("name")
        content = data.get("content")
        
        # Parse boolean values properly (FormData sends strings "0"/"1")
        is_internal_raw = data.get("is_internal", False)
        is_internal = is_internal_raw in [True, 1, "1", "true", "True"]
        
        is_draft_raw = data.get("is_draft", False)
        is_draft = is_draft_raw in [True, 1, "1", "true", "True"]
        
        frappe.logger().info(f"[add_reply] is_internal_raw={is_internal_raw}, is_internal={is_internal}")

        if not feedback_name:
            return validation_error_response("name là bắt buộc", {"name": ["name là bắt buộc"]})
        if not content:
            return validation_error_response("content là bắt buộc", {"content": ["content là bắt buộc"]})
        
        # Get feedback
        feedback = frappe.get_doc("Feedback", feedback_name)
        
        # Allow reply to both Góp ý and Đánh giá types
        # Staff can respond to ratings (especially low ratings) to address concerns
        
        # If draft, check if there's existing draft from this user and update it
        if is_draft:
            # Find existing draft reply from current user
            draft_found = False
            if feedback.replies:
                for reply in feedback.replies:
                    if reply.is_internal and reply.reply_by == frappe.session.user:
                        # Update existing draft
                        reply.content = content
                        reply.reply_date = now()
                        draft_found = True
                        break
            
            # If no existing draft, create new one
            if not draft_found:
                feedback.append("replies", {
                    "content": content,
                    "reply_by": frappe.session.user,
                    "reply_by_type": "Staff",
                    "reply_date": now(),
                    "is_internal": True  # Draft is always internal
                })
            
            # Don't update status for draft
            feedback.save()
            frappe.db.commit()
            
            return success_response(
                data={"name": feedback.name},
                message="Lưu tạm thành công"
            )
        
        # Process file attachments if any
        attachment_urls = _process_staff_attachments(feedback_name)
        
        # Build final content with attachments
        final_content = content
        if attachment_urls:
            # Append attachment info to content as HTML
            attachments_html = "\n\n---\n**File đính kèm:**\n"
            for url in attachment_urls:
                attachments_html += f'- <a href="{url}" target="_blank">{url.split("/")[-1]}</a>\n'
            final_content += attachments_html
        
        # For non-draft replies, check if there's a draft to convert
        if feedback.replies:
            for reply in feedback.replies:
                if reply.is_internal and reply.reply_by == frappe.session.user:
                    # Convert draft to public reply
                    reply.content = final_content
                    reply.is_internal = is_internal
                    reply.reply_date = now()
                    if attachment_urls:
                        reply.attachments = attachment_urls[0]  # Store first attachment in field
                    break
            else:
                # No draft found, add new reply
                feedback.append("replies", {
                    "content": final_content,
                    "reply_by": frappe.session.user,
                    "reply_by_type": "Staff",
                    "reply_date": now(),
                    "is_internal": is_internal,
                    "attachments": attachment_urls[0] if attachment_urls else None
                })
        else:
            # No replies yet, add new one
            feedback.append("replies", {
                "content": final_content,
                "reply_by": frappe.session.user,
                "reply_by_type": "Staff",
                "reply_date": now(),
                "is_internal": is_internal,
                "attachments": attachment_urls[0] if attachment_urls else None
            })
        
        # Update status only for non-draft replies
        # When staff replies, always set status to waiting for parent response
        feedback.status = "Chờ phản hồi phụ huynh"
        
        feedback.save()
        frappe.db.commit()
        
        # Send push notification to guardian (only for non-internal replies)
        frappe.logger().info(f"[add_reply] Checking notification: is_internal={is_internal}")
        if not is_internal:
            try:
                frappe.logger().info(f"[add_reply] Sending notification to guardian for feedback {feedback.name}")
                from erp.api.notification.feedback import send_staff_reply_notification_to_guardian
                # Get staff name for notification
                staff_name = frappe.db.get_value("User", frappe.session.user, "full_name") or frappe.session.user
                send_staff_reply_notification_to_guardian(feedback, staff_name)
                frappe.logger().info(f"[add_reply] Notification function called successfully")
            except Exception as notify_error:
                frappe.logger().error(f"Error sending guardian notification: {str(notify_error)}")
                import traceback
                frappe.logger().error(f"Traceback: {traceback.format_exc()}")
                # Don't fail the request if notification fails
        else:
            frappe.logger().info(f"[add_reply] Skipping notification because is_internal={is_internal}")
        
        return success_response(
            data={"name": feedback.name},
            message="Thêm phản hồi thành công"
        )
    
    except frappe.DoesNotExistError:
        return error_response(
            message="Feedback không tồn tại",
            code="NOT_FOUND"
        )
    except Exception as e:
        frappe.logger().error(f"Error adding reply: {str(e)}")
        return error_response(
            message=f"Lỗi khi thêm phản hồi: {str(e)}",
            code="REPLY_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def get_draft_reply():
    """Get draft reply for current user"""
    try:
        _check_staff_permission()
        
        data = _get_request_data()
        request_args = frappe.request.args
        
        feedback_name = data.get("name") or request_args.get("name")
        if not feedback_name:
            return validation_error_response("name là bắt buộc", {"name": ["name là bắt buộc"]})
        
        # Get feedback
        feedback = frappe.get_doc("Feedback", feedback_name)
        
        # Find draft reply from current user
        draft_content = None
        if feedback.replies:
            for reply in feedback.replies:
                if reply.is_internal and reply.reply_by == frappe.session.user:
                    draft_content = reply.content
                    break
        
        return success_response(
            data={"draft_content": draft_content},
            message="Lấy draft thành công" if draft_content else "Không có draft"
        )
    
    except frappe.DoesNotExistError:
        return error_response(
            message="Feedback không tồn tại",
            code="NOT_FOUND"
        )
    except Exception as e:
        frappe.logger().error(f"Error getting draft reply: {str(e)}")
        return error_response(
            message=f"Lỗi khi lấy draft: {str(e)}",
            code="GET_DRAFT_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def update_status():
    """Update feedback status (staff only)"""
    try:
        _check_staff_permission()
        
        data = frappe.local.form_dict
        feedback_name = data.get("name")
        status = data.get("status")

        if not feedback_name:
            return validation_error_response("name là bắt buộc", {"name": ["name là bắt buộc"]})
        if not status:
            return validation_error_response("status là bắt buộc", {"status": ["status là bắt buộc"]})
        
        # Get feedback
        feedback = frappe.get_doc("Feedback", feedback_name)
        feedback.status = status
        
        # Set closed_at if closing
        if status in ["Đóng", "Tự động đóng"] and not feedback.closed_at:
            feedback.closed_at = now()
        
        feedback.save()
        frappe.db.commit()
        
        return success_response(
            data={"name": feedback.name},
            message="Cập nhật trạng thái thành công"
        )
    
    except frappe.DoesNotExistError:
        return error_response(
            message="Feedback không tồn tại",
            code="NOT_FOUND"
        )
    except Exception as e:
        frappe.logger().error(f"Error updating status: {str(e)}")
        return error_response(
            message=f"Lỗi khi cập nhật trạng thái: {str(e)}",
            code="STATUS_UPDATE_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def close_feedback():
    """Close feedback and trigger resolution rating"""
    try:
        _check_staff_permission()
        
        data = frappe.local.form_dict
        feedback_name = data.get("name")

        if not feedback_name:
            return validation_error_response("name là bắt buộc", {"name": ["name là bắt buộc"]})
        
        # Get feedback
        feedback = frappe.get_doc("Feedback", feedback_name)
        
        # Only close Góp ý type
        if feedback.feedback_type != "Góp ý":
            return error_response(
                message="Chỉ có thể đóng feedback loại Góp ý",
                code="CLOSE_NOT_ALLOWED"
            )
        
        # Update status
        feedback.status = "Đóng"
        feedback.closed_at = now()
        
        feedback.save()
        frappe.db.commit()
        
        return success_response(
            data={"name": feedback.name},
            message="Đóng feedback thành công. Phụ huynh sẽ được yêu cầu đánh giá việc giải quyết."
        )
    
    except frappe.DoesNotExistError:
        return error_response(
            message="Feedback không tồn tại",
            code="NOT_FOUND"
        )
    except Exception as e:
        frappe.logger().error(f"Error closing feedback: {str(e)}")
        return error_response(
            message=f"Lỗi khi đóng feedback: {str(e)}",
            code="CLOSE_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def delete_feedback():
    """Delete feedback permanently"""
    try:
        _check_staff_permission()
        
        data = _get_request_data()
        request_args = frappe.request.args
        
        feedback_name = data.get("name") or request_args.get("name")
        if not feedback_name:
            return validation_error_response("name là bắt buộc", {"name": ["name là bắt buộc"]})
        
        # Get feedback to check if exists
        feedback = frappe.get_doc("Feedback", feedback_name)
        
        # Delete the feedback
        frappe.delete_doc("Feedback", feedback_name, force=True)
        frappe.db.commit()
        
        return success_response(
            data={"name": feedback_name},
            message="Xóa feedback thành công"
        )
    
    except frappe.DoesNotExistError:
        return error_response(
            message="Feedback không tồn tại",
            code="NOT_FOUND"
        )
    except Exception as e:
        frappe.logger().error(f"Error deleting feedback: {str(e)}")
        return error_response(
            message=f"Lỗi khi xóa feedback: {str(e)}",
            code="DELETE_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def sla_report():
    """SLA performance report"""
    try:
        _check_staff_permission()
        
        data = frappe.local.form_dict
        request_args = frappe.request.args
        
        # Date range filter
        date_from = data.get("date_from") or request_args.get("date_from")
        date_to = data.get("date_to") or request_args.get("date_to")
        
        filters = {"feedback_type": "Góp ý"}
        
        if date_from:
            filters["submitted_at"] = [">=", date_from]
        if date_to:
            if "submitted_at" in filters:
                filters["submitted_at"] = ["between", [date_from or "", date_to]]
            else:
                filters["submitted_at"] = ["<=", date_to]
        
        # Get all feedback
        feedback_list = frappe.get_all(
            "Feedback",
            filters=filters,
            fields=[
                "name", "department", "priority", "status",
                "submitted_at", "first_response_date", "deadline",
                "sla_status", "assigned_to"
            ]
        )
        
        # Calculate statistics
        total = len(feedback_list)
        overdue = len([f for f in feedback_list if f.get("sla_status") == "Overdue"])
        warning = len([f for f in feedback_list if f.get("sla_status") == "Warning"])
        on_time = len([f for f in feedback_list if f.get("sla_status") == "On time"])
        
        # Calculate average response time
        response_times = []
        for feedback in feedback_list:
            if feedback.get("first_response_date") and feedback.get("submitted_at"):
                submitted = get_datetime(feedback["submitted_at"])
                first_response = get_datetime(feedback["first_response_date"])
                hours = (first_response - submitted).total_seconds() / 3600
                response_times.append(hours)
        
        avg_response_time = sum(response_times) / len(response_times) if response_times else 0
        
        # Department-wise statistics
        department_stats = {}
        for feedback in feedback_list:
            dept = feedback.get("department", "Khác")
            if dept not in department_stats:
                department_stats[dept] = {
                    "total": 0,
                    "overdue": 0,
                    "warning": 0,
                    "on_time": 0
                }
            
            department_stats[dept]["total"] += 1
            sla_status = feedback.get("sla_status", "On time")
            if sla_status == "Overdue":
                department_stats[dept]["overdue"] += 1
            elif sla_status == "Warning":
                department_stats[dept]["warning"] += 1
            else:
                department_stats[dept]["on_time"] += 1
        
        return success_response(
            data={
                "total": total,
                "overdue": overdue,
                "warning": warning,
                "on_time": on_time,
                "average_response_time_hours": round(avg_response_time, 2),
                "department_statistics": department_stats
            },
            message="Báo cáo SLA"
        )
    
    except Exception as e:
        frappe.logger().error(f"Error generating SLA report: {str(e)}")
        return error_response(
            message=f"Lỗi khi tạo báo cáo SLA: {str(e)}",
            code="SLA_REPORT_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def export():
    """Export feedback data to CSV/Excel"""
    try:
        _check_staff_permission()
        
        # Use admin_list to get data
        result = admin_list()
        
        if result.get("success"):
            # Return data for export
            return success_response(
                data=result.get("data", {}).get("data", []),
                message="Dữ liệu feedback để export"
            )
        else:
            return result
    
    except Exception as e:
        frappe.logger().error(f"Error exporting feedback: {str(e)}")
        return error_response(
            message=f"Lỗi khi export feedback: {str(e)}",
            code="EXPORT_ERROR"
        )



@frappe.whitelist(allow_guest=False)
def get_users_for_assignment():
    """Get users with SIS IT or Mobile IT role for feedback assignment selection"""
    try:
        _check_staff_permission()

        # Get enabled users with SIS IT or Mobile IT role using SQL join for better performance
        users = frappe.db.sql("""
            SELECT DISTINCT
                u.name,
                u.email,
                u.full_name,
                u.first_name,
                u.last_name,
                u.user_image,
                u.employee_code,
                u.employee_id
            FROM `tabUser` u
            INNER JOIN `tabHas Role` hr ON hr.parent = u.name
            WHERE u.enabled = 1
                AND hr.role IN ('SIS IT', 'Mobile IT')
            ORDER BY u.full_name ASC
        """, as_dict=True)

        # Ensure each user has user_id field (use name if not present)
        processed_users = []
        for user in users:
            processed_user = user.copy()
            # Ensure user_id is always present
            processed_user["user_id"] = user.get("name")  # name is the user ID in Frappe
            processed_users.append(processed_user)

        return success_response(
            data=processed_users,
            message="Lấy danh sách user SIS IT/Mobile IT thành công"
        )

    except Exception as e:
        frappe.logger().error(f"Error getting users for assignment: {str(e)}")
        return error_response(
            message=f"Lỗi khi lấy danh sách user: {str(e)}",
            code="GET_USERS_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def update_assignment():
    """Update feedback assignment and priority together"""
    try:
        _check_staff_permission()

        data = _get_request_data()
        frappe.logger().info(f"update_assignment - request data: {data}")

        feedback_name = data.get("name")
        assigned_to = data.get("assigned_to")
        priority = data.get("priority")

        frappe.logger().info(f"update_assignment - extracted: name={feedback_name}, assigned_to={assigned_to}, priority={priority}")

        if not feedback_name:
            return validation_error_response("name là bắt buộc", {"name": ["name là bắt buộc"]})

        # Get feedback
        feedback = frappe.get_doc("Feedback", feedback_name)

        # Update fields
        if assigned_to:
            feedback.assigned_to = assigned_to
            feedback.assigned_date = now()
            
            # Save assigned user information
            try:
                assigned_user = frappe.get_doc("User", assigned_to)
                feedback.assigned_to_full_name = assigned_user.full_name
                feedback.assigned_to_jobtitle = getattr(assigned_user, "job_title", None)
                feedback.assigned_to_avatar = assigned_user.user_image
            except frappe.DoesNotExistError:
                # If user not found, set to None
                feedback.assigned_to_full_name = None
                feedback.assigned_to_jobtitle = None
                feedback.assigned_to_avatar = None

        if priority:
            feedback.priority = priority

        # Save
        feedback.save()

        return single_item_response(data={"name": feedback.name})

    except frappe.DoesNotExistError:
        return error_response(
            message="Feedback không tồn tại",
            code="NOT_FOUND"
        )
    except Exception as e:
        frappe.logger().error(f"Error updating assignment: {str(e)}")
        return error_response(
            message=f"Lỗi khi cập nhật assignment: {str(e)}",
            code="UPDATE_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def get_staff_rating_stats():
    """Get rating statistics for staff members"""
    try:
        _check_staff_permission()

        # Get all closed feedbacks with resolution ratings and assigned_to
        feedbacks = frappe.get_all(
            "Feedback",
            filters={
                "status": "Đóng",
                "resolution_rating": ["!=", ""],
                "assigned_to": ["!=", ""]
            },
            fields=[
                "assigned_to",
                "resolution_rating",
                "assigned_to_full_name",
                "assigned_to_jobtitle"
            ]
        )

        # Group by assigned_to
        staff_stats = {}
        for feedback in feedbacks:
            staff_id = feedback.assigned_to
            # Convert from 0-1 scale to 1-5 scale for calculations
            rating_01 = float(feedback.resolution_rating) if feedback.resolution_rating else 0
            rating = round(rating_01 * 5)  # Convert to 1-5 scale and round to nearest integer

            if staff_id not in staff_stats:
                staff_stats[staff_id] = {
                    "staff_id": staff_id,
                    "staff_name": feedback.assigned_to_full_name or staff_id,
                    "job_title": feedback.assigned_to_jobtitle or "",
                    "total_feedbacks": 0,
                    "total_rating": 0,
                    "average_rating": 0,
                    "rating_distribution": {
                        "1_star": 0,
                        "2_star": 0,
                        "3_star": 0,
                        "4_star": 0,
                        "5_star": 0
                    }
                }

            staff_stats[staff_id]["total_feedbacks"] += 1
            staff_stats[staff_id]["total_rating"] += rating

            # Count rating distribution (already in 1-5 scale from the converted rating)
            star_rating = round(rating)
            if 1 <= star_rating <= 5:
                staff_stats[staff_id]["rating_distribution"][f"{star_rating}_star"] += 1

        # Calculate averages (keep in 1-5 scale for simplicity)
        for staff_id, stats in staff_stats.items():
            if stats["total_feedbacks"] > 0:
                stats["average_rating"] = round(stats["total_rating"] / stats["total_feedbacks"], 2)

        # Convert to list and sort by average rating (highest first)
        result = list(staff_stats.values())
        result.sort(key=lambda x: x["average_rating"], reverse=True)

        return success_response(
            data=result,
            message="Lấy thống kê rating staff thành công"
        )

    except Exception as e:
        frappe.logger().error(f"Error getting staff rating stats: {str(e)}")
        return error_response(
            message=f"Lỗi khi lấy thống kê rating: {str(e)}",
            code="STATS_ERROR"
        )

