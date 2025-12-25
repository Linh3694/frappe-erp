# Copyright (c) 2024, Wellspring and contributors
# For license information, please see license.txt

"""
API endpoints cho Resource upload/list/delete
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


def check_resource_permission(project_id: str, user: str) -> bool:
    """
    Kiểm tra user có quyền upload/delete resource không
    - owner: YES
    - manager: YES
    - member: YES
    - viewer: NO
    """
    role = get_user_project_role(project_id, user)
    return role is not None and role != "viewer"


def enrich_resource_data(resource: dict) -> dict:
    """Bổ sung thông tin cho resource"""
    # Enrich uploaded_by info
    if resource.get("uploaded_by"):
        uploader_info = frappe.db.get_value(
            "User",
            resource["uploaded_by"],
            ["full_name", "user_image"],
            as_dict=True
        )
        if uploader_info:
            resource["uploaded_by_full_name"] = uploader_info.get("full_name")
            resource["uploaded_by_image"] = uploader_info.get("user_image")
    
    # Format file size
    size = resource.get("file_size", 0)
    if size:
        if size < 1024:
            resource["file_size_formatted"] = f"{size} B"
        elif size < 1024 * 1024:
            resource["file_size_formatted"] = f"{size / 1024:.1f} KB"
        else:
            resource["file_size_formatted"] = f"{size / (1024 * 1024):.1f} MB"
    
    return resource


@frappe.whitelist(allow_guest=False)
def get_resources():
    """
    Lấy danh sách resources của project
    
    Args:
        project_id: ID của project (from query params)
        target_type: Filter theo loại (project/requirement/task, from query params)
        target_id: Filter theo target cụ thể (from query params)
    
    Returns:
        List resources
    """
    try:
        # Lấy params từ GET query params
        project_id = frappe.request.args.get("project_id") or frappe.form_dict.get("project_id")
        target_type = frappe.request.args.get("target_type") or frappe.form_dict.get("target_type")
        target_id = frappe.request.args.get("target_id") or frappe.form_dict.get("target_id")
        
        # Validate project_id
        if not project_id:
            return error_response("project_id is required", code="MISSING_PARAMETER")
        user = frappe.session.user
        
        # Kiểm tra quyền truy cập
        if not check_project_access(project_id, user):
            return forbidden_response("Bạn không có quyền truy cập dự án này")
        
        # Build filters
        filters = {"project_id": project_id}
        if target_type:
            filters["target_type"] = target_type
        if target_id:
            filters["target_id"] = target_id
        
        # Lấy resources
        resources = frappe.get_all(
            "PM Resource",
            filters=filters,
            fields=["name", "filename", "file_url", "file_type", "file_size",
                   "target_type", "target_id", "uploaded_by", "creation"],
            order_by="creation desc"
        )
        
        # Enrich data
        for res in resources:
            enrich_resource_data(res)
        
        return success_response(
            data=resources,
            message=f"Tìm thấy {len(resources)} tài nguyên"
        )
        
    except Exception as e:
        frappe.log_error(f"Error getting resources: {str(e)}")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["POST"])
def upload_resource():
    """
    Upload resource mới
    
    Form data:
        project_id: ID project (required)
        target_type: Loại target (project/requirement/task)
        target_id: ID của target
        file: File upload (required)
    
    Returns:
        Resource vừa upload
    """
    try:
        user = frappe.session.user
        
        # Lấy form data từ multipart/form-data (hỗ trợ cả request.form và form_dict)
        project_id = frappe.request.form.get("project_id") or frappe.form_dict.get("project_id")
        target_type = frappe.request.form.get("target_type") or frappe.form_dict.get("target_type") or "project"
        target_id = frappe.request.form.get("target_id") or frappe.form_dict.get("target_id")
        
        # Validate required fields
        if not project_id:
            return validation_error_response(
                "Thiếu thông tin bắt buộc",
                {"project_id": ["Project ID là bắt buộc"]}
            )
        
        # Kiểm tra project tồn tại
        if not frappe.db.exists("PM Project", project_id):
            return not_found_response(f"Project {project_id} không tồn tại")
        
        # Kiểm tra quyền
        if not check_resource_permission(project_id, user):
            return forbidden_response("Bạn không có quyền upload tài nguyên")
        
        # Validate target
        valid_target_types = ["project", "requirement", "task"]
        if target_type not in valid_target_types:
            return validation_error_response(
                "Target type không hợp lệ",
                {"target_type": [f"Target type phải là một trong: {', '.join(valid_target_types)}"]}
            )
        
        # Nếu target_type là project thì target_id = project_id
        if target_type == "project":
            target_id = project_id
        
        # Kiểm tra target tồn tại
        if target_type == "requirement":
            if not frappe.db.exists("PM Requirement", target_id):
                return not_found_response(f"Requirement {target_id} không tồn tại")
        elif target_type == "task":
            if not frappe.db.exists("PM Task", target_id):
                return not_found_response(f"Task {target_id} không tồn tại")
        
        # Xử lý file upload
        files = frappe.request.files
        if not files or "file" not in files:
            return validation_error_response(
                "Thiếu file",
                {"file": ["Vui lòng chọn file để upload"]}
            )
        
        uploaded_file = files["file"]
        filename = uploaded_file.filename
        file_content = uploaded_file.read()
        file_type = uploaded_file.content_type or ""
        
        # Bước 1: Upload file trước (không attach vào doctype nào)
        file_doc = frappe.get_doc({
            "doctype": "File",
            "file_name": filename,
            "is_private": 1,
            "content": file_content
        })
        file_doc.insert()
        
        # Bước 2: Tạo PM Resource với file_url từ file đã upload
        resource = frappe.get_doc({
            "doctype": "PM Resource",
            "project_id": project_id,
            "target_type": target_type,
            "target_id": target_id,
            "filename": filename,
            "file_url": file_doc.file_url,
            "file_type": file_type,
            "file_size": file_doc.file_size or 0,
            "uploaded_by": user
        })
        resource.insert()
        
        # Bước 3: Cập nhật file để attach vào PM Resource
        file_doc.attached_to_doctype = "PM Resource"
        file_doc.attached_to_name = resource.name
        file_doc.save()
        
        frappe.db.commit()
        
        # Enrich và return
        res_data = resource.as_dict()
        enrich_resource_data(res_data)
        
        return single_item_response(res_data, "Upload tài nguyên thành công")
        
    except Exception as e:
        frappe.log_error(f"Error uploading resource: {str(e)}")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["POST"])
def delete_resource():
    """
    Xóa resource
    
    Query params:
        resource_id: ID của resource (required)
    
    Returns:
        Success message
    """
    try:
        user = frappe.session.user
        resource_id = frappe.form_dict.get("resource_id") or frappe.local.request.args.get("resource_id")
        
        if not resource_id:
            return validation_error_response("Resource ID là bắt buộc", {"resource_id": ["Resource ID không được để trống"]})
        
        # Kiểm tra resource tồn tại
        if not frappe.db.exists("PM Resource", resource_id):
            return not_found_response(f"Resource {resource_id} không tồn tại")
        
        resource = frappe.get_doc("PM Resource", resource_id)
        
        # Kiểm tra quyền (chỉ uploader hoặc owner/manager mới được xóa)
        role = get_user_project_role(resource.project_id, user)
        if resource.uploaded_by != user and role not in ["owner", "manager"]:
            return forbidden_response("Bạn không có quyền xóa tài nguyên này")
        
        # Xóa file trong Frappe
        if resource.file_url:
            file_doc = frappe.db.get_value(
                "File",
                {"file_url": resource.file_url},
                "name"
            )
            if file_doc:
                frappe.delete_doc("File", file_doc, force=True)
        
        # Xóa resource
        frappe.delete_doc("PM Resource", resource_id, force=True)
        frappe.db.commit()
        
        return success_response(message="Xóa tài nguyên thành công")
        
    except Exception as e:
        frappe.log_error(f"Error deleting resource: {str(e)}")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def get_resource():
    """
    Lấy chi tiết một resource
    
    Query params:
        resource_id: ID của resource (required)
    
    Returns:
        Chi tiết resource
    """
    try:
        user = frappe.session.user
        resource_id = frappe.form_dict.get("resource_id") or frappe.local.request.args.get("resource_id")
        
        if not resource_id:
            return validation_error_response("Resource ID là bắt buộc", {"resource_id": ["Resource ID không được để trống"]})
        
        # Kiểm tra resource tồn tại
        if not frappe.db.exists("PM Resource", resource_id):
            return not_found_response(f"Resource {resource_id} không tồn tại")
        
        resource = frappe.get_doc("PM Resource", resource_id).as_dict()
        
        # Kiểm tra quyền truy cập
        if not check_project_access(resource["project_id"], user):
            return forbidden_response("Bạn không có quyền truy cập tài nguyên này")
        
        # Enrich data
        enrich_resource_data(resource)
        
        return single_item_response(resource, "Lấy thông tin tài nguyên thành công")
        
    except Exception as e:
        frappe.log_error(f"Error getting resource: {str(e)}")
        return error_response(str(e))

