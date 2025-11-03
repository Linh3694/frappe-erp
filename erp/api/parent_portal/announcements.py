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
                "created_at",
                "created_by",
                "updated_at",
                "updated_by"
            ],
            order_by="sent_at desc",  # Most recent first
            limit=limit,
            start=offset
        )

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

        return list_response(
            data=processed_announcements,
            meta={
                "pagination": {
                    "page": page,
                    "limit": limit,
                    "total": total_count,
                    "pages": total_pages
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
