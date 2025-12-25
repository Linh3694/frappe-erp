# Copyright (c) 2024, Wellspring and contributors
# For license information, please see license.txt

"""
API endpoints cho Meeting Minutes (Biên bản họp)
"""

import frappe
from frappe import _
import json
from erp.utils.api_response import (
    success_response,
    error_response,
    single_item_response,
    not_found_response,
    forbidden_response,
    validation_error_response
)
from .project import get_user_project_role, check_project_access


def check_meeting_permission(project_id: str, user: str) -> bool:
    """
    Kiểm tra user có quyền tạo/sửa/xóa meeting không
    - owner: YES
    - manager: YES  
    - member: YES
    - viewer: NO
    """
    role = get_user_project_role(project_id, user)
    return role is not None and role != "viewer"


def enrich_meeting_data(meeting: dict) -> dict:
    """Bổ sung thông tin cho meeting"""
    # Lấy attendees
    attendees = frappe.get_all(
        "PM Meeting Attendee",
        filters={"parent": meeting["name"]},
        fields=["user_id", "attended"]
    )
    
    # Enrich attendee info
    for attendee in attendees:
        user_info = frappe.db.get_value(
            "User",
            attendee["user_id"],
            ["full_name", "user_image", "email"],
            as_dict=True
        )
        if user_info:
            attendee["full_name"] = user_info.get("full_name")
            attendee["user_image"] = user_info.get("user_image")
            attendee["email"] = user_info.get("email")
    
    meeting["attendees"] = attendees
    
    # Enrich created_by info
    if meeting.get("created_by"):
        creator_info = frappe.db.get_value(
            "User",
            meeting["created_by"],
            ["full_name", "user_image"],
            as_dict=True
        )
        if creator_info:
            meeting["created_by_full_name"] = creator_info.get("full_name")
            meeting["created_by_image"] = creator_info.get("user_image")
    
    return meeting


@frappe.whitelist(allow_guest=False)
def get_meetings():
    """
    Lấy danh sách meetings của project
    
    Query params:
        project_id: ID của project (required)
    
    Returns:
        Danh sách meetings
    """
    try:
        user = frappe.session.user
        project_id = frappe.form_dict.get("project_id")
        
        if not project_id:
            return error_response("project_id is required", code="MISSING_PARAMETER")
        
        # Kiểm tra quyền truy cập project
        if not check_project_access(project_id, user):
            return forbidden_response("Bạn không có quyền truy cập dự án này")
        
        # Lấy meetings
        meetings = frappe.get_all(
            "PM Meeting",
            filters={"project_id": project_id},
            fields=[
                "name", "title", "description", "meeting_date",
                "start_time", "end_time", "location",
                "created_by", "creation", "modified"
            ],
            order_by="meeting_date desc, start_time desc"
        )
        
        # Enrich data
        for meeting in meetings:
            enrich_meeting_data(meeting)
        
        return success_response(
            data=meetings,
            message=f"Tìm thấy {len(meetings)} biên bản họp"
        )
        
    except Exception as e:
        frappe.log_error(f"Error getting meetings: {str(e)}")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def get_meeting():
    """
    Lấy chi tiết một meeting
    
    Query params:
        meeting_id: ID của meeting (required)
    
    Returns:
        Chi tiết meeting
    """
    try:
        user = frappe.session.user
        meeting_id = frappe.form_dict.get("meeting_id")
        
        if not meeting_id:
            return validation_error_response("Meeting ID là bắt buộc", {"meeting_id": ["Meeting ID không được để trống"]})
        
        # Kiểm tra meeting tồn tại
        if not frappe.db.exists("PM Meeting", meeting_id):
            return not_found_response(f"Meeting {meeting_id} không tồn tại")
        
        meeting = frappe.get_doc("PM Meeting", meeting_id).as_dict()
        
        # Kiểm tra quyền truy cập project
        if not check_project_access(meeting["project_id"], user):
            return forbidden_response("Bạn không có quyền truy cập biên bản này")
        
        # Enrich data
        enrich_meeting_data(meeting)
        
        return single_item_response(meeting, "Lấy thông tin biên bản thành công")
        
    except Exception as e:
        frappe.log_error(f"Error getting meeting: {str(e)}")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["POST"])
