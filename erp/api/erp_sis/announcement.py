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
    not_found_response,
    forbidden_response,
    paginated_response
)


def _get_user_fullname(user_email: str) -> str:
    """Get user's full name from email"""
    if not user_email:
        return ""
    try:
        user = frappe.get_doc("User", user_email)
        return user.full_name or user_email
    except Exception:
        return user_email


@frappe.whitelist(allow_guest=False)
def get_announcements():
    """Get announcements with filtering"""
    try:
        data = frappe.local.form_dict

        # Get current user's campus information
        campus_id = get_current_campus_from_context()
        frappe.logger().info(f"Current campus_id: {campus_id}")

        if not campus_id:
            # Fallback to default if no campus found
            campus_id = "campus-1"
            frappe.logger().warning(f"No campus found for user {frappe.session.user}, using default: {campus_id}")

        # Check if SIS Announcement doctype exists
        if not frappe.db.exists("DocType", "SIS Announcement"):
            frappe.logger().error("SIS Announcement DocType does not exist")
            return error_response(
                message="SIS Announcement DocType not found",
                code="DOCTYPE_NOT_FOUND"
            )

        # Build filters
        filters = {"campus_id": campus_id}

        # Status filter
        status = data.get("status")
        if status:
            filters["status"] = status

        # Pagination
        page = int(data.get("page", 1))
        limit = int(data.get("limit", 20))
        offset = (page - 1) * limit

        frappe.logger().info(f"Using filters: {filters}")

        # Clear cache to ensure fresh data
        frappe.clear_cache(doctype="SIS Announcement")

        # Get announcements with pagination
        announcements = frappe.get_all(
            "SIS Announcement",
            fields=[
                "name",
                "title_en",
                "title_vn",
                "content_en",
                "content_vn",
                "recipients",
                "recipient_type",
                "status",
                "sent_at",
                "sent_by",
                "campus_id",
                "creation",
                "modified",
                "sent_count",
                "received_count"
            ],
            filters=filters,
            order_by="sent_at desc, modified desc" if status == "sent" else "modified desc",
            limit_page_length=limit,
            limit_start=offset,
            ignore_permissions=True
        )

        # Get total count for pagination
        total_count = frappe.db.count("SIS Announcement", filters=filters)

        # Enrich announcements with recipient information
        for announcement in announcements:
            # Parse recipients JSON if it's a string
            if announcement.get("recipients"):
                recipients_str = announcement["recipients"]
                if isinstance(recipients_str, str):
                    try:
                        announcement["recipients"] = json.loads(recipients_str)
                    except (json.JSONDecodeError, TypeError):
                        announcement["recipients"] = []
                        frappe.logger().warning(f"Failed to parse recipients for {announcement['name']}")
            else:
                announcement["recipients"] = []
            
            # Set default counts if not set
            if not announcement.get("sent_count"):
                announcement["sent_count"] = 0
            if not announcement.get("received_count"):
                announcement["received_count"] = 0

            # Add sent_by_fullname
            if announcement.get("sent_by"):
                announcement["sent_by_fullname"] = _get_user_fullname(announcement["sent_by"])
            else:
                announcement["sent_by_fullname"] = None

            # For the list view, create a title field (use Vietnamese if available)
            announcement["title"] = announcement.get("title_vn") or announcement.get("title_en", "")
            
            # For the list view, create a content field (truncate to 100 chars)
            content = announcement.get("content_vn") or announcement.get("content_en", "")
            # Remove markdown syntax
            content = frappe.utils.strip_html_tags(content)
            announcement["content"] = content[:100] + "..." if len(content) > 100 else content

        frappe.logger().info(f"Successfully retrieved {len(announcements)} announcements")

        # Return paginated response if there are more pages, otherwise return list response
        if total_count > limit:
            return paginated_response(
                data=announcements,
                current_page=page,
                total_count=total_count,
                per_page=limit,
                message="Announcements fetched successfully"
            )
        else:
            return list_response(
                data=announcements,
                message="Announcements fetched successfully"
            )

    except Exception as e:
        frappe.logger().error(f"Error fetching announcements: {str(e)}")
        return error_response(
            message=f"Failed to fetch announcements: {str(e)}",
            code="FETCH_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def get_announcement():
    """Get a single announcement by ID"""
    try:
        data = frappe.local.form_dict
        
        # Try from request.form (for POST form-urlencoded)
        announcement_id = data.get("announcement_id") or frappe.request.form.get("announcement_id")
        
        # Try from request.args (for GET query params)
        if not announcement_id:
            announcement_id = frappe.request.args.get("announcement_id")
        
        # Try from JSON body
        if not announcement_id:
            try:
                json_data = frappe.request.get_json(silent=True)
                if json_data:
                    announcement_id = json_data.get("announcement_id")
            except:
                pass
        
        if not announcement_id:
            return validation_error_response(
                f"Announcement ID is required",
                {"announcement_id": ["Announcement ID is required"]}
            )

        # Get current user's campus information
        campus_id = get_current_campus_from_context()

        # Get the announcement
        announcement = frappe.get_doc("SIS Announcement", announcement_id)

        # Check if user has access to this campus
        if campus_id and announcement.campus_id != campus_id:
            return forbidden_response("You don't have access to this announcement")

        # Parse recipients
        recipients = []
        if announcement.recipients:
            recipients_str = announcement.recipients
            if isinstance(recipients_str, str):
                try:
                    recipients = json.loads(recipients_str)
                except (json.JSONDecodeError, TypeError):
                    recipients = []

        announcement_data = {
            "name": announcement.name,
            "title_en": announcement.title_en,
            "title_vn": announcement.title_vn,
            "content_en": announcement.content_en,
            "content_vn": announcement.content_vn,
            "recipients": recipients,
            "recipient_type": getattr(announcement, 'recipient_type', 'specific'),
            "status": announcement.status,
            "sent_at": announcement.sent_at,
            "sent_by": announcement.sent_by,
            "sent_by_fullname": _get_user_fullname(announcement.sent_by),
            "campus_id": announcement.campus_id,
            "created_at": announcement.creation,
            "created_by": announcement.owner,
            "updated_at": announcement.modified,
            "updated_by": getattr(announcement, 'modified_by', '')
        }

        return single_item_response(
            data=announcement_data,
            message="Announcement fetched successfully"
        )

    except frappe.DoesNotExistError:
        return not_found_response("Announcement not found")
    except Exception as e:
        frappe.logger().error(f"Error fetching announcement: {str(e)}")
        return error_response(
            message=f"Failed to fetch announcement: {str(e)}",
            code="FETCH_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def create_announcement():
    """Create a new announcement"""
    try:
        # Get data from request
        data = frappe.local.form_dict
        
        # Try to parse JSON from request body if needed
        if not data or not data.get('title_en'):
            try:
                if frappe.request.data:
                    data = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
                    frappe.logger().info(f"Parsed JSON data: {list(data.keys())}")
            except Exception as e:
                frappe.logger().error(f"Failed to parse JSON from request: {str(e)}")

        frappe.logger().info(f"Create announcement data: {list(data.keys())}")

        # Get current user's campus information
        campus_id = get_current_campus_from_context()
        if not campus_id:
            campus_id = "campus-1"

        # Override campus_id to ensure user can't create for other campuses
        data['campus_id'] = campus_id

        # Validate required fields
        title_en = str(data.get("title_en", "")).strip()
        title_vn = str(data.get("title_vn", "")).strip()
        content_en = str(data.get("content_en", "")).strip()
        content_vn = str(data.get("content_vn", "")).strip()
        
        frappe.logger().info(f"Validation: title_en='{title_en}', title_vn='{title_vn}'")

        if not title_en or not title_vn:
            return validation_error_response(
                "Both English and Vietnamese titles are required",
                {"title": ["Both English and Vietnamese titles are required"]}
            )

        if not content_en or not content_vn:
            return validation_error_response(
                "Both English and Vietnamese content are required",
                {"content": ["Both English and Vietnamese content are required"]}
            )

        # Get recipients
        recipients_data = data.get("recipients", [])
        if isinstance(recipients_data, str):
            try:
                recipients_data = json.loads(recipients_data)
            except json.JSONDecodeError:
                recipients_data = []

        # Validate recipients
        if not recipients_data or len(recipients_data) == 0:
            return validation_error_response(
                "At least one recipient is required",
                {"recipients": ["At least one recipient is required"]}
            )

        # Create the announcement
        announcement = frappe.get_doc({
            "doctype": "SIS Announcement",
            "campus_id": campus_id,
            "title_en": title_en,
            "title_vn": title_vn,
            "content_en": content_en,
            "content_vn": content_vn,
            "recipients": json.dumps(recipients_data),
            "recipient_type": data.get("recipient_type", "specific"),
            "status": data.get("status", "draft"),
            "sent_by": frappe.session.user  # Always set sent_by to current user
        })

        announcement.insert()

        # Get the created announcement data
        created_announcement = frappe.get_doc("SIS Announcement", announcement.name)

        # If status is "sent", send notifications immediately and set sent_at
        if created_announcement.status == "sent":
            try:
                from erp.utils.notification_handler import send_bulk_parent_notifications
                
                notification_result = send_bulk_parent_notifications(
                    recipient_type="announcement",
                    recipients_data={
                        "student_ids": [],
                        "recipients": recipients_data,
                        "announcement_id": created_announcement.name
                    },
                    title="Thông báo",
                    body=created_announcement.title_vn or created_announcement.title_en or "Thông báo mới",
                    icon="/icon.png",
                    data={
                        "type": "announcement",
                        "announcement_id": created_announcement.name,
                        "title_en": created_announcement.title_en,
                        "title_vn": created_announcement.title_vn,
                        "url": f"/announcement/{created_announcement.name}"
                    }
                )
                
                # Update with send info
                created_announcement.sent_at = frappe.utils.now()
                created_announcement.sent_count = notification_result.get("total_parents", 0)
                created_announcement.save()
                
                frappe.logger().info(f"✅ Announcement {created_announcement.name} sent to {notification_result.get('total_parents', 0)} parents on creation")
            except Exception as e:
                frappe.logger().error(f"❌ Error sending notifications on announcement creation: {str(e)}")
                # Don't fail the creation, just log the error

        # Parse recipients
        recipients = []
        if created_announcement.recipients:
            try:
                recipients = json.loads(created_announcement.recipients)
            except (json.JSONDecodeError, TypeError):
                recipients = []

        announcement_data = {
            "name": created_announcement.name,
            "title_en": created_announcement.title_en,
            "title_vn": created_announcement.title_vn,
            "content_en": created_announcement.content_en,
            "content_vn": created_announcement.content_vn,
            "recipients": recipients,
            "recipient_type": getattr(created_announcement, 'recipient_type', 'specific'),
            "status": created_announcement.status,
            "sent_at": created_announcement.sent_at,
            "sent_by": created_announcement.sent_by,
            "sent_by_fullname": _get_user_fullname(created_announcement.sent_by),
            "campus_id": created_announcement.campus_id,
            "created_at": created_announcement.creation,
            "created_by": created_announcement.owner,
            "updated_at": created_announcement.modified,
            "updated_by": getattr(created_announcement, 'modified_by', '')
        }

        return single_item_response(
            data=announcement_data,
            message="Announcement created successfully"
        )

    except frappe.DuplicateEntryError:
        return validation_error_response(
            "An announcement with this title already exists",
            {"title": ["An announcement with this title already exists"]}
        )
    except Exception as e:
        frappe.logger().error(f"Error creating announcement: {str(e)}")
        return error_response(
            message=f"Failed to create announcement: {str(e)}",
            code="CREATE_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def update_announcement():
    """Update an existing announcement"""
    try:
        # Get data from request
        data = frappe.local.form_dict
        
        # Try to parse JSON from request body if needed
        if not data or not data.get('announcement_id'):
            try:
                if frappe.request.data:
                    data = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
                    frappe.logger().info(f"Parsed JSON data: {list(data.keys())}")
            except Exception as e:
                frappe.logger().error(f"Failed to parse JSON from request: {str(e)}")

        announcement_id = data.get("announcement_id")

        if not announcement_id:
            return validation_error_response(
                "Announcement ID is required",
                {"announcement_id": ["Announcement ID is required"]}
            )

        # Get the announcement
        announcement = frappe.get_doc("SIS Announcement", announcement_id)

        # Check if user has access to this campus
        campus_id = get_current_campus_from_context()
        if campus_id and announcement.campus_id != campus_id:
            return forbidden_response("You don't have access to this announcement")

        # Don't allow updating sent announcements
        if announcement.status == "sent":
            return validation_error_response(
                "Cannot update a sent announcement",
                {"status": ["Cannot update a sent announcement"]}
            )

        # Validate required fields for update
        title_en = str(data.get("title_en", "")).strip()
        title_vn = str(data.get("title_vn", "")).strip()
        content_en = str(data.get("content_en", "")).strip()
        content_vn = str(data.get("content_vn", "")).strip()

        if not title_en or not title_vn:
            return validation_error_response(
                "Both English and Vietnamese titles are required",
                {"title": ["Both English and Vietnamese titles are required"]}
            )

        if not content_en or not content_vn:
            return validation_error_response(
                "Both English and Vietnamese content are required",
                {"content": ["Both English and Vietnamese content are required"]}
            )

        # Update fields
        if "title_en" in data:
            announcement.title_en = data["title_en"]
        if "title_vn" in data:
            announcement.title_vn = data["title_vn"]
        if "content_en" in data:
            announcement.content_en = data["content_en"]
        if "content_vn" in data:
            announcement.content_vn = data["content_vn"]

        # Handle recipients update
        recipients_data = data.get("recipients")
        if recipients_data is not None:
            if isinstance(recipients_data, str):
                try:
                    recipients_data = json.loads(recipients_data)
                except json.JSONDecodeError:
                    recipients_data = []

            if not recipients_data or len(recipients_data) == 0:
                return validation_error_response(
                    "At least one recipient is required",
                    {"recipients": ["At least one recipient is required"]}
                )

            announcement.recipients = json.dumps(recipients_data)

        if "recipient_type" in data:
            announcement.recipient_type = data["recipient_type"]

        announcement.save()

        # Get updated announcement data
        updated_announcement = frappe.get_doc("SIS Announcement", announcement.name)

        # Parse recipients
        recipients = []
        if updated_announcement.recipients:
            try:
                recipients = json.loads(updated_announcement.recipients)
            except (json.JSONDecodeError, TypeError):
                recipients = []

        announcement_data = {
            "name": updated_announcement.name,
            "title_en": updated_announcement.title_en,
            "title_vn": updated_announcement.title_vn,
            "content_en": updated_announcement.content_en,
            "content_vn": updated_announcement.content_vn,
            "recipients": recipients,
            "recipient_type": getattr(updated_announcement, 'recipient_type', 'specific'),
            "status": updated_announcement.status,
            "sent_at": updated_announcement.sent_at,
            "sent_by": updated_announcement.sent_by,
            "sent_by_fullname": _get_user_fullname(updated_announcement.sent_by),
            "campus_id": updated_announcement.campus_id,
            "created_at": updated_announcement.creation,
            "created_by": updated_announcement.owner,
            "updated_at": updated_announcement.modified,
            "updated_by": getattr(updated_announcement, 'modified_by', '')
        }

        return single_item_response(
            data=announcement_data,
            message="Announcement updated successfully"
        )

    except frappe.DoesNotExistError:
        return not_found_response("Announcement not found")
    except Exception as e:
        frappe.logger().error(f"Error updating announcement: {str(e)}")
        return error_response(
            message=f"Failed to update announcement: {str(e)}",
            code="UPDATE_ERROR"
        )


@frappe.whitelist(allow_guest=False, methods=['GET', 'POST'])
def delete_announcement():
    """Delete an announcement"""
    logs = []

    try:
        logs.append(f"DELETE API CALLED - User: {frappe.session.user}")
        logs.append(f"Request method: {frappe.request.method}")

        data = frappe.local.form_dict
        logs.append(f"form_dict keys: {list(data.keys())}")

        announcement_id = data.get("announcement_id")
        logs.append(f"announcement_id from form_dict: '{announcement_id}'")

        # Try from request.args (for GET query params)
        if not announcement_id:
            announcement_id = frappe.request.args.get("announcement_id")
            logs.append(f"announcement_id from query args: '{announcement_id}'")

        if not announcement_id:
            logs.append("ERROR: Announcement ID is required")
            return validation_error_response(
                "Announcement ID is required",
                {"announcement_id": ["Announcement ID is required"]}
            )

        logs.append(f"FINAL announcement_id: '{announcement_id}'")

        # Verify announcement exists BEFORE deletion
        try:
            announcement_check = frappe.get_doc("SIS Announcement", announcement_id)
            logs.append(f"Announcement exists: {announcement_check.name}, campus: {announcement_check.campus_id}")
        except frappe.DoesNotExistError:
            logs.append(f"ERROR: Announcement {announcement_id} does not exist before deletion")
            return error_response(
                message="Announcement not found",
                code="NOT_FOUND",
                logs=logs
            )

        # Check if user has access to this campus
        campus_id = get_current_campus_from_context()
        logs.append(f"User campus: '{campus_id}', Announcement campus: '{announcement_check.campus_id}'")

        if campus_id and announcement_check.campus_id != campus_id:
            logs.append("ERROR: Campus access denied")
            return error_response(
                message="You don't have access to this announcement",
                code="FORBIDDEN",
                logs=logs
            )

        logs.append("Access granted - proceeding with deletion")

        # Get fresh announcement instance for deletion
        announcement = frappe.get_doc("SIS Announcement", announcement_id)

        # Delete using frappe.delete_doc
        try:
            logs.append("Calling frappe.delete_doc...")
            frappe.delete_doc("SIS Announcement", announcement_id, ignore_permissions=True)
            frappe.db.commit()  # Ensure the deletion is committed to database
            logs.append("frappe.delete_doc completed successfully")

            # IMMEDIATE VERIFICATION - check if still exists using different methods
            try:
                # Method 1: frappe.db.exists
                still_exists_db = frappe.db.exists("SIS Announcement", announcement_id)
                logs.append(f"Verification 1 - frappe.db.exists: {still_exists_db}")

                # Method 2: Direct SQL query
                direct_sql_result = frappe.db.sql("SELECT name FROM `tabSIS Announcement` WHERE name = %s", announcement_id, as_dict=True)
                logs.append(f"Verification 2 - Direct SQL result: {direct_sql_result}")

                # Method 3: frappe.get_all
                get_all_result = frappe.get_all("SIS Announcement", filters={"name": announcement_id}, fields=["name"])
                logs.append(f"Verification 3 - frappe.get_all result: {get_all_result}")

                if still_exists_db or direct_sql_result or get_all_result:
                    logs.append("ERROR: Announcement still exists in database after delete!")
                    logs.append(f"Details - db.exists: {still_exists_db}, sql: {direct_sql_result}, get_all: {get_all_result}")
                    return error_response(
                        message="Announcement deletion failed - still exists in database",
                        code="DELETE_ERROR",
                        logs=logs
                    )
                else:
                    logs.append("SUCCESS: Announcement confirmed deleted from all verification methods")

            except Exception as verify_error:
                logs.append(f"Verification check error: {str(verify_error)}")
                import traceback
                logs.append(f"Verification traceback: {traceback.format_exc()}")

            # Clear frappe cache to ensure fresh data for subsequent queries
            frappe.clear_cache(doctype="SIS Announcement")
            logs.append("Frappe cache cleared for SIS Announcement")

            logs.append("DELETION COMPLETED SUCCESSFULLY")
            return success_response(
                message="Announcement deleted successfully",
                logs=logs
            )

        except Exception as delete_error:
            logs.append(f"DELETE OPERATION FAILED: {str(delete_error)}")
            frappe.logger().error(f"Delete operation failed: {str(delete_error)}")
            import traceback
            logs.append(f"Delete traceback: {traceback.format_exc()}")
            return error_response(
                message=f"Failed to delete announcement: {str(delete_error)}",
                code="DELETE_ERROR",
                logs=logs
            )

    except Exception as initial_error:
        logs.append(f"Initial setup error: {str(initial_error)}")
        import traceback
        logs.append(f"Initial traceback: {traceback.format_exc()}")
        return error_response(
            message=f"Failed to initialize delete operation: {str(initial_error)}",
            code="INIT_ERROR",
            logs=logs
        )


@frappe.whitelist(allow_guest=False, methods=['GET', 'POST'])
def send_announcement():
    """Send a draft announcement"""
    try:
        data = frappe.local.form_dict
        announcement_id = data.get("announcement_id")

        if not announcement_id:
            return validation_error_response(
                "Announcement ID is required",
                {"announcement_id": ["Announcement ID is required"]}
            )

        # Get the announcement
        announcement = frappe.get_doc("SIS Announcement", announcement_id)

        # Check if user has access to this campus
        campus_id = get_current_campus_from_context()
        if campus_id and announcement.campus_id != campus_id:
            return forbidden_response("You don't have access to this announcement")

        # Only allow sending draft announcements
        if announcement.status != "draft":
            return validation_error_response(
                "Only draft announcements can be sent",
                {"status": ["Only draft announcements can be sent"]}
            )

        # Parse recipients
        recipients = []
        if announcement.recipients:
            try:
                recipients = json.loads(announcement.recipients)
            except (json.JSONDecodeError, TypeError):
                recipients = []

        if not recipients:
            return validation_error_response(
                "No recipients to send to",
                {"recipients": ["No recipients to send to"]}
            )

        # Use unified notification handler to send notifications
        from erp.utils.notification_handler import send_bulk_parent_notifications

        try:
            notification_result = send_bulk_parent_notifications(
                recipient_type="announcement",
                recipients_data={
                    "student_ids": [],  # Will be resolved in handler
                    "recipients": recipients,  # Raw recipient selection
                    "announcement_id": announcement.name
                },
                title="Thông báo",
                body=announcement.title_vn or announcement.title_en or "Thông báo mới",
                icon="/icon.png",
                data={
                    "type": "announcement",
                    "announcement_id": announcement.name,
                    "title_en": announcement.title_en,
                    "title_vn": announcement.title_vn,
                    "url": f"/announcement/{announcement.name}"
                }
            )

            frappe.logger().info(f"📢 Announcement notification result: {notification_result}")

            # Update status to sent and store sent count
            announcement.status = "sent"
            announcement.sent_at = frappe.utils.now()
            announcement.sent_count = notification_result.get("total_parents", 0)
            announcement.save()

            frappe.logger().info(f"✅ Announcement {announcement_id} sent successfully to {notification_result.get('total_parents', 0)} parents")

            return success_response(
                message="Announcement sent successfully",
                data={
                    "announcement_id": announcement.name,
                    "status": announcement.status,
                    "sent_at": announcement.sent_at,
                    "sent_by": announcement.sent_by,
                    "sent_by_fullname": _get_user_fullname(announcement.sent_by),
                    "sent_count": announcement.sent_count,
                    "notification_summary": {
                        "total_parents": notification_result.get("total_parents", 0),
                        "success_count": notification_result.get("success_count", 0),
                        "failed_count": notification_result.get("failed_count", 0)
                    }
                }
            )

        except Exception as e:
            frappe.logger().error(f"❌ Error sending notifications: {str(e)}")
            return error_response(
                message=f"Failed to send notifications: {str(e)}",
                code="NOTIFICATION_ERROR"
            )

    except frappe.DoesNotExistError:
        return not_found_response("Announcement not found")
    except Exception as e:
        frappe.logger().error(f"Error sending announcement: {str(e)}")
        return error_response(
            message=f"Failed to send announcement: {str(e)}",
            code="SEND_ERROR"
        )
