# Copyright (c) 2025, Wellspring International School and contributors
# For license information, please see license.txt

"""
Feedback API for Parent Portal
Guardians can create, view, update, delete feedback and add replies
"""

import frappe
from frappe import _
from frappe.utils import now, get_datetime
import json
import base64
from erp.utils.api_response import (
    success_response,
    error_response,
    single_item_response,
    validation_error_response,
    not_found_response,
    list_response,
    forbidden_response
)


def _get_current_guardian():
    """Get current guardian from session user"""
    user_email = frappe.session.user
    
    # Extract guardian_id from email (format: guardian_id@parent.wellspring.edu.vn)
    if "@parent.wellspring.edu.vn" not in user_email:
        return None
    
    guardian_id = user_email.split('@')[0]
    
    # Find guardian
    guardians = frappe.get_all(
        "CRM Guardian",
        filters={"guardian_id": guardian_id},
        fields=["name"],
        limit=1
    )
    
    if not guardians:
        return None
    
    return guardians[0]['name']


def _get_device_info():
    """Extract device info from request"""
    request = frappe.request
    device_info = {
        "ip_address": request.environ.get("REMOTE_ADDR", ""),
        "user_agent": request.headers.get("User-Agent", "")
    }
    return device_info


def _process_attachments(feedback_name):
    """Process file attachments from frappe.request.files (similar to leave system)"""
    attachment_data = []

    if not frappe.request.files:
        return attachment_data

    for file_key, file_list in frappe.request.files.items(multi=True):
        # Handle both single file and multi=True
        if not isinstance(file_list, list):
            file_list = [file_list]
            
        if file_key.startswith('documents'):
            for file_obj in file_list:
                try:
                    # Read file content
                    file_content = file_obj.stream.read()
                    file_obj.stream.seek(0)  # Reset stream for potential re-read
                    
                    # Create File doc - use is_private=0 for public access
                    file_doc = frappe.get_doc({
                        "doctype": "File",
                        "file_name": file_obj.filename,
                        "attached_to_doctype": "Feedback",
                        "attached_to_name": feedback_name,
                        "content": file_content,
                        "is_private": 0  # Public file for easy access
                    })

                    file_doc.insert(ignore_permissions=True)

                    if file_doc.file_url:
                        # Store file metadata with the URL as-is (public files use /files/xxx)
                        attachment_data.append({
                            "name": file_doc.name,
                            "file_name": file_obj.filename,
                            "file_url": file_doc.file_url,
                            "file_size": len(file_content),
                            "file_type": file_obj.content_type or "application/octet-stream",
                            "creation": file_doc.creation
                        })

                except Exception as e:
                    frappe.logger().error(f"Error processing attachment {file_key}: {str(e)}")
                    # Continue processing other attachments

    return attachment_data


def _get_request_data():
    """Get request data from various sources, following leave.py pattern"""
    # Check if files exist AND not empty
    has_files = frappe.request.files and len(frappe.request.files) > 0
    
    if has_files:
        # FormData with files - use request.form
        data = frappe.request.form
        frappe.logger().info(f"Using frappe.request.form (has {len(frappe.request.files)} files)")
    elif frappe.request.is_json:
        # JSON request - use request.json
        data = frappe.request.json or {}
        frappe.logger().info("Using frappe.request.json (JSON body)")
    else:
        # Fallback to form_dict
        data = frappe.form_dict
        frappe.logger().info("Using frappe.form_dict (fallback)")
    
    frappe.logger().info(f"DEBUG [FINAL_DATA] Parsed data keys: {list(data.keys())}")
    frappe.logger().info(f"DEBUG [FINAL_DATA] 'feedback_type' value: {data.get('feedback_type', 'NOT FOUND')}")
    return data


