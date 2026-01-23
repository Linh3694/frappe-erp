# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
import json
from erp.utils.campus_utils import get_current_campus_from_context
from erp.utils.api_response import (
    success_response,
    error_response,
    list_response,
    single_item_response,
    validation_error_response,
    not_found_response
)


@frappe.whitelist(allow_guest=False)
def get_announcements():
    """Get sent announcements for parent portal with filtering"""
    try:
        data = frappe.local.form_dict
        request_args = frappe.request.args
        request_values = frappe.request.values

        # Try to get student_id from multiple sources (GET params)
        student_id_param = data.get('student_id') or request_args.get('student_id') or request_values.get('student_id')

        campus_id = data.get("campus_id")

        frappe.logger().info(f"Parent portal - Campus_id from params: {data.get('campus_id')}, user: {frappe.session.user}, final campus_id: {campus_id}")

        # Check if SIS Announcement doctype exists
        if not frappe.db.exists("DocType", "SIS Announcement"):
            frappe.logger().error("SIS Announcement DocType does not exist")
            return error_response(
                message="Announcement system not available",
                code="DOCTYPE_NOT_FOUND"
            )

        # Build filters - only sent announcements
        filters = {
            "status": "sent"
        }

        # Add campus filter only if campus_id is provided
        if campus_id:
            filters["campus_id"] = campus_id

        # Log filters for debugging
        backend_log = f"Fetching announcements with filters={filters}"
        frappe.logger().info(f"Parent portal - {backend_log}")

        # Student ID for potential future filtering
        student_id = student_id_param if student_id_param else data.get("student_id")

        # Get search query
        search_query = data.get("search")
        if search_query:
            # Search in both English and Vietnamese titles and content
            search_filters = {
                "status": "sent",
                "title_en": ["like", f"%{search_query}%"]
            }
            if campus_id:
                search_filters["campus_id"] = campus_id

            # Try searching in title_en first
            search_results = frappe.get_all(
                "SIS Announcement",
                filters=search_filters,
                fields=["name"]
            )

            # If no results, search in title_vn
            if not search_results:
                search_filters["title_en"] = ["!=", None]  # Reset title_en filter
                search_filters["title_vn"] = ["like", f"%{search_query}%"]
                search_results = frappe.get_all(
                    "SIS Announcement",
                    filters=search_filters,
                    fields=["name"]
                )

            # If still no results, search in content
            if not search_results:
                search_filters["title_vn"] = ["!=", None]  # Reset title_vn filter
                search_filters["content_en"] = ["like", f"%{search_query}%"]
                search_results = frappe.get_all(
                    "SIS Announcement",
                    filters=search_filters,
                    fields=["name"]
                )

                if not search_results:
                    search_filters["content_en"] = ["!=", None]  # Reset content_en filter
                    search_filters["content_vn"] = ["like", f"%{search_query}%"]
                    search_results = frappe.get_all(
                        "SIS Announcement",
                        filters=search_filters,
                        fields=["name"]
                    )

            if search_results:
                announcement_names = [result.name for result in search_results]
                filters["name"] = ["in", announcement_names]
            else:
                # No search results found
                return list_response(
                    data=[],
                    meta={
                        "pagination": {
                            "page": 1,
                            "limit": int(data.get("limit", 10)),
                            "total": 0,
                            "pages": 0
                        }
                    }
                )

        # Get pagination parameters
        page = int(data.get("page", 1))
        limit = int(data.get("limit", 10))

        # Calculate offset
        offset = (page - 1) * limit

        # Get total count first
        total_count = frappe.db.count("SIS Announcement", filters=filters)

        # Get announcements with pagination
        announcements = frappe.get_all(
            "SIS Announcement",
            filters=filters,
            fields=[
                "name",
                "campus_id",
                "title_en",
                "title_vn",
                "content_en",
                "content_vn",
                "status",
                "sent_at",
                "sent_by",
                "recipients",
                "recipient_type",
                "created_at",
                "created_by",
                "updated_at",
                "updated_by"
            ],
            order_by="sent_at desc",  # Most recent first
            limit=limit,
            start=offset
        )

        # Get student information for recipient filtering
        student_grade_name = None
        student_class_name = None
        if student_id:
            try:
                # Get student's grade and class information
                class_students = frappe.get_all(
                    "SIS Class Student",
                    filters={"student_id": student_id},
                    fields=["class_id"],
                    order_by="creation desc",
                    limit=1
                )

                if class_students and class_students[0].class_id:
                    class_id = class_students[0].class_id
                    class_doc = frappe.get_doc("SIS Class", class_id)
                    student_class_name = class_doc.title or class_doc.name

                    # Get grade information
                    if class_doc.education_grade:
                        grade_doc = frappe.get_doc("SIS Education Grade", class_doc.education_grade)
                        student_grade_name = grade_doc.title_en or grade_doc.title_vn or grade_doc.name
            except Exception as e:
                frappe.logger().error(f"Parent portal - Error getting student grade/class: {str(e)}")

        # ⭐ DEBUG LOG
        frappe.logger().info(f"Parent portal - student_id={student_id}, student_grade_name={student_grade_name}, student_class_name={student_class_name}")

        # Process announcements to add additional information
        processed_announcements = []
        for announcement in announcements:
            # Get campus information
            campus_info = None
            if announcement.campus_id:
                try:
                    campus = frappe.get_doc("SIS Campus", announcement.campus_id)
                    campus_info = {
                        "name": campus.name,
                        "campus_name": campus.campus_name
                    }
                except:
                    pass

            # Get sender information
            sender_info = None
            if announcement.sent_by:
                try:
                    user = frappe.get_doc("User", announcement.sent_by)
                    sender_info = {
                        "email": user.email,
                        "full_name": user.full_name or user.email
                    }
                except:
                    pass

            # Process recipients to get relevant tags for current student
            relevant_tags = []
            
            # ⭐ QUAN TRỌNG: Check recipient_type ở level announcement trước
            # Nếu là announcement toàn trường (recipient_type == 'school'), luôn hiển thị
            announcement_is_school_wide = announcement.recipient_type == 'school'
            
            if announcement_is_school_wide:
                # Announcement toàn trường - luôn relevant với tất cả students
                relevant_tags.append({
                    "type": "school",
                    "name": "school",
                    "display_name": "Toàn trường",
                    "display_name_en": "All School"
                })
            
            # Xử lý recipients JSON (cho các loại khác hoặc bổ sung tags)
            if announcement.recipients:
                try:
                    if isinstance(announcement.recipients, str):
                        recipients = json.loads(announcement.recipients)
                    else:
                        recipients = announcement.recipients

                    if isinstance(recipients, list):
                        for recipient in recipients:
                            if isinstance(recipient, dict):
                                recipient_type = recipient.get('type')
                                # Support cả 'id' và 'name' field (backward compatibility)
                                recipient_id = recipient.get('id') or recipient.get('name', '')
                                recipient_display_name = recipient.get('display_name', recipient_id)

                                # Check if this recipient is relevant to current student
                                is_relevant = False
                                
                                # Kiểm tra nếu là announcement toàn trường (nhiều cách lưu trong JSON)
                                is_school_wide = (
                                    recipient_type == 'school' or 
                                    recipient_id == 'school' or
                                    (recipient_display_name and 'toàn trường' in recipient_display_name.lower()) or
                                    (recipient_display_name and 'all school' in recipient_display_name.lower())
                                )

                                # Nếu đã add tag school ở trên rồi, skip để tránh duplicate
                                if is_school_wide and announcement_is_school_wide:
                                    continue

                                if is_school_wide:
                                    # School-wide announcements are relevant to all students
                                    is_relevant = True
                                    recipient_type = 'school'  # Normalize type
                                elif recipient_type == 'stage':
                                    # Education Stage (Tiểu học, THCS, THPT) - check if student belongs to this stage
                                    try:
                                        # Get stage's grades, then check if student's grade is in those grades
                                        stage_grades = frappe.get_all(
                                            "SIS Education Grade",
                                            filters={"education_stage_id": recipient_id},
                                            fields=["name", "title_en", "title_vn"],
                                            pluck="name"
                                        )
                                        if stage_grades:
                                            # Get student's grade ID from class
                                            if student_id:
                                                class_students = frappe.get_all(
                                                    "SIS Class Student",
                                                    filters={"student_id": student_id},
                                                    fields=["class_id"],
                                                    order_by="creation desc",
                                                    limit=1
                                                )
                                                if class_students and class_students[0].class_id:
                                                    class_doc = frappe.get_doc("SIS Class", class_students[0].class_id)
                                                    student_grade_id = class_doc.education_grade
                                                    # Check if student's grade belongs to this stage
                                                    is_relevant = student_grade_id in stage_grades
                                                    frappe.logger().info(f"Parent portal - Stage check: stage={recipient_id}, student_grade={student_grade_id}, stage_grades={stage_grades}, is_relevant={is_relevant}")
                                    except Exception as e:
                                        frappe.logger().error(f"Parent portal - Error checking stage {recipient_id}: {str(e)}")
                                        is_relevant = False
                                elif recipient_type == 'grade' and student_grade_name:
                                    # For grade, resolve the grade name from the ID
                                    grade_name_from_db = recipient_id
                                    try:
                                        if recipient_id and recipient_id != 'school':
                                            grade_doc = frappe.get_doc("SIS Education Grade", recipient_id)
                                            grade_name_from_db = grade_doc.title_en or grade_doc.title_vn or recipient_id
                                    except:
                                        pass
                                    # Check if student's grade matches this recipient
                                    is_relevant = grade_name_from_db == student_grade_name or recipient_display_name == student_grade_name
                                    
                                elif recipient_type == 'class' and student_class_name:
                                    # For class, resolve the class name from the ID
                                    class_name_from_db = recipient_id
                                    try:
                                        if recipient_id and recipient_id != 'school':
                                            class_doc = frappe.get_doc("SIS Class", recipient_id)
                                            class_name_from_db = class_doc.title or recipient_id
                                    except:
                                        pass
                                    # Check if student's class matches this recipient
                                    is_relevant = class_name_from_db == student_class_name or recipient_display_name == student_class_name
                                    
                                elif recipient_type == 'student':
                                    # Check if student is specifically targeted
                                    is_relevant = recipient_id == student_id

                                if is_relevant:
                                    # Handle special case for school-wide announcements
                                    if recipient_type == 'school':
                                        display_name_vn = "Toàn trường"
                                        display_name_en = "All School"
                                    else:
                                        # For stage/grade/class/student, resolve display name from database
                                        display_name_vn = recipient_display_name or recipient_id
                                        display_name_en = recipient_display_name or recipient_id
                                        
                                        # Try to resolve from database if display_name is empty/null
                                        if recipient_type == 'stage' and (not recipient_display_name or recipient_display_name == recipient_id):
                                            # Education Stage (Tiểu Học, THCS, THPT)
                                            try:
                                                stage_doc = frappe.get_doc("SIS Education Stage", recipient_id)
                                                display_name_vn = stage_doc.title_vn or stage_doc.title_en or recipient_id
                                                display_name_en = stage_doc.title_en or stage_doc.title_vn or recipient_id
                                            except Exception:
                                                pass
                                        elif recipient_type == 'grade' and (not recipient_display_name or recipient_display_name == recipient_id):
                                            # Education Grade (Khối 1, Khối 2, etc.)
                                            try:
                                                grade_doc = frappe.get_doc("SIS Education Grade", recipient_id)
                                                display_name_vn = grade_doc.title_vn or grade_doc.title_en or recipient_id
                                                display_name_en = grade_doc.title_en or display_name_vn or recipient_id
                                            except Exception:
                                                pass
                                        elif recipient_type == 'class' and (not recipient_display_name or recipient_display_name == recipient_id):
                                            try:
                                                class_doc = frappe.get_doc("SIS Class", recipient_id)
                                                display_name_vn = class_doc.title or recipient_id
                                                display_name_en = class_doc.title or recipient_id
                                            except:
                                                pass

                                    relevant_tags.append({
                                        "type": recipient_type,
                                        "name": recipient_id,
                                        "display_name": display_name_vn,
                                        "display_name_en": display_name_en
                                    })
                except Exception as e:
                    frappe.logger().error(f"Parent portal - Error processing recipients for announcement {announcement.name}: {str(e)}")

            # ⭐ FILTER: If student_id is provided, skip announcements with no relevant tags
            if student_id and not relevant_tags:
                frappe.logger().debug(f"Parent portal - Skipping announcement {announcement.name} (no match for student {student_id})")
                continue

            # Note: Always return announcement with relevant_tags (even if empty when no student_id provided)
            
            # ⭐ DEBUG LOG - per announcement
            frappe.logger().info(f"Parent portal - Announcement {announcement.name}: recipients={json.dumps(announcement.recipients)}, relevant_tags_count={len(relevant_tags)}")
            
            processed_announcement = {
                "name": announcement.name,
                "campus_id": announcement.campus_id,
                "campus": campus_info,
                "title_en": announcement.title_en,
                "title_vn": announcement.title_vn,
                "content_en": announcement.content_en,
                "content_vn": announcement.content_vn,
                "status": announcement.status,
                "sent_at": announcement.sent_at,
                "sent_by": announcement.sent_by,
                "sender": sender_info,
                "recipient_tags": relevant_tags,  # Relevant tags for current student
                "created_at": announcement.created_at,
                "created_by": announcement.created_by,
                "updated_at": announcement.updated_at,
                "updated_by": announcement.updated_by,
                "published_at": announcement.sent_at  # Use sent_at as published_at for consistency with frontend
            }

            processed_announcements.append(processed_announcement)

        # Calculate total pages
        total_pages = (total_count + limit - 1) // limit  # Ceiling division

        frappe.logger().info(f"Parent portal - Retrieved {len(processed_announcements)} announcements out of {total_count} total")

        # ⭐ Build debug info for all announcements
        announcements_debug = []
        for a in announcements:
            tags = []
            if a.recipients:
                try:
                    if isinstance(a.recipients, str):
                        recipients = json.loads(a.recipients)
                    else:
                        recipients = a.recipients
                    tags = [f"{r.get('type')}:{r.get('display_name')}" for r in recipients if isinstance(r, dict)]
                except:
                    pass
            announcements_debug.append({
                "name": a.name,
                "recipients_raw": tags,
                "recipients_full": recipients if isinstance(recipients, list) else []
            })

        return list_response(
            data=processed_announcements,
            meta={
                "pagination": {
                    "page": page,
                    "limit": limit,
                    "total": total_count,
                    "pages": total_pages
                },
                "debug": {
                    "student_id": student_id,
                    "student_grade_name": student_grade_name,
                    "student_class_name": student_class_name,
                    "processed_count": len(processed_announcements),
                    "all_announcements": announcements_debug
                }
            }
        )

    except Exception as e:
        frappe.logger().error(f"Parent portal - Error in get_announcements: {str(e)}")
        return error_response(
            message="An error occurred while fetching announcements",
            code="INTERNAL_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def get_announcement_detail(announcement_id):
    """Get detailed information for a specific announcement"""
    try:
        if not announcement_id:
            return validation_error_response("Announcement ID is required")

        # Check if SIS Announcement doctype exists
        if not frappe.db.exists("DocType", "SIS Announcement"):
            return error_response(
                message="Announcement system not available",
                code="DOCTYPE_NOT_FOUND"
            )

        # Get announcement
        try:
            announcement = frappe.get_doc("SIS Announcement", announcement_id)
        except frappe.DoesNotExistError:
            return not_found_response("Announcement not found")

        # Check if announcement is sent (published)
        if announcement.status != "sent":
            return not_found_response("Announcement not found")

        # Get campus information
        campus_info = None
        if announcement.campus_id:
            try:
                campus = frappe.get_doc("SIS Campus", announcement.campus_id)
                campus_info = {
                    "name": campus.name,
                    "campus_name": campus.campus_name
                }
            except:
                pass

        # Get sender information
        sender_info = None
        if announcement.sent_by:
            try:
                user = frappe.get_doc("User", announcement.sent_by)
                sender_info = {
                    "email": user.email,
                    "full_name": user.full_name or user.email
                }
            except:
                pass

        # Process recipients for detail view (same logic as list view)
        relevant_tags = []
        
        # ⭐ QUAN TRỌNG: Check recipient_type ở level announcement trước
        announcement_is_school_wide = announcement.recipient_type == 'school'
        
        if announcement_is_school_wide:
            relevant_tags.append({
                "type": "school",
                "name": "school",
                "display_name": "Toàn trường",
                "display_name_en": "All School"
            })
        
        if announcement.recipients:
            try:
                if isinstance(announcement.recipients, str):
                    recipients = json.loads(announcement.recipients)
                else:
                    recipients = announcement.recipients

                if isinstance(recipients, list):
                    # For detail view, show all recipients since it's a specific announcement
                    for recipient in recipients:
                        if isinstance(recipient, dict):
                            recipient_type = recipient.get('type')
                            # Support cả 'id' và 'name' field (backward compatibility)
                            recipient_name = recipient.get('id') or recipient.get('name', '')
                            recipient_display_name = recipient.get('display_name', recipient_name)

                            # Skip nếu đã có tag school ở trên
                            is_school_wide = (
                                recipient_type == 'school' or 
                                recipient_name == 'school' or
                                (recipient_display_name and 'toàn trường' in recipient_display_name.lower())
                            )
                            if is_school_wide and announcement_is_school_wide:
                                continue

                            # Handle special case for school-wide announcements
                            if recipient_type == 'school' or is_school_wide:
                                display_name_vn = "Toàn trường"
                                display_name_en = "All School"
                                recipient_type = 'school'
                            else:
                                display_name_vn = recipient_display_name or recipient_name
                                display_name_en = recipient_display_name or recipient_name
                                
                                # Try to resolve display name from database
                                if recipient_type == 'stage' and (not recipient_display_name or recipient_display_name == recipient_name):
                                    try:
                                        stage_doc = frappe.get_doc("SIS Education Stage", recipient_name)
                                        display_name_vn = stage_doc.title_vn or stage_doc.title_en or recipient_name
                                        display_name_en = stage_doc.title_en or stage_doc.title_vn or recipient_name
                                    except:
                                        pass
                                elif recipient_type == 'grade' and (not recipient_display_name or recipient_display_name == recipient_name):
                                    try:
                                        grade_doc = frappe.get_doc("SIS Education Grade", recipient_name)
                                        display_name_vn = grade_doc.title_vn or grade_doc.title_en or recipient_name
                                        display_name_en = grade_doc.title_en or display_name_vn or recipient_name
                                    except:
                                        pass
                                elif recipient_type == 'class' and (not recipient_display_name or recipient_display_name == recipient_name):
                                    try:
                                        class_doc = frappe.get_doc("SIS Class", recipient_name)
                                        display_name_vn = class_doc.title or recipient_name
                                        display_name_en = class_doc.title or recipient_name
                                    except:
                                        pass

                            relevant_tags.append({
                                "type": recipient_type,
                                "name": recipient_name,
                                "display_name": display_name_vn,
                                "display_name_en": display_name_en
                            })
            except Exception as e:
                frappe.logger().error(f"Parent portal - Error processing recipients for announcement detail {announcement.name}: {str(e)}")

        processed_announcement = {
            "name": announcement.name,
            "campus_id": announcement.campus_id,
            "campus": campus_info,
            "title_en": announcement.title_en,
            "title_vn": announcement.title_vn,
            "content_en": announcement.content_en,
            "content_vn": announcement.content_vn,
            "status": announcement.status,
            "sent_at": announcement.sent_at,
            "sent_by": announcement.sent_by,
            "sender": sender_info,
            "recipient_tags": relevant_tags,  # All tags for this announcement
            "sent_count": announcement.sent_count,
            "received_count": announcement.received_count,
            "created_at": announcement.created_at,
            "created_by": announcement.created_by,
            "updated_at": announcement.updated_at,
            "updated_by": announcement.updated_by,
            "published_at": announcement.sent_at
        }

        return single_item_response(processed_announcement)

    except Exception as e:
        frappe.logger().error(f"Parent portal - Error in get_announcement_detail: {str(e)}")
        return error_response(
            message="An error occurred while fetching announcement detail",
            code="INTERNAL_ERROR"
        )
