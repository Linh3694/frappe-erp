# Copyright (c) 2024, Wellspring and contributors
# For license information, please see license.txt

"""
API endpoints cho Requirement CRUD
"""

import frappe
from frappe import _
import json
from erp.utils.api_response import (
    success_response,
    error_response,
    single_item_response,
    not_found_response,
    forbidden_response
)
from .project import get_user_project_role, check_project_access


def check_requirement_permission(project_id: str, user: str) -> bool:
    """
    Kiểm tra user có quyền tạo/sửa requirement không
    - owner: YES
    - manager: YES
    - member: YES
    - viewer: NO
    """
    role = get_user_project_role(project_id, user)
    return role is not None and role != "viewer"


def enrich_requirement_data(requirement: dict) -> dict:
    """Bổ sung thông tin cho requirement"""
    # Enrich created_by info
    if requirement.get("created_by"):
        creator_info = frappe.db.get_value(
            "User",
            requirement["created_by"],
            ["full_name", "user_image"],
            as_dict=True
        )
        if creator_info:
            requirement["created_by_full_name"] = creator_info.get("full_name")
            requirement["created_by_image"] = creator_info.get("user_image")
    
    # Lấy số lượng resources đính kèm
    resource_count = frappe.db.count(
        "PM Resource",
        {"target_type": "requirement", "target_id": requirement["name"]}
    )
    requirement["resource_count"] = resource_count
    
    return requirement


def log_requirement_change(project_id: str, requirement_id: str, action: str, 
                          old_value: dict, new_value: dict):
    """Helper function để log thay đổi requirement"""
    try:
        log = frappe.get_doc({
            "doctype": "PM Change Log",
            "project_id": project_id,
            "action": action,
            "actor_id": frappe.session.user,
            "target_type": "requirement",
            "target_id": requirement_id,
            "old_value": json.dumps(old_value) if old_value else None,
            "new_value": json.dumps(new_value) if new_value else None
        })
        log.insert(ignore_permissions=True)
    except Exception as e:
        frappe.log_error(f"Error logging requirement change: {str(e)}")


@frappe.whitelist(allow_guest=False)
def get_requirements():
    """
    Lấy danh sách requirements của project
    
    Args:
        project_id: ID của project (from query params)
        status: Filter theo status (new/approved/rejected, from query params)
        priority: Filter theo priority (from query params)
    
    Returns:
        List requirements
    """
    try:
        user = frappe.session.user
        
        # Lấy params từ request
        project_id = frappe.form_dict.get("project_id")
        status = frappe.form_dict.get("status")
        priority = frappe.form_dict.get("priority")
        
        # Validate project_id
        if not project_id:
            return error_response("project_id is required", code="MISSING_PARAMETER")
        
        # Kiểm tra quyền truy cập
        if not check_project_access(project_id, user):
            return forbidden_response("Bạn không có quyền truy cập dự án này")
        
        # Build filters
        filters = {"project_id": project_id}
        if status:
            filters["status"] = status
        if priority:
            filters["priority"] = priority
        
        # Lấy requirements
        requirements = frappe.get_all(
            "PM Requirement",
            filters=filters,
            fields=["name", "title", "description", "priority", "status",
                   "created_by", "creation", "modified"],
            order_by="creation desc"
        )
        
        # Enrich data
        for req in requirements:
            enrich_requirement_data(req)
        
        return success_response(
            data=requirements,
            message=f"Tìm thấy {len(requirements)} yêu cầu"
        )
        
    except Exception as e:
        frappe.log_error(f"Error getting requirements: {str(e)}")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def get_requirement(requirement_id: str):
    """
    Lấy chi tiết một requirement
    
    Args:
        requirement_id: ID của requirement
    
    Returns:
        Chi tiết requirement
    """
    try:
        user = frappe.session.user
        
        # Kiểm tra requirement tồn tại
        if not frappe.db.exists("PM Requirement", requirement_id):
            return not_found_response(f"Requirement {requirement_id} không tồn tại")
        
        requirement = frappe.get_doc("PM Requirement", requirement_id).as_dict()
        
        # Kiểm tra quyền truy cập
        if not check_project_access(requirement["project_id"], user):
            return forbidden_response("Bạn không có quyền truy cập yêu cầu này")
        
        # Enrich data
        enrich_requirement_data(requirement)
        
        # Lấy resources đính kèm
        resources = frappe.get_all(
            "PM Resource",
            filters={"target_type": "requirement", "target_id": requirement_id},
            fields=["name", "filename", "file_url", "file_type", "file_size",
                   "uploaded_by", "creation"]
        )
        requirement["resources"] = resources
        
        return single_item_response(requirement, "Lấy thông tin yêu cầu thành công")
        
    except Exception as e:
        frappe.log_error(f"Error getting requirement: {str(e)}")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["POST"])