def create_meeting():
    """
    Tạo meeting mới
    
    Payload:
        project_id: ID project (required)
        title: Tiêu đề (required)
        description: Mô tả
        meeting_date: Ngày họp (required)
        start_time: Giờ bắt đầu
        end_time: Giờ kết thúc
        location: Địa điểm
        minutes: Nội dung biên bản
        action_items: Action items
        attendee_ids: List user IDs tham dự
    
    Returns:
        Meeting vừa tạo
    """
    try:
        user = frappe.session.user
        data = json.loads(frappe.request.data) if frappe.request.data else {}
        
        # Validate required fields
        errors = {}
        if not data.get("project_id"):
            errors["project_id"] = ["Project ID là bắt buộc"]
        if not data.get("title"):
            errors["title"] = ["Tiêu đề là bắt buộc"]
        if not data.get("meeting_date"):
            errors["meeting_date"] = ["Ngày họp là bắt buộc"]
        
        if errors:
            return validation_error_response("Thiếu thông tin bắt buộc", errors)
        
        project_id = data.get("project_id")
        
        # Kiểm tra project tồn tại
        if not frappe.db.exists("PM Project", project_id):
            return not_found_response(f"Project {project_id} không tồn tại")
        
        # Kiểm tra quyền tạo meeting
        if not check_meeting_permission(project_id, user):
            return forbidden_response("Bạn không có quyền tạo biên bản trong dự án này")
        
        # Tạo meeting
        meeting = frappe.get_doc({
            "doctype": "PM Meeting",
            "project_id": project_id,
            "title": data.get("title"),
            "description": data.get("description"),
            "meeting_date": data.get("meeting_date"),
            "start_time": data.get("start_time"),
            "end_time": data.get("end_time"),
            "location": data.get("location"),
            "minutes": data.get("minutes"),
            "action_items": data.get("action_items"),
            "created_by": user
        })
        
        # Thêm attendees nếu có
        attendee_ids = data.get("attendee_ids", [])
        for attendee_id in attendee_ids:
            if frappe.db.exists("User", attendee_id):
                meeting.append("attendees", {
                    "user_id": attendee_id,
                    "attended": 1
                })
        
        meeting.insert()
        frappe.db.commit()
        
        # Enrich và return
        meeting_data = meeting.as_dict()
        enrich_meeting_data(meeting_data)
        
        return single_item_response(meeting_data, "Tạo biên bản thành công")
        
    except Exception as e:
        frappe.log_error(f"Error creating meeting: {str(e)}")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["POST"])
def update_meeting():
    """
    Cập nhật meeting
    
    Query params:
        meeting_id: ID của meeting (required)
    
    Payload:
        title: Tiêu đề
        description: Mô tả
        meeting_date: Ngày họp
        start_time: Giờ bắt đầu
        end_time: Giờ kết thúc
        location: Địa điểm
        minutes: Nội dung biên bản
        action_items: Action items
        attendee_ids: List user IDs tham dự (replace all)
    
    Returns:
        Meeting sau khi cập nhật
    """
    try:
        user = frappe.session.user
        meeting_id = frappe.form_dict.get("meeting_id")
        
        if not meeting_id:
            return validation_error_response("Meeting ID là bắt buộc", {"meeting_id": ["Meeting ID không được để trống"]})
        
        data = json.loads(frappe.request.data) if frappe.request.data else {}
        
        # Kiểm tra meeting tồn tại
        if not frappe.db.exists("PM Meeting", meeting_id):
            return not_found_response(f"Meeting {meeting_id} không tồn tại")
        
        meeting = frappe.get_doc("PM Meeting", meeting_id)
        
        # Kiểm tra quyền
        if not check_meeting_permission(meeting.project_id, user):
            return forbidden_response("Bạn không có quyền chỉnh sửa biên bản này")
        
        # Cập nhật fields
        if "title" in data:
            meeting.title = data["title"]
        if "description" in data:
            meeting.description = data["description"]
        if "meeting_date" in data:
            meeting.meeting_date = data["meeting_date"]
        if "start_time" in data:
            meeting.start_time = data["start_time"]
        if "end_time" in data:
            meeting.end_time = data["end_time"]
        if "location" in data:
            meeting.location = data["location"]
        if "minutes" in data:
            meeting.minutes = data["minutes"]
        if "action_items" in data:
            meeting.action_items = data["action_items"]
        
        # Cập nhật attendees nếu có
        if "attendee_ids" in data:
            # Clear existing attendees
            meeting.attendees = []
            
            # Add new attendees
            for attendee_id in data.get("attendee_ids", []):
                if frappe.db.exists("User", attendee_id):
                    meeting.append("attendees", {
                        "user_id": attendee_id,
                        "attended": 1
                    })
        
        meeting.save()
        frappe.db.commit()
        
        # Enrich và return
        meeting_data = meeting.as_dict()
        enrich_meeting_data(meeting_data)
        
        return single_item_response(meeting_data, "Cập nhật biên bản thành công")
        
    except Exception as e:
        frappe.log_error(f"Error updating meeting: {str(e)}")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["POST"])
def delete_meeting():
    """
    Xóa meeting
    
    Query params:
        meeting_id: ID của meeting (required)
    
    Returns:
        Success message
    """
    try:
        user = frappe.session.user
        meeting_id = frappe.form_dict.get("meeting_id")
        
        if not meeting_id:
            return validation_error_response("Meeting ID là bắt buộc", {"meeting_id": ["Meeting ID không được để trống"]})
        
        # Kiểm tra meeting tồn tại
        if not frappe.db.exists("PM Meeting", meeting_id):
            return not_found_response(f"Meeting {meeting_id} không tồn tại")
        
        meeting = frappe.get_doc("PM Meeting", meeting_id)
        
        # Kiểm tra quyền
        if not check_meeting_permission(meeting.project_id, user):
            return forbidden_response("Bạn không có quyền xóa biên bản này")
        
        # Xóa meeting
        frappe.delete_doc("PM Meeting", meeting_id, force=True)
        frappe.db.commit()
        
        return success_response(message="Xóa biên bản thành công")
        
    except Exception as e:
        frappe.log_error(f"Error deleting meeting: {str(e)}")
        return error_response(str(e))