@frappe.whitelist(allow_guest=False)
def create():
    """Create new feedback"""
    try:
        frappe.logger().info("="*100)
        frappe.logger().info("DEBUG [FEEDBACK CREATE] ===== START CREATE FEEDBACK =====")
        frappe.logger().info(f"DEBUG [FEEDBACK CREATE] Current user: {frappe.session.user}")
        
        guardian = _get_current_guardian()
        frappe.logger().info(f"DEBUG [FEEDBACK CREATE] Guardian: {guardian}")
        
        if not guardian:
            return error_response(
                message="Không tìm thấy thông tin phụ huynh",
                code="GUARDIAN_NOT_FOUND"
            )

        # Get data from form (handles both FormData and JSON)
        data = _get_request_data()

        # Debug logging
        frappe.logger().info(f"DEBUG [FEEDBACK CREATE] Content-Type: {frappe.request.content_type}")
        frappe.logger().info(f"DEBUG [FEEDBACK CREATE] Form dict keys: {list(frappe.local.form_dict.keys()) if frappe.local.form_dict else 'None'}")
        frappe.logger().info(f"DEBUG [FEEDBACK CREATE] Request files: {len(frappe.request.files) if frappe.request.files else 0} files")
        frappe.logger().info(f"DEBUG [FEEDBACK CREATE] Parsed data keys: {list(data.keys())}")
        frappe.logger().info(f"DEBUG [FEEDBACK CREATE] Parsed data: {data}")

        # Validate required fields
        feedback_type = data.get("feedback_type")
        if not feedback_type:
            return validation_error_response(
                "feedback_type là bắt buộc",
                {"feedback_type": ["feedback_type là bắt buộc"]}
            )
        
        # Validate fields based on feedback type
        if feedback_type == "Đánh giá":
            rating = data.get("rating")
            if not rating or rating == 0:
                return validation_error_response(
                    "rating là bắt buộc cho loại Đánh giá",
                    {"rating": ["rating là bắt buộc cho loại Đánh giá"]}
                )
        elif feedback_type == "Góp ý":
            if not data.get("title"):
                return validation_error_response(
                    "title là bắt buộc cho loại Góp ý",
                    {"title": ["title là bắt buộc cho loại Góp ý"]}
                )
            if not data.get("content"):
                return validation_error_response(
                    "content là bắt buộc cho loại Góp ý",
                    {"content": ["content là bắt buộc cho loại Góp ý"]}
                )
        
        # Create feedback doc
        feedback = frappe.get_doc({
            "doctype": "Feedback",
            "feedback_type": feedback_type,
            "guardian": guardian,
            "status": "Mới"
        })
        
        # Set fields based on feedback type
        if feedback_type == "Góp ý":
            # Department is now optional, only set if provided
            if data.get("department"):
                feedback.department = data.get("department")
            feedback.title = data.get("title")
            feedback.content = data.get("content")
            feedback.priority = data.get("priority", "Trung bình")
            # Explicitly clear rating fields for "Góp ý" type
            # Set rating to 0 instead of None because Rating fieldtype may not accept None
            feedback.rating = 0
            feedback.rating_comment = None
        elif feedback_type == "Đánh giá":
            # Ensure rating is set as integer (1-5 scale)
            rating_value = int(data.get("rating", 0))
            # Frappe Rating fieldtype stores normalized value (0-1), so we need to divide by 5
            # Rating 5 stars = 5/5 = 1.0, Rating 1 star = 1/5 = 0.2
            normalized_rating = rating_value / 5.0
            feedback.rating = normalized_rating  # Store normalized value (0-1)
            feedback.rating_comment = data.get("rating_comment", "") or ""
            feedback.status = "Mới"  # Không auto-complete, để staff có thể phản hồi nếu cần (đặc biệt với đánh giá thấp)
            # Explicitly clear "Góp ý" fields for "Đánh giá" type
            feedback.department = None
            feedback.title = None
            feedback.content = None
            feedback.priority = None
        
        # Set device info
        device_info = _get_device_info()
        feedback.ip_address = device_info.get("ip_address")
        feedback.user_agent = device_info.get("user_agent")
        
        # Insert with ignore_permissions since API validates permissions separately
        # Also ignore_validate to skip Frappe's required field validation (we validate in API)
        feedback.flags.ignore_permissions = True
        feedback.flags.ignore_validate = True
        feedback.insert()

        # Handle attachments if provided (after insert to have feedback_name)
        attachment_data = _process_attachments(feedback.name)
        if attachment_data:
            # Set attachments as JSON string with file metadata (for BE storage)
            feedback.attachments = json.dumps(attachment_data)

        # Manually call validate() to run business logic (deadline calculation, SLA status, etc.)
        # Keep ignore_validate=True to skip required field validation (already validated in API)
        feedback.validate()
        # Keep ignore_validate=True when saving to prevent Frappe from re-validating required fields
        # This is necessary because rating field has reqd=1 but depends_on condition
        feedback.flags.ignore_validate = True
        feedback.save()

        frappe.db.commit()
        
        # Send push notification to mobile staff (cho cả Góp ý và Đánh giá)
        # Chạy async (background job) để không block response
        try:
            from erp.api.notification.feedback import send_new_feedback_notification
            frappe.enqueue(
                send_new_feedback_notification,
                feedback_doc=feedback,
                queue='short',
                timeout=60,
                now=False  # Chạy background, không block
            )
            frappe.logger().info(f"📱 Feedback notification enqueued for {feedback.name}")
        except Exception as notify_error:
            frappe.logger().error(f"Error enqueueing feedback notification: {str(notify_error)}")
            # Don't fail the request if notification fails
        
        return success_response(
            data={"name": feedback.name},
            message="Tạo feedback thành công"
        )
    
    except Exception as e:
        frappe.logger().error(f"Error creating feedback: {str(e)}")
        return error_response(
            message=f"Lỗi khi tạo feedback: {str(e)}",
            code="CREATE_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def list_feedback():
    """List feedback for current guardian"""
    try:
        guardian = _get_current_guardian()
        if not guardian:
            return error_response(
                message="Không tìm thấy thông tin phụ huynh",
                code="GUARDIAN_NOT_FOUND"
            )
        
        data = _get_request_data()
        request_args = frappe.request.args
        
        # Get pagination params
        page = int(data.get("page", request_args.get("page", 1)))
        page_length = int(data.get("page_length", request_args.get("page_length", 20)))
        offset = (page - 1) * page_length
        
        # Build filters
        filters = {"guardian": guardian}
        
        # Add optional filters
        if data.get("feedback_type"):
            filters["feedback_type"] = data.get("feedback_type")
        
        if data.get("status"):
            filters["status"] = data.get("status")
        
        # Search query
        search_query = data.get("search") or request_args.get("search")
        
        # Get feedback list
        feedback_list = frappe.get_all(
            "Feedback",
            filters=filters,
            fields=[
                "name", "feedback_type", "title", "status", "priority",
                "rating", "rating_comment", "department", "assigned_to",
                "submitted_at", "last_updated", "closed_at",
                "conversation_count", "resolution_rating"
            ],
            order_by="submitted_at desc",
            limit=page_length,
            limit_start=offset
        )
        
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
def get():
    """Get feedback detail with conversation"""
    try:
        guardian = _get_current_guardian()
        if not guardian:
            return error_response(
                message="Không tìm thấy thông tin phụ huynh",
                code="GUARDIAN_NOT_FOUND"
            )
        
        data = _get_request_data()
        request_args = frappe.request.args
        
        feedback_name = data.get("name") or request_args.get("name")
        if not feedback_name:
            return validation_error_response(
                "name là bắt buộc",
                {"name": ["name là bắt buộc"]}
            )
        
        # Get feedback
        feedback = frappe.get_doc("Feedback", feedback_name)
        
        # Check permission
        if feedback.guardian != guardian:
            return error_response(
                message="Bạn không có quyền xem feedback này",
                code="PERMISSION_DENIED"
            )
        
        # Format response
        feedback_data = feedback.as_dict()

        # Process attachments - convert from JSON string to array with metadata
        if feedback.attachments:
            try:
                if isinstance(feedback.attachments, str):
                    attachment_list = json.loads(feedback.attachments)
                    # Return relative paths as-is (/files/xxx)
                    feedback_data["attachments"] = attachment_list
                else:
                    feedback_data["attachments"] = feedback.attachments
            except (json.JSONDecodeError, TypeError):
                feedback_data["attachments"] = []
        else:
            feedback_data["attachments"] = []

        # Include guardian information (guardian_name)
        if feedback.guardian:
            try:
                guardian_doc = frappe.get_doc("CRM Guardian", feedback.guardian)
                feedback_data["guardian_name"] = guardian_doc.guardian_name
            except frappe.DoesNotExistError:
                feedback_data["guardian_name"] = None

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
        
        # Format replies
        if feedback.replies:
            feedback_data["replies"] = [
                {
                    "content": reply.content,
                    "reply_by": reply.reply_by,
                    "reply_by_type": reply.reply_by_type,
                    "reply_date": reply.reply_date,
                    "is_internal": reply.is_internal if not reply.is_internal else False  # Hide internal notes from guardian
                }
                for reply in feedback.replies
                if not reply.is_internal  # Filter out internal notes
            ]
        
        return single_item_response(data=feedback_data)
    
    except frappe.DoesNotExistError:
        return not_found_response("Feedback không tồn tại")
    except Exception as e:
        frappe.logger().error(f"Error getting feedback: {str(e)}")
        return error_response(
            message=f"Lỗi khi lấy feedback: {str(e)}",
            code="GET_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def update():
    """Update feedback (guardian only, before response)"""
    try:
        guardian = _get_current_guardian()
        if not guardian:
            return error_response(
                message="Không tìm thấy thông tin phụ huynh",
                code="GUARDIAN_NOT_FOUND"
            )
        
        data = frappe.local.form_dict
        feedback_name = data.get("name")
        
        if not feedback_name:
            return validation_error_response(
                "name là bắt buộc",
                {"name": ["name là bắt buộc"]}
            )
        
        # Get feedback
        feedback = frappe.get_doc("Feedback", feedback_name)
        
        # Check permission
        if feedback.guardian != guardian:
            return error_response(
                message="Bạn không có quyền cập nhật feedback này",
                code="PERMISSION_DENIED"
            )
        
        # Check if feedback already has replies
        if feedback.replies and len(feedback.replies) > 0:
            return error_response(
                message="Không thể cập nhật feedback đã có phản hồi",
                code="UPDATE_NOT_ALLOWED"
            )
        
        # Update fields
        if data.get("title"):
            feedback.title = data.get("title")
        if data.get("content"):
            feedback.content = data.get("content")
        if data.get("department"):
            feedback.department = data.get("department")
        if data.get("rating"):
            feedback.rating = data.get("rating")
        if data.get("rating_comment"):
            feedback.rating_comment = data.get("rating_comment")
        
        feedback.save()
        frappe.db.commit()
        
        return success_response(
            data={"name": feedback.name},
            message="Cập nhật feedback thành công"
        )
    
    except frappe.DoesNotExistError:
        return not_found_response("Feedback không tồn tại")
    except Exception as e:
        frappe.logger().error(f"Error updating feedback: {str(e)}")
        return error_response(
            message=f"Lỗi khi cập nhật feedback: {str(e)}",
            code="UPDATE_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def delete():
    """Delete feedback (guardian only, before response)"""
    try:
        guardian = _get_current_guardian()
        if not guardian:
            return error_response(
                message="Không tìm thấy thông tin phụ huynh",
                code="GUARDIAN_NOT_FOUND"
            )
        
        data = _get_request_data()
        feedback_name = data.get("name")
        
        if not feedback_name:
            return validation_error_response(
                "name là bắt buộc",
                {"name": ["name là bắt buộc"]}
            )
        
        # Get feedback
        feedback = frappe.get_doc("Feedback", feedback_name)
        
        # Check permission
        if feedback.guardian != guardian:
            return error_response(
                message="Bạn không có quyền xóa feedback này",
                code="PERMISSION_DENIED"
            )
        
        # Check if feedback already has replies
        if feedback.replies and len(feedback.replies) > 0:
            return error_response(
                message="Không thể xóa feedback đã có phản hồi",
                code="DELETE_NOT_ALLOWED"
            )
        
        # Delete feedback (ignore permissions as we already checked guardian ownership)
        frappe.delete_doc("Feedback", feedback_name, ignore_permissions=True, force=True)
        frappe.db.commit()
        
        return success_response(message="Xóa feedback thành công")
    
    except frappe.DoesNotExistError:
        return not_found_response("Feedback không tồn tại")
    except Exception as e:
        frappe.logger().error(f"Error deleting feedback: {str(e)}")
        return error_response(
            message=f"Lỗi khi xóa feedback: {str(e)}",
            code="DELETE_ERROR"
        )


def _process_guardian_reply_attachments(feedback_name):
    """Process file attachments from guardian reply"""
    import uuid
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
                        "is_private": 0  # Public file for easy access
                    })
                    file_doc.insert(ignore_permissions=True)

                    file_url = file_doc.file_url
                    if file_url:
                        attachment_urls.append(file_url)

                except Exception as e:
                    frappe.logger().error(f"Error processing guardian attachment {file_key}: {str(e)}")

    return attachment_urls


@frappe.whitelist(allow_guest=False)
def add_reply():
    """Add reply to feedback conversation (supports file attachments)"""
    try:
        guardian = _get_current_guardian()
        if not guardian:
            return error_response(
                message="Không tìm thấy thông tin phụ huynh",
                code="GUARDIAN_NOT_FOUND"
            )
        
        data = _get_request_data()
        feedback_name = data.get("name")
        content = data.get("content", "")
        
        # Parse request_close properly (FormData sends strings)
        request_close_raw = data.get("request_close", False)
        request_close = request_close_raw in [True, 1, "1", "true", "True"]
        
        if not feedback_name:
            return validation_error_response(
                "name là bắt buộc",
                {"name": ["name là bắt buộc"]}
            )
        
        # Check if there are files
        has_files = frappe.request.files and len(frappe.request.files) > 0
        
        if not content and not has_files:
            return validation_error_response(
                "content hoặc file đính kèm là bắt buộc",
                {"content": ["Vui lòng nhập nội dung hoặc đính kèm ảnh/video"]}
            )
        
        # Get feedback
        feedback = frappe.get_doc("Feedback", feedback_name)
        
        # Check permission
        if feedback.guardian != guardian:
            return error_response(
                message="Bạn không có quyền phản hồi feedback này",
                code="PERMISSION_DENIED"
            )
        
        # Process file attachments
        attachment_urls = _process_guardian_reply_attachments(feedback_name)
        
        # Build final content with attachments
        final_content = content or ""
        if attachment_urls:
            attachments_html = "\n\n---\n**File đính kèm:**\n"
            for url in attachment_urls:
                attachments_html += f'- <a href="{url}" target="_blank">{url.split("/")[-1]}</a>\n'
            final_content += attachments_html
        
        # Add reply
        reply_content = final_content
        if request_close:
            reply_content = f"{final_content}\n\n[Phụ huynh yêu cầu đóng yêu cầu]"
        
        feedback.append("replies", {
            "content": reply_content,
            "reply_by": frappe.session.user,
            "reply_by_type": "Guardian",
            "reply_date": now(),
            "is_internal": False
        })
        
        # Update status
        if request_close:
            # If requesting close, set status to waiting for staff confirmation
            feedback.status = "Chờ phản hồi phụ huynh"
        else:
            # If just replying, set status back to processing
            feedback.status = "Đang xử lý"
        
        feedback.save()
        frappe.db.commit()
        
        # Send push notification to assigned staff (if any)
        # Chạy async (background job) để không block response
        try:
            from erp.api.notification.feedback import send_feedback_reply_notification
            frappe.enqueue(
                send_feedback_reply_notification,
                feedback_doc=feedback,
                reply_type="Guardian",
                queue='short',
                timeout=60,
                now=False
            )
            frappe.logger().info(f"📱 Reply notification enqueued for {feedback.name}")
        except Exception as notify_error:
            frappe.logger().error(f"Error enqueueing reply notification: {str(notify_error)}")
            # Don't fail the request if notification fails
        
        return success_response(
            data={"name": feedback.name},
            message="Thêm phản hồi thành công"
        )
    
    except frappe.DoesNotExistError:
        return not_found_response("Feedback không tồn tại")
    except Exception as e:
        frappe.logger().error(f"Error adding reply: {str(e)}")
        return error_response(
            message=f"Lỗi khi thêm phản hồi: {str(e)}",
            code="REPLY_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def close_and_rate():
    """Close feedback and rate admin support"""
    try:
        guardian = _get_current_guardian()
        if not guardian:
            return error_response(
                message="Không tìm thấy thông tin phụ huynh",
                code="GUARDIAN_NOT_FOUND"
            )
        
        data = _get_request_data()
        feedback_name = data.get("name")
        resolution_rating = data.get("resolution_rating")
        resolution_comment = data.get("resolution_comment", "")
        close_message = data.get("close_message", "")
        support_rating = data.get("support_rating")
        support_comment = data.get("support_comment", "")
        
        if not feedback_name:
            return validation_error_response(
                "name là bắt buộc",
                {"name": ["name là bắt buộc"]}
            )
        if not resolution_rating:
            return validation_error_response(
                "resolution_rating là bắt buộc",
                {"resolution_rating": ["resolution_rating là bắt buộc"]}
            )
        if not support_rating:
            return validation_error_response(
                "support_rating là bắt buộc",
                {"support_rating": ["support_rating là bắt buộc"]}
            )
        
        # Get feedback
        feedback = frappe.get_doc("Feedback", feedback_name)
        
        # Check permission
        if feedback.guardian != guardian:
            return error_response(
                message="Bạn không có quyền đóng feedback này",
                code="PERMISSION_DENIED"
            )
        
        # Cho phép đóng cả "Góp ý" và "Đánh giá"
        
        # Check if feedback has staff replies
        if not feedback.replies:
            return error_response(
                message="Không thể đóng feedback chưa có phản hồi từ nhân viên",
                code="NO_STAFF_REPLY"
            )
        
        # Check if there's at least one staff reply
        has_staff_reply = any(reply.reply_by_type == "Staff" and not reply.is_internal for reply in feedback.replies)
        if not has_staff_reply:
            return error_response(
                message="Không thể đóng feedback chưa có phản hồi từ nhân viên",
                code="NO_STAFF_REPLY"
            )
        
        # Add closing message if provided
        if close_message:
            feedback.append("replies", {
                "content": close_message,
                "reply_by": frappe.session.user,
                "reply_by_type": "Guardian",
                "reply_date": now(),
                "is_internal": False
            })
        
        # Update status to closed
        feedback.status = "Đóng"
        feedback.closed_at = now()
        
        # Update resolution rating
        # Convert rating from 1-5 scale to normalized 0-1 scale
        normalized_rating = float(resolution_rating) / 5.0
        feedback.resolution_rating = normalized_rating
        feedback.resolution_comment = resolution_comment
        
        # Update support team rating
        # Convert rating from 1-5 scale to normalized 0-1 scale
        normalized_support_rating = float(support_rating) / 5.0
        feedback.support_rating = normalized_support_rating
        feedback.support_comment = support_comment
        feedback.support_rated_for = feedback.assigned_to  # Auto-set to who handled the support
        
        feedback.save()
        frappe.db.commit()
        
        return success_response(
            data={"name": feedback.name},
            message="Đóng yêu cầu và đánh giá thành công"
        )
    
    except frappe.DoesNotExistError:
        return not_found_response("Feedback không tồn tại")
    except Exception as e:
        frappe.logger().error(f"Error closing and rating feedback: {str(e)}")
        return error_response(
            message=f"Lỗi khi đóng và đánh giá feedback: {str(e)}",
            code="CLOSE_RATE_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def update_status():
    """Update feedback status (guardian can request close)"""
    try:
        guardian = _get_current_guardian()
        if not guardian:
            return error_response(
                message="Không tìm thấy thông tin phụ huynh",
                code="GUARDIAN_NOT_FOUND"
            )
        
        data = frappe.local.form_dict
        feedback_name = data.get("name")
        status = data.get("status")
        
        if not feedback_name:
            return validation_error_response(
                "name là bắt buộc",
                {"name": ["name là bắt buộc"]}
            )
        if not status:
            return validation_error_response(
                "status là bắt buộc",
                {"status": ["status là bắt buộc"]}
            )
        
        # Get feedback
        feedback = frappe.get_doc("Feedback", feedback_name)
        
        # Check permission
        if feedback.guardian != guardian:
            return error_response(
                message="Bạn không có quyền cập nhật feedback này",
                code="PERMISSION_DENIED"
            )
        
        # Guardian can only request close, not actually close
        if status == "Đóng":
            # Add a note requesting close
            feedback.append("replies", {
                "content": "Phụ huynh yêu cầu đóng feedback",
                "reply_by": frappe.session.user,
                "reply_by_type": "Guardian",
                "reply_date": now(),
                "is_internal": False
            })
            feedback.status = "Chờ phản hồi phụ huynh"  # Keep status as waiting for staff
        else:
            # For other status changes, guardian can update
            feedback.status = status
        
        feedback.save()
        frappe.db.commit()
        
        return success_response(
            data={"name": feedback.name},
            message="Cập nhật trạng thái thành công"
        )
    
    except frappe.DoesNotExistError:
        return not_found_response("Feedback không tồn tại")
    except Exception as e:
        frappe.logger().error(f"Error updating status: {str(e)}")
        return error_response(
            message=f"Lỗi khi cập nhật trạng thái: {str(e)}",
            code="STATUS_UPDATE_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def submit_resolution_rating():
    """Submit resolution rating for closed feedback"""
    try:
        guardian = _get_current_guardian()
        if not guardian:
            return error_response(
                message="Không tìm thấy thông tin phụ huynh",
                code="GUARDIAN_NOT_FOUND"
            )
        
        data = frappe.local.form_dict
        feedback_name = data.get("name")
        resolution_rating = data.get("resolution_rating")
        resolution_comment = data.get("resolution_comment", "")
        
        if not feedback_name:
            return validation_error_response(
                "name là bắt buộc",
                {"name": ["name là bắt buộc"]}
            )
        if not resolution_rating:
            return validation_error_response(
                "resolution_rating là bắt buộc",
                {"resolution_rating": ["resolution_rating là bắt buộc"]}
            )
        
        # Get feedback
        feedback = frappe.get_doc("Feedback", feedback_name)
        
        # Check permission
        if feedback.guardian != guardian:
            return error_response(
                message="Bạn không có quyền đánh giá feedback này",
                code="PERMISSION_DENIED"
            )
        
        # Check if feedback is closed
        if feedback.status not in ["Đóng", "Tự động đóng"]:
            return error_response(
                message="Chỉ có thể đánh giá feedback đã đóng",
                code="RATING_NOT_ALLOWED"
            )
        
        # Update resolution rating
        feedback.resolution_rating = resolution_rating
        feedback.resolution_comment = resolution_comment
        
        feedback.save()
        frappe.db.commit()
        
        return success_response(
            data={"name": feedback.name},
            message="Gửi đánh giá thành công"
        )
    
    except frappe.DoesNotExistError:
        return not_found_response("Feedback không tồn tại")
    except Exception as e:
        frappe.logger().error(f"Error submitting resolution rating: {str(e)}")
        return error_response(
            message=f"Lỗi khi gửi đánh giá: {str(e)}",
            code="RATING_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def get_feedback_attachments():
    """
    Get all attachments for a feedback - PARENT PORTAL ONLY

    This endpoint is dedicated for parent portal usage.
    Admins should use erp.api.erp_sis.feedback.get_feedback_attachments instead.
    """
    try:
        # Try to get feedback_name from various sources
        feedback_name = frappe.form_dict.get('feedback_name') or frappe.request.args.get('feedback_name')

        if not feedback_name:
            return validation_error_response("Thiếu feedback_name", {"feedback_name": ["Feedback name là bắt buộc"]})

        # Get the feedback to check permissions
        feedback = frappe.get_doc("Feedback", feedback_name)

        # PARENT PORTAL: Verify guardian has access to this feedback
        guardian = _get_current_guardian()
        if not guardian:
            return error_response("Không tìm thấy thông tin phụ huynh")

        # Check if the feedback belongs to this guardian
        if feedback.guardian != guardian:
            return forbidden_response("Bạn không có quyền truy cập file đính kèm của feedback này")

        # Get all files attached to this feedback
        attachments = frappe.get_all("File",
            filters={
                "attached_to_doctype": "Feedback",
                "attached_to_name": feedback_name,
                "is_private": 1
            },
            fields=["name", "file_name", "file_url", "file_size", "creation"],
            order_by="creation desc"
        )

        # Add full URLs for files
        for attachment in attachments:
            if attachment.file_url and not attachment.file_url.startswith('http'):
                attachment.file_url = frappe.utils.get_url(attachment.file_url)

        return list_response(attachments)

    except frappe.DoesNotExistError:
        return not_found_response("Feedback không tồn tại")
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Parent Portal Get Feedback Attachments Error")
        return error_response(f"Lỗi khi lấy file đính kèm: {str(e)}")

