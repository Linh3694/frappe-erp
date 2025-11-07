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
from erp.utils.api_response import (
    success_response,
    error_response,
    single_item_response,
    validation_error_response,
    not_found_response
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


def _get_request_data():
    """Get request data from various sources"""
    data = {}
    
    # Check if request is JSON
    is_json = False
    if hasattr(frappe.request, 'content_type'):
        content_type = frappe.request.content_type or ''
        is_json = 'application/json' in content_type.lower()
    
    # Try to get from JSON body first if Content-Type is JSON
    if is_json:
        try:
            if hasattr(frappe.request, 'data') and frappe.request.data:
                raw = frappe.request.data
                body = raw.decode('utf-8') if isinstance(raw, (bytes, bytearray)) else raw
                if body:
                    parsed = json.loads(body)
                    if isinstance(parsed, dict):
                        data.update(parsed)
        except (json.JSONDecodeError, AttributeError, TypeError) as e:
            frappe.logger().error(f"Error parsing JSON body: {str(e)}")
    
    # Also try form_dict (might have data from URL params or form data)
    if frappe.local.form_dict:
        form_dict_data = dict(frappe.local.form_dict)
        # Merge form_dict data, but don't overwrite JSON data
        for key, value in form_dict_data.items():
            if key not in data or not data.get(key):
                data[key] = value
    
    return data


@frappe.whitelist(allow_guest=False)
def create():
    """Create new feedback"""
    try:
        guardian = _get_current_guardian()
        if not guardian:
            return error_response(
                message="Không tìm thấy thông tin phụ huynh",
                code="GUARDIAN_NOT_FOUND"
            )
        
        data = _get_request_data()
        
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
            if not data.get("department"):
                return validation_error_response(
                    "department là bắt buộc cho loại Góp ý",
                    {"department": ["department là bắt buộc cho loại Góp ý"]}
                )
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
            feedback.status = "Hoàn thành"  # Auto-complete for rating
            # Explicitly clear "Góp ý" fields for "Đánh giá" type
            feedback.department = None
            feedback.title = None
            feedback.content = None
            feedback.priority = None
        
        # Set device info
        device_info = _get_device_info()
        feedback.ip_address = device_info.get("ip_address")
        feedback.user_agent = device_info.get("user_agent")
        
        # Handle attachments if provided
        if data.get("attachments"):
            feedback.attachments = data.get("attachments")
        
        # Insert with ignore_permissions since API validates permissions separately
        # Also ignore_validate to skip Frappe's required field validation (we validate in API)
        feedback.flags.ignore_permissions = True
        feedback.flags.ignore_validate = True
        feedback.insert()
        
        # Manually call validate() to run business logic (deadline calculation, SLA status, etc.)
        # Keep ignore_validate=True to skip required field validation (already validated in API)
        feedback.validate()
        # Keep ignore_validate=True when saving to prevent Frappe from re-validating required fields
        # This is necessary because rating field has reqd=1 but depends_on condition
        feedback.flags.ignore_validate = True
        feedback.save()
        
        frappe.db.commit()
        
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
                "conversation_count", "resolution_rating",
                "assigned_to_full_name", "assigned_to_jobtitle", "assigned_to_avatar"
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
                message="Bạn không có quyền xóa feedback này",
                code="PERMISSION_DENIED"
            )
        
        # Check if feedback already has replies
        if feedback.replies and len(feedback.replies) > 0:
            return error_response(
                message="Không thể xóa feedback đã có phản hồi",
                code="DELETE_NOT_ALLOWED"
            )
        
        # Delete feedback
        frappe.delete_doc("Feedback", feedback_name)
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


@frappe.whitelist(allow_guest=False)
def add_reply():
    """Add reply to feedback conversation"""
    try:
        guardian = _get_current_guardian()
        if not guardian:
            return error_response(
                message="Không tìm thấy thông tin phụ huynh",
                code="GUARDIAN_NOT_FOUND"
            )
        
        data = _get_request_data()
        feedback_name = data.get("name")
        content = data.get("content")
        request_close = data.get("request_close", False)
        
        if not feedback_name:
            return validation_error_response(
                "name là bắt buộc",
                {"name": ["name là bắt buộc"]}
            )
        if not content:
            return validation_error_response(
                "content là bắt buộc",
                {"content": ["content là bắt buộc"]}
            )
        
        # Get feedback
        feedback = frappe.get_doc("Feedback", feedback_name)
        
        # Check permission
        if feedback.guardian != guardian:
            return error_response(
                message="Bạn không có quyền phản hồi feedback này",
                code="PERMISSION_DENIED"
            )
        
        # Check if feedback type allows replies
        if feedback.feedback_type == "Đánh giá":
            return error_response(
                message="Đánh giá không thể có phản hồi",
                code="REPLY_NOT_ALLOWED"
            )
        
        # Add reply
        reply_content = content
        if request_close:
            reply_content = f"{content}\n\n[Phụ huynh yêu cầu đóng yêu cầu]"
        
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
        elif feedback.status == "Chờ phản hồi phụ huynh":
            feedback.status = "Đã phản hồi"
        
        feedback.save()
        frappe.db.commit()
        
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
                message="Bạn không có quyền đóng feedback này",
                code="PERMISSION_DENIED"
            )
        
        # Only allow closing "Góp ý" type
        if feedback.feedback_type != "Góp ý":
            return error_response(
                message="Chỉ có thể đóng feedback loại Góp ý",
                code="CLOSE_NOT_ALLOWED"
            )
        
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

