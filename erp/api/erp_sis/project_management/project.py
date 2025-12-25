# Copyright (c) 2024, Wellspring and contributors
# For license information, please see license.txt

"""
API endpoints cho Project CRUD và member management
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


def get_user_project_role(project_id: str, user_id: str) -> str | None:
    """
    Lấy role của user trong project
    Returns: 'owner' | 'manager' | 'member' | 'viewer' | None
    """
    member = frappe.db.get_value(
        "PM Project Member",
        {"project_id": project_id, "user_id": user_id},
        ["role"],
        as_dict=True
    )
    return member.get("role") if member else None


def check_project_access(project_id: str, user_id: str) -> bool:
    """Kiểm tra user có quyền truy cập project không"""
    return get_user_project_role(project_id, user_id) is not None


def check_project_edit_permission(project_id: str, user_id: str) -> bool:
    """Kiểm tra user có quyền edit project không (owner/manager)"""
    role = get_user_project_role(project_id, user_id)
    return role in ["owner", "manager"]


def enrich_project_data(project: dict) -> dict:
    """Bổ sung thêm thông tin cho project"""
    # Lấy thông tin members
    members = frappe.get_all(
        "PM Project Member",
        filters={"project_id": project["name"]},
        fields=["name", "user_id", "role", "joined_at"]
    )
    
    # Enrich member info
    for member in members:
        user_info = frappe.db.get_value(
            "User",
            member["user_id"],
            ["full_name", "user_image"],
            as_dict=True
        )
        if user_info:
            member["full_name"] = user_info.get("full_name")
            member["user_image"] = user_info.get("user_image")
    
    project["members"] = members
    project["member_count"] = len(members)
    
    # Lấy số lượng tasks
    task_count = frappe.db.count("PM Task", {"project_id": project["name"]})
    project["task_count"] = task_count
    
    # Lấy owner info
    owner_info = frappe.db.get_value(
        "User",
        project["owner_id"],
        ["full_name", "user_image"],
        as_dict=True
    )
    if owner_info:
        project["owner_full_name"] = owner_info.get("full_name")
        project["owner_image"] = owner_info.get("user_image")
    
    return project


@frappe.whitelist(allow_guest=False)
def get_my_projects(status: str = None, visibility: str = None):
    """
    Lấy danh sách projects mà user là thành viên
    
    Args:
        status: Filter theo status (active/archived)
        visibility: Filter theo visibility (private/internal)
    
    Returns:
        List các projects
    """
    try:
        user = frappe.session.user
        
        # Lấy các project mà user là member
        member_projects = frappe.get_all(
            "PM Project Member",
            filters={"user_id": user},
            pluck="project_id"
        )
        
        if not member_projects:
            return success_response(data=[], message="Không có dự án nào")
        
        # Build filters
        filters = {"name": ["in", member_projects]}
        if status:
            filters["status"] = status
        if visibility:
            filters["visibility"] = visibility
        
        # Lấy projects
        projects = frappe.get_all(
            "PM Project",
            filters=filters,
            fields=["name", "title", "description", "owner_id", "status", 
                   "visibility", "campus_id", "creation", "modified"],
            order_by="modified desc"
        )
        
        # Enrich data
        for project in projects:
            enrich_project_data(project)
        
        return success_response(
            data=projects,
            message=f"Tìm thấy {len(projects)} dự án"
        )
        
    except Exception as e:
        frappe.log_error(f"Error getting projects: {str(e)}")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def get_project():
    """
    Lấy chi tiết một project
    
    Args:
        project_id: ID của project (from query params)
    
    Returns:
        Chi tiết project với members và stats
    """
    try:
        user = frappe.session.user
        
        # Lấy project_id từ request params
        project_id = frappe.form_dict.get("project_id")
        
        # Validate project_id
        if not project_id:
            return error_response("project_id is required", code="MISSING_PARAMETER")
        
        # Kiểm tra project tồn tại
        if not frappe.db.exists("PM Project", project_id):
            return not_found_response(f"Project {project_id} không tồn tại")
        
        # Kiểm tra quyền truy cập
        if not check_project_access(project_id, user):
            return forbidden_response("Bạn không có quyền truy cập dự án này")
        
        # Lấy project
        project = frappe.get_doc("PM Project", project_id).as_dict()
        
        # Enrich data
        enrich_project_data(project)
        
        # Lấy user's role trong project
        project["current_user_role"] = get_user_project_role(project_id, user)
        
        return single_item_response(project, "Lấy thông tin dự án thành công")
        
    except Exception as e:
        frappe.log_error(f"Error getting project: {str(e)}")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["POST"])
def create_project():
    """
    Tạo project mới
    
    Payload:
        title: Tên dự án (required)
        description: Mô tả dự án
        visibility: private/internal (default: private)
        campus_id: Campus ID
    
    Returns:
        Project vừa tạo
    """
    try:
        user = frappe.session.user
        data = json.loads(frappe.request.data) if frappe.request.data else {}
        
        # Validate required fields
        if not data.get("title"):
            return validation_error_response(
                "Thiếu thông tin bắt buộc",
                {"title": ["Tên dự án là bắt buộc"]}
            )
        
        # Tạo project
        project = frappe.get_doc({
            "doctype": "PM Project",
            "title": data.get("title"),
            "description": data.get("description"),
            "owner_id": user,
            "status": "active",
            "visibility": data.get("visibility", "private"),
            "campus_id": data.get("campus_id")
        })
        project.insert()
        frappe.db.commit()
        
        # Enrich và return
        project_data = project.as_dict()
        enrich_project_data(project_data)
        project_data["current_user_role"] = "owner"
        
        # Log change
        log_project_change(project.name, "project_created", None, {
            "title": project.title,
            "visibility": project.visibility
        })
        
        return single_item_response(project_data, "Tạo dự án thành công")
        
    except Exception as e:
        frappe.log_error(f"Error creating project: {str(e)}")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["POST"])
def update_project(project_id: str):
    """
    Cập nhật thông tin project
    
    Args:
        project_id: ID của project
    
    Payload:
        title: Tên dự án
        description: Mô tả
        visibility: private/internal
        campus_id: Campus ID
    
    Returns:
        Project sau khi cập nhật
    """
    try:
        user = frappe.session.user
        data = json.loads(frappe.request.data) if frappe.request.data else {}
        
        # Kiểm tra project tồn tại
        if not frappe.db.exists("PM Project", project_id):
            return not_found_response(f"Project {project_id} không tồn tại")
        
        # Kiểm tra quyền edit
        if not check_project_edit_permission(project_id, user):
            return forbidden_response("Bạn không có quyền chỉnh sửa dự án này")
        
        # Lấy project và lưu old values
        project = frappe.get_doc("PM Project", project_id)
        old_values = {
            "title": project.title,
            "description": project.description,
            "visibility": project.visibility
        }
        
        # Cập nhật
        if "title" in data:
            project.title = data["title"]
        if "description" in data:
            project.description = data["description"]
        if "visibility" in data:
            project.visibility = data["visibility"]
        if "campus_id" in data:
            project.campus_id = data["campus_id"]
        
        project.save()
        frappe.db.commit()
        
        # Log change
        new_values = {
            "title": project.title,
            "description": project.description,
            "visibility": project.visibility
        }
        log_project_change(project_id, "project_updated", old_values, new_values)
        
        # Enrich và return
        project_data = project.as_dict()
        enrich_project_data(project_data)
        project_data["current_user_role"] = get_user_project_role(project_id, user)
        
        return single_item_response(project_data, "Cập nhật dự án thành công")
        
    except Exception as e:
        frappe.log_error(f"Error updating project: {str(e)}")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["POST"])
def archive_project(project_id: str):
    """
    Archive một project (chuyển status thành archived)
    
    Args:
        project_id: ID của project
    
    Returns:
        Project sau khi archive
    """
    try:
        user = frappe.session.user
        
        # Kiểm tra project tồn tại
        if not frappe.db.exists("PM Project", project_id):
            return not_found_response(f"Project {project_id} không tồn tại")
        
        # Chỉ owner mới có quyền archive
        role = get_user_project_role(project_id, user)
        if role != "owner":
            return forbidden_response("Chỉ chủ dự án mới có quyền archive")
        
        # Archive
        project = frappe.get_doc("PM Project", project_id)
        old_status = project.status
        project.status = "archived"
        project.save()
        frappe.db.commit()
        
        # Log change
        log_project_change(project_id, "project_archived", 
                          {"status": old_status}, 
                          {"status": "archived"})
        
        return success_response(message="Archive dự án thành công")
        
    except Exception as e:
        frappe.log_error(f"Error archiving project: {str(e)}")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["POST"])
def restore_project(project_id: str):
    """
    Khôi phục project từ archived về active
    
    Args:
        project_id: ID của project
    
    Returns:
        Project sau khi restore
    """
    try:
        user = frappe.session.user
        
        # Kiểm tra project tồn tại
        if not frappe.db.exists("PM Project", project_id):
            return not_found_response(f"Project {project_id} không tồn tại")
        
        # Chỉ owner mới có quyền restore
        role = get_user_project_role(project_id, user)
        if role != "owner":
            return forbidden_response("Chỉ chủ dự án mới có quyền khôi phục")
        
        # Restore
        project = frappe.get_doc("PM Project", project_id)
        old_status = project.status
        project.status = "active"
        project.save()
        frappe.db.commit()
        
        # Log change
        log_project_change(project_id, "project_restored",
                          {"status": old_status},
                          {"status": "active"})
        
        return success_response(message="Khôi phục dự án thành công")
        
    except Exception as e:
        frappe.log_error(f"Error restoring project: {str(e)}")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["POST"])
def delete_project(project_id: str):
    """
    Xóa project (chỉ owner có quyền)
    
    Args:
        project_id: ID của project
    
    Returns:
        Success message
    """
    try:
        user = frappe.session.user
        
        # Kiểm tra project tồn tại
        if not frappe.db.exists("PM Project", project_id):
            return not_found_response(f"Project {project_id} không tồn tại")
        
        # Chỉ owner mới có quyền xóa
        role = get_user_project_role(project_id, user)
        if role != "owner":
            return forbidden_response("Chỉ chủ dự án mới có quyền xóa")
        
        # Xóa các related docs trước
        # 1. Xóa members
        frappe.db.delete("PM Project Member", {"project_id": project_id})
        # 2. Xóa invitations
        frappe.db.delete("PM Project Invitation", {"project_id": project_id})
        # 3. Xóa task assignees của các tasks trong project
        tasks = frappe.get_all("PM Task", filters={"project_id": project_id}, pluck="name")
        if tasks:
            frappe.db.delete("PM Task Assignee", {"task_id": ["in", tasks]})
        # 4. Xóa tasks
        frappe.db.delete("PM Task", {"project_id": project_id})
        # 5. Xóa requirements
        frappe.db.delete("PM Requirement", {"project_id": project_id})
        # 6. Xóa resources
        frappe.db.delete("PM Resource", {"project_id": project_id})
        # 7. Xóa change logs
        frappe.db.delete("PM Change Log", {"project_id": project_id})
        # 8. Xóa project
        frappe.delete_doc("PM Project", project_id, force=True)
        
        frappe.db.commit()
        
        return success_response(message="Xóa dự án thành công")
        
    except Exception as e:
        frappe.log_error(f"Error deleting project: {str(e)}")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def get_project_members():
    """
    Lấy danh sách thành viên của project
    
    Args:
        project_id: ID của project (from query params)
    
    Returns:
        List các members với thông tin chi tiết
    """
    try:
        user = frappe.session.user
        
        # Lấy project_id từ request params
        project_id = frappe.form_dict.get("project_id")
        
        # Validate project_id
        if not project_id:
            return error_response("project_id is required", code="MISSING_PARAMETER")
        
        # Kiểm tra quyền truy cập
        if not check_project_access(project_id, user):
            return forbidden_response("Bạn không có quyền truy cập dự án này")
        
        # Lấy members
        members = frappe.get_all(
            "PM Project Member",
            filters={"project_id": project_id},
            fields=["name", "user_id", "role", "joined_at"]
        )
        
        # Enrich member info
        for member in members:
            user_info = frappe.db.get_value(
                "User",
                member["user_id"],
                ["full_name", "email", "user_image"],
                as_dict=True
            )
            if user_info:
                member["full_name"] = user_info.get("full_name")
                member["email"] = user_info.get("email")
                member["user_image"] = user_info.get("user_image")
        
        return success_response(
            data=members,
            message=f"Tìm thấy {len(members)} thành viên"
        )
        
    except Exception as e:
        frappe.log_error(f"Error getting project members: {str(e)}")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["POST"])
def update_member_role(project_id: str, member_user_id: str, new_role: str):
    """
    Cập nhật role của member trong project
    
    Args:
        project_id: ID của project
        member_user_id: User ID của member cần update
        new_role: Role mới (manager/member/viewer)
    
    Returns:
        Success message
    """
    try:
        user = frappe.session.user
        
        # Validate role
        valid_roles = ["manager", "member", "viewer"]
        if new_role not in valid_roles:
            return validation_error_response(
                "Role không hợp lệ",
                {"new_role": [f"Role phải là một trong: {', '.join(valid_roles)}"]}
            )
        
        # Chỉ owner mới có quyền thay đổi role
        role = get_user_project_role(project_id, user)
        if role != "owner":
            return forbidden_response("Chỉ chủ dự án mới có quyền thay đổi role")
        
        # Không thể thay đổi role của owner
        target_role = get_user_project_role(project_id, member_user_id)
        if target_role == "owner":
            return forbidden_response("Không thể thay đổi role của chủ dự án")
        
        # Cập nhật role
        member = frappe.get_doc("PM Project Member", {
            "project_id": project_id,
            "user_id": member_user_id
        })
        old_role = member.role
        member.role = new_role
        member.save()
        frappe.db.commit()
        
        # Log change
        log_project_change(project_id, "member_role_updated",
                          {"user_id": member_user_id, "role": old_role},
                          {"user_id": member_user_id, "role": new_role})
        
        return success_response(message=f"Đã cập nhật role thành {new_role}")
        
    except Exception as e:
        frappe.log_error(f"Error updating member role: {str(e)}")
        return error_response(str(e))


def log_project_change(project_id: str, action: str, old_value: dict, new_value: dict):
    """Helper function để log thay đổi project"""
    try:
        log = frappe.get_doc({
            "doctype": "PM Change Log",
            "project_id": project_id,
            "action": action,
            "actor_id": frappe.session.user,
            "target_type": "project",
            "target_id": project_id,
            "old_value": json.dumps(old_value) if old_value else None,
            "new_value": json.dumps(new_value) if new_value else None
        })
        log.insert(ignore_permissions=True)
    except Exception as e:
        frappe.log_error(f"Error logging project change: {str(e)}")

