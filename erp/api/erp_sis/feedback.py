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
    allowed_roles = ["System Manager", "SIS Manager", "Administrator"]
    
    if not any(role in allowed_roles for role in user_roles):
        frappe.throw(_("Bạn không có quyền truy cập API này"), frappe.PermissionError)


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
        
        # Calculate SLA status and add guardian_name for each feedback
        for feedback in feedback_list:
            # Add guardian_name
            if feedback.get("guardian"):
                feedback["guardian_name"] = guardian_name_map.get(feedback["guardian"], feedback["guardian"])
            
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
            return validation_error_response("name là bắt buộc")
        
        # Get feedback
        feedback = frappe.get_doc("Feedback", feedback_name)
        feedback_data = feedback.as_dict()

        # Include all replies (including internal notes for admin)
        if feedback.replies:
            feedback_data["replies"] = [
                {
                    "content": reply.content,
                    "reply_by": reply.reply_by,
                    "reply_by_type": reply.reply_by_type,
                    "reply_date": reply.reply_date,
                    "is_internal": reply.is_internal
                }
                for reply in feedback.replies
            ]

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

                # Get students from student_relationships table
                students = []
                if guardian.student_relationships:
                    for relationship in guardian.student_relationships:
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

                            # If we have student_code, get class info from SIS Student
                            if student_code:
                                sis_students = frappe.get_all("Student",
                                    filters={"student_code": student_code},
                                    fields=["name", "student_name", "program"]
                                )

                                if sis_students:
                                    sis_student = sis_students[0]
                                    program = sis_student.program

                                    # Get class info from SIS Class Student - only regular classes
                                    student_classes = frappe.get_all("SIS Class Student",
                                        filters={"student_id": sis_student.name},
                                        fields=["class_id"]
                                    )

                                    for class_ref in student_classes:
                                        try:
                                            class_doc = frappe.get_doc("SIS Class", class_ref.class_id)
                                            # Check if this is a regular class (not mixed/club)
                                            if hasattr(class_doc, 'class_type') and class_doc.class_type == "regular":
                                                class_name = class_doc.title
                                                break  # Use first regular class found
                                        except:
                                            continue

                        except frappe.DoesNotExistError:
                            # Student not found, use relationship student ID
                            student_name = relationship.student
                        except Exception as e:
                            # Any other error, log and use relationship student ID
                            frappe.logger().error(f"Error getting student {relationship.student}: {str(e)}")
                            student_name = relationship.student

                        student_info = {
                            "name": student_name,
                            "student_id": relationship.student,
                            "relationship": relationship.relationship_type,
                            "class_name": class_name,
                            "program": program
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
            return validation_error_response("name là bắt buộc")
        
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
            return validation_error_response("feedback_names là bắt buộc")
        if not assigned_to:
            return validation_error_response("assigned_to là bắt buộc")
        
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
            return validation_error_response("name là bắt buộc")
        if not priority:
            return validation_error_response("priority là bắt buộc")
        
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


@frappe.whitelist(allow_guest=False)
def add_reply():
    """Add reply to feedback (staff only)"""
    try:
        _check_staff_permission()
        
        data = frappe.local.form_dict
        feedback_name = data.get("name")
        content = data.get("content")
        is_internal = data.get("is_internal", False)
        
        if not feedback_name:
            return validation_error_response("name là bắt buộc")
        if not content:
            return validation_error_response("content là bắt buộc")
        
        # Get feedback
        feedback = frappe.get_doc("Feedback", feedback_name)
        
        # Only reply to Góp ý type
        if feedback.feedback_type != "Góp ý":
            return error_response(
                message="Chỉ có thể phản hồi feedback loại Góp ý",
                code="REPLY_NOT_ALLOWED"
            )
        
        # Add reply
        feedback.append("replies", {
            "content": content,
            "reply_by": frappe.session.user,
            "reply_by_type": "Staff",
            "reply_date": now(),
            "is_internal": is_internal
        })
        
        # Update status
        if feedback.status == "Mới":
            feedback.status = "Đang xử lý"
        elif feedback.status == "Đã phản hồi":
            feedback.status = "Chờ phản hồi phụ huynh"
        else:
            feedback.status = "Đã phản hồi"
        
        feedback.save()
        frappe.db.commit()
        
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
def update_status():
    """Update feedback status (staff only)"""
    try:
        _check_staff_permission()
        
        data = frappe.local.form_dict
        feedback_name = data.get("name")
        status = data.get("status")
        
        if not feedback_name:
            return validation_error_response("name là bắt buộc")
        if not status:
            return validation_error_response("status là bắt buộc")
        
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
            return validation_error_response("name là bắt buộc")
        
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
def update_assignment():
    """Update feedback assignment and priority together"""
    try:
        _check_staff_permission()

        data = frappe.local.form_dict

        feedback_name = data.get("name")
        assigned_to = data.get("assigned_to")
        priority = data.get("priority")

        if not feedback_name:
            return validation_error_response("name là bắt buộc")

        # Get feedback
        feedback = frappe.get_doc("Feedback", feedback_name)

        # Update fields
        if assigned_to:
            feedback.assigned_to = assigned_to
            feedback.assigned_date = now()

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