def create_requirement():
    """
    Tạo requirement mới
    
    Payload:
        project_id: ID project (required)
        title: Tiêu đề (required)
        description: Mô tả chi tiết
        priority: Độ ưu tiên (default: medium)
    
    Returns:
        Requirement vừa tạo
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
        
        if errors:
            return validation_error_response("Thiếu thông tin bắt buộc", errors)
        
        project_id = data.get("project_id")
        
        # Kiểm tra project tồn tại
        if not frappe.db.exists("PM Project", project_id):
            return not_found_response(f"Project {project_id} không tồn tại")
        
        # Kiểm tra quyền
        if not check_requirement_permission(project_id, user):
            return forbidden_response("Bạn không có quyền tạo yêu cầu trong dự án này")
        
        # Validate priority
        valid_priorities = ["low", "medium", "high", "critical"]
        priority = data.get("priority", "medium")
        if priority not in valid_priorities:
            return validation_error_response(
                "Priority không hợp lệ",
                {"priority": [f"Priority phải là một trong: {', '.join(valid_priorities)}"]}
            )
        
        # Tạo requirement
        requirement = frappe.get_doc({
            "doctype": "PM Requirement",
            "project_id": project_id,
            "title": data.get("title"),
            "description": data.get("description"),
            "priority": priority,
            "status": "new",
            "created_by": user
        })
        requirement.insert()
        frappe.db.commit()
        
        # Log change
        log_requirement_change(project_id, requirement.name, "requirement_created", None, {
            "title": requirement.title,
            "priority": requirement.priority
        })
        
        # Enrich và return
        req_data = requirement.as_dict()
        enrich_requirement_data(req_data)
        
        return single_item_response(req_data, "Tạo yêu cầu thành công")
        
    except Exception as e:
        frappe.log_error(f"Error creating requirement: {str(e)}")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["POST"])
def update_requirement(requirement_id: str):
    """
    Cập nhật requirement
    
    Args:
        requirement_id: ID của requirement
    
    Payload:
        title: Tiêu đề
        description: Mô tả
        priority: Độ ưu tiên
        status: Trạng thái
    
    Returns:
        Requirement sau khi cập nhật
    """
    try:
        user = frappe.session.user
        data = json.loads(frappe.request.data) if frappe.request.data else {}
        
        # Kiểm tra requirement tồn tại
        if not frappe.db.exists("PM Requirement", requirement_id):
            return not_found_response(f"Requirement {requirement_id} không tồn tại")
        
        requirement = frappe.get_doc("PM Requirement", requirement_id)
        
        # Kiểm tra quyền
        if not check_requirement_permission(requirement.project_id, user):
            return forbidden_response("Bạn không có quyền chỉnh sửa yêu cầu này")
        
        # Lưu old values
        old_values = {
            "title": requirement.title,
            "description": requirement.description,
            "priority": requirement.priority,
            "status": requirement.status
        }
        
        # Cập nhật
        if "title" in data:
            requirement.title = data["title"]
        if "description" in data:
            requirement.description = data["description"]
        if "priority" in data:
            valid_priorities = ["low", "medium", "high", "critical"]
            if data["priority"] in valid_priorities:
                requirement.priority = data["priority"]
        if "status" in data:
            valid_statuses = ["new", "approved", "rejected"]
            if data["status"] in valid_statuses:
                requirement.status = data["status"]
        
        requirement.save()
        frappe.db.commit()
        
        # Log change
        new_values = {
            "title": requirement.title,
            "description": requirement.description,
            "priority": requirement.priority,
            "status": requirement.status
        }
        log_requirement_change(requirement.project_id, requirement_id, 
                              "requirement_updated", old_values, new_values)
        
        # Enrich và return
        req_data = requirement.as_dict()
        enrich_requirement_data(req_data)
        
        return single_item_response(req_data, "Cập nhật yêu cầu thành công")
        
    except Exception as e:
        frappe.log_error(f"Error updating requirement: {str(e)}")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["POST"])
def delete_requirement(requirement_id: str):
    """
    Xóa requirement
    
    Args:
        requirement_id: ID của requirement
    
    Returns:
        Success message
    """
    try:
        user = frappe.session.user
        
        # Kiểm tra requirement tồn tại
        if not frappe.db.exists("PM Requirement", requirement_id):
            return not_found_response(f"Requirement {requirement_id} không tồn tại")
        
        requirement = frappe.get_doc("PM Requirement", requirement_id)
        project_id = requirement.project_id
        
        # Kiểm tra quyền (owner/manager mới được xóa)
        role = get_user_project_role(project_id, user)
        if role not in ["owner", "manager"]:
            return forbidden_response("Bạn không có quyền xóa yêu cầu này")
        
        # Lưu info để log
        req_info = {
            "title": requirement.title,
            "priority": requirement.priority,
            "status": requirement.status
        }
        
        # Xóa resources liên quan
        frappe.db.delete("PM Resource", {"target_type": "requirement", "target_id": requirement_id})
        
        # Xóa requirement
        frappe.delete_doc("PM Requirement", requirement_id, force=True)
        frappe.db.commit()
        
        # Log change
        log_requirement_change(project_id, requirement_id, "requirement_deleted", 
                              req_info, None)
        
        return success_response(message="Xóa yêu cầu thành công")
        
    except Exception as e:
        frappe.log_error(f"Error deleting requirement: {str(e)}")
        return error_response(str(e))

