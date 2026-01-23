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

        # Lấy tất cả students của phụ huynh đang login
        # Thay vì filter theo 1 student cụ thể, ta sẽ check với tất cả students
        user_email = frappe.session.user
        all_student_ids = []
        all_student_info = {}  # student_id -> {grade_id, class_id, stage_id}
        
        try:
            # Tìm guardian từ user email
            # Format: {guardian_id}@parent.wellspring.edu.vn
            guardian_id = user_email.split('@')[0] if '@parent.wellspring.edu.vn' in user_email else None
            
            if guardian_id:
                # Tìm guardian document
                guardians = frappe.get_all("CRM Guardian", filters={"guardian_id": guardian_id}, fields=["name"])
                if guardians:
                    guardian_name = guardians[0].name
                    
                    # Lấy tất cả students từ relationships
                    relationships = frappe.db.sql("""
                        SELECT DISTINCT fr.student
                        FROM `tabCRM Family Relationship` fr
                        INNER JOIN `tabCRM Family` f ON fr.parent = f.name
                        WHERE fr.guardian = %(guardian)s
                            AND fr.student IS NOT NULL
                            AND f.docstatus < 2
                            AND fr.parentfield = 'relationships'
                    """, {"guardian": guardian_name}, as_dict=True)
                    
                    for rel in relationships:
                        student_id_from_rel = rel.get("student")
                        if student_id_from_rel:
                            all_student_ids.append(student_id_from_rel)
                            
                            # Lấy thông tin class/grade/stage của student
                            class_students = frappe.get_all(
                                "SIS Class Student",
                                filters={"student_id": student_id_from_rel},
                                fields=["class_id"],
                                order_by="creation desc",
                                limit=1
                            )
                            
                            if class_students and class_students[0].class_id:
                                class_id = class_students[0].class_id
                                class_doc = frappe.get_doc("SIS Class", class_id)
                                grade_id = class_doc.education_grade
                                stage_id = None
                                
                                if grade_id:
                                    try:
                                        grade_doc = frappe.get_doc("SIS Education Grade", grade_id)
                                        stage_id = grade_doc.education_stage_id
                                    except:
                                        pass
                                
                                all_student_info[student_id_from_rel] = {
                                    "class_id": class_id,
                                    "grade_id": grade_id,
                                    "stage_id": stage_id
                                }
            
            frappe.logger().info(f"Parent portal - User {user_email} has {len(all_student_ids)} students: {all_student_ids}")
        except Exception as e:
            frappe.logger().error(f"Parent portal - Error getting user's students: {str(e)}")

        # ⭐ DEBUG LOG
        frappe.logger().info(f"Parent portal - all_student_ids={all_student_ids}, all_student_info={all_student_info}")

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

            # ===== LOGIC MỚI: Hiển thị TẤT CẢ recipient_tags, filter dựa trên TẤT CẢ students của phụ huynh =====
            recipient_tags = []
            is_announcement_relevant = False
            
            # Check nếu là announcement toàn trường
            announcement_is_school_wide = announcement.recipient_type == 'school'
            if announcement_is_school_wide:
                is_announcement_relevant = True
                recipient_tags.append({
                    "type": "school",
                    "name": "school",
                    "display_name": "Toàn trường",
                    "display_name_en": "All School"
                })
            
            # Xử lý recipients JSON
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
                                recipient_id = recipient.get('id') or recipient.get('name', '')
                                recipient_display_name = recipient.get('display_name', recipient_id)
                                
                                # Skip nếu đã có tag school
                                is_school_wide = (
                                    recipient_type == 'school' or 
                                    recipient_id == 'school' or
                                    (recipient_display_name and 'toàn trường' in recipient_display_name.lower())
                                )
                                if is_school_wide:
                                    if not announcement_is_school_wide:
                                        is_announcement_relevant = True
                                        recipient_tags.append({
                                            "type": "school",
                                            "name": "school",
                                            "display_name": "Toàn trường",
                                            "display_name_en": "All School"
                                        })
                                    continue
                                
                                # Resolve display name từ database
                                display_name_vn = recipient_display_name or recipient_id
                                display_name_en = recipient_display_name or recipient_id
                                
                                if recipient_type == 'stage':
                                    try:
                                        stage_doc = frappe.get_doc("SIS Education Stage", recipient_id)
                                        display_name_vn = stage_doc.title_vn or stage_doc.title_en or recipient_id
                                        display_name_en = stage_doc.title_en or stage_doc.title_vn or recipient_id
                                        
                                        # Check xem bất kỳ student nào của phụ huynh có thuộc stage này không
                                        for s_id, s_info in all_student_info.items():
                                            if s_info.get("stage_id") == recipient_id:
                                                is_announcement_relevant = True
                                                break
                                    except:
                                        pass
                                        
                                elif recipient_type == 'grade':
                                    try:
                                        grade_doc = frappe.get_doc("SIS Education Grade", recipient_id)
                                        display_name_vn = grade_doc.title_vn or grade_doc.title_en or recipient_id
                                        display_name_en = grade_doc.title_en or display_name_vn or recipient_id
                                        
                                        # Check xem bất kỳ student nào của phụ huynh có thuộc grade này không
                                        for s_id, s_info in all_student_info.items():
                                            if s_info.get("grade_id") == recipient_id:
                                                is_announcement_relevant = True
                                                break
                                    except:
                                        pass
                                        
                                elif recipient_type == 'class':
                                    try:
                                        class_doc = frappe.get_doc("SIS Class", recipient_id)
                                        display_name_vn = class_doc.title or recipient_id
                                        display_name_en = class_doc.title or recipient_id
                                        
                                        # Check xem bất kỳ student nào của phụ huynh có thuộc class này không
                                        for s_id, s_info in all_student_info.items():
                                            if s_info.get("class_id") == recipient_id:
                                                is_announcement_relevant = True
                                                break
                                    except:
                                        pass
                                        
                                elif recipient_type == 'student':
                                    # Check xem student có trong danh sách students của phụ huynh không
                                    if recipient_id in all_student_ids:
                                        is_announcement_relevant = True
                                    # Resolve student name
                                    try:
                                        student_doc = frappe.get_doc("CRM Student", recipient_id)
                                        display_name_vn = student_doc.full_name or recipient_id
                                        display_name_en = student_doc.full_name or recipient_id
                                    except:
                                        pass
                                
                                # Thêm tag vào danh sách (hiển thị TẤT CẢ recipients, không chỉ relevant)
                                recipient_tags.append({
                                    "type": recipient_type,
                                    "name": recipient_id,
                                    "display_name": display_name_vn,
                                    "display_name_en": display_name_en
                                })
                                
                except Exception as e:
                    frappe.logger().error(f"Parent portal - Error processing recipients for announcement {announcement.name}: {str(e)}")

            # ⭐ FILTER: Skip announcement nếu không liên quan đến bất kỳ student nào của phụ huynh
            if all_student_ids and not is_announcement_relevant:
                frappe.logger().debug(f"Parent portal - Skipping announcement {announcement.name} (no match for any student of user)")
                continue

            # ⭐ DEBUG LOG - per announcement
            frappe.logger().info(f"Parent portal - Announcement {announcement.name}: recipients={json.dumps(announcement.recipients)}, recipient_tags_count={len(recipient_tags)}")
            
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
                "recipient_tags": recipient_tags,  # Tất cả recipients của announcement
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
                    "user_email": user_email,
                    "all_student_ids": all_student_ids,
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
