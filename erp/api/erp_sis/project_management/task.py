# Copyright (c) 2024, Wellspring and contributors
# For license information, please see license.txt

"""
API endpoints cho Task CRUD và Kanban operations
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


def check_task_permission(project_id: str, user: str) -> bool:
    """
    Kiểm tra user có quyền tạo/sửa/xóa/move task không
    - owner: YES
    - manager: YES  
    - member: YES
    - viewer: NO
    """
    role = get_user_project_role(project_id, user)
    return role is not None and role != "viewer"


def enrich_task_data(task: dict) -> dict:
    """Bổ sung thông tin cho task"""
    # Lấy assignees
    assignees = frappe.get_all(
        "PM Task Assignee",
        filters={"task_id": task["name"]},
        fields=["name", "user_id", "assigned_at", "assigned_by"]
    )
    
    # Enrich assignee info
    for assignee in assignees:
        user_info = frappe.db.get_value(
            "User",
            assignee["user_id"],
            ["full_name", "user_image"],
            as_dict=True
        )
        if user_info:
            assignee["full_name"] = user_info.get("full_name")
            assignee["user_image"] = user_info.get("user_image")
    
    task["assignees"] = assignees
    
    # Enrich created_by info
    if task.get("created_by"):
        creator_info = frappe.db.get_value(
            "User",
            task["created_by"],
            ["full_name", "user_image"],
            as_dict=True
        )
        if creator_info:
            task["created_by_full_name"] = creator_info.get("full_name")
            task["created_by_image"] = creator_info.get("user_image")
    
    # Thêm comment count
    task["comment_count"] = frappe.db.count("PM Task Comment", {"task_id": task["name"]})
    
    # Thêm attachment/resource count
    task["attachment_count"] = frappe.db.count("PM Resource", {
        "target_type": "task",
        "target_id": task["name"]
    })
    
    return task


def log_task_change(project_id: str, task_id: str, action: str, old_value: dict, new_value: dict):
    """Helper function để log thay đổi task"""
    try:
        log = frappe.get_doc({
            "doctype": "PM Change Log",
            "project_id": project_id,
            "action": action,
            "actor_id": frappe.session.user,
            "target_type": "task",
            "target_id": task_id,
            "old_value": json.dumps(old_value) if old_value else None,
            "new_value": json.dumps(new_value) if new_value else None
        })
        log.insert(ignore_permissions=True)
    except Exception as e:
        frappe.log_error(f"Error logging task change: {str(e)}")


@frappe.whitelist(allow_guest=False)
def get_board_tasks():
    """
    Lấy danh sách tasks cho Kanban board
    
    Args:
        project_id: ID của project (from query params)
        status: Filter theo status (optional, from query params)
    
    Returns:
        Tasks grouped by status
    """
    try:
        user = frappe.session.user
        
        # Lấy params từ GET query params
        project_id = frappe.request.args.get("project_id") or frappe.form_dict.get("project_id")
        status = frappe.request.args.get("status") or frappe.form_dict.get("status")
        
        # Validate project_id
        if not project_id:
            return error_response("project_id is required", code="MISSING_PARAMETER")
        
        # Kiểm tra quyền truy cập project
        if not check_project_access(project_id, user):
            return forbidden_response("Bạn không có quyền truy cập dự án này")
        
        # Build filters
        filters = {"project_id": project_id}
        if status:
            filters["status"] = status
        
        # Lấy tasks
        tasks = frappe.get_all(
            "PM Task",
            filters=filters,
            fields=["name", "title", "description", "status", "priority",
                   "created_by", "due_date", "tags", "order_index",
                   "creation", "modified"],
            order_by="order_index asc, modified desc"
        )
        
        # Enrich data
        for task in tasks:
            enrich_task_data(task)
        
        # Group by status
        grouped = {
            "backlog": [],
            "todo": [],
            "in_progress": [],
            "review": [],
            "done": []
        }
        
        for task in tasks:
            task_status = task.get("status", "backlog")
            if task_status in grouped:
                grouped[task_status].append(task)
        
        return success_response(
            data={
                "tasks": tasks,
                "grouped": grouped,
                "total": len(tasks)
            },
            message=f"Tìm thấy {len(tasks)} task"
        )
        
    except Exception as e:
        frappe.log_error(f"Error getting board tasks: {str(e)}")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def get_task(task_id: str):
    """
    Lấy chi tiết một task
    
    Args:
        task_id: ID của task
    
    Returns:
        Chi tiết task
    """
    try:
        user = frappe.session.user
        
        # Kiểm tra task tồn tại
        if not frappe.db.exists("PM Task", task_id):
            return not_found_response(f"Task {task_id} không tồn tại")
        
        task = frappe.get_doc("PM Task", task_id).as_dict()
        
        # Kiểm tra quyền truy cập project
        if not check_project_access(task["project_id"], user):
            return forbidden_response("Bạn không có quyền truy cập task này")
        
        # Enrich data
        enrich_task_data(task)
        
        # Lấy project title
        task["project_title"] = frappe.db.get_value(
            "PM Project", task["project_id"], "title"
        )
        
        return single_item_response(task, "Lấy thông tin task thành công")
        
    except Exception as e:
        frappe.log_error(f"Error getting task: {str(e)}")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["POST"])
def create_task():
    """
    Tạo task mới
    
    Payload:
        project_id: ID project (required)
        title: Tiêu đề task (required)
        description: Mô tả
        status: Trạng thái (default: backlog)
        priority: Độ ưu tiên (default: medium)
        due_date: Hạn hoàn thành
        tags: Tags (comma-separated)
        assignee_ids: List user IDs để assign
    
    Returns:
        Task vừa tạo
    """
    try:
        user = frappe.session.user
        data = json.loads(frappe.request.data) if frappe.request.data else {}
        
        # Validate required fields
        errors = {}
        if not data.get("project_id"):
            errors["project_id"] = ["Project ID là bắt buộc"]
        if not data.get("title"):
            errors["title"] = ["Tiêu đề task là bắt buộc"]
        
        if errors:
            return validation_error_response("Thiếu thông tin bắt buộc", errors)
        
        project_id = data.get("project_id")
        
        # Kiểm tra project tồn tại
        if not frappe.db.exists("PM Project", project_id):
            return not_found_response(f"Project {project_id} không tồn tại")
        
        # Kiểm tra quyền tạo task
        if not check_task_permission(project_id, user):
            return forbidden_response("Bạn không có quyền tạo task trong dự án này")
        
        # Validate status
        valid_statuses = ["backlog", "todo", "in_progress", "review", "done"]
        status = data.get("status", "backlog")
        if status not in valid_statuses:
            return validation_error_response(
                "Status không hợp lệ",
                {"status": [f"Status phải là một trong: {', '.join(valid_statuses)}"]}
            )
        
        # Validate priority
        valid_priorities = ["low", "medium", "high", "critical"]
        priority = data.get("priority", "medium")
        if priority not in valid_priorities:
            return validation_error_response(
                "Priority không hợp lệ",
                {"priority": [f"Priority phải là một trong: {', '.join(valid_priorities)}"]}
            )
        
        # Tính order_index
        max_order = frappe.db.sql("""
            SELECT MAX(order_index) as max_order
            FROM `tabPM Task`
            WHERE project_id = %s AND status = %s
        """, (project_id, status), as_dict=True)
        
        order_index = 0
        if max_order and max_order[0].max_order is not None:
            order_index = max_order[0].max_order + 1
        
        # Tạo task
        task = frappe.get_doc({
            "doctype": "PM Task",
            "project_id": project_id,
            "title": data.get("title"),
            "description": data.get("description"),
            "status": status,
            "priority": priority,
            "created_by": user,
            "due_date": data.get("due_date"),
            "tags": data.get("tags"),
            "order_index": order_index
        })
        task.insert()
        
        # Tạo assignees nếu có
        assignee_ids = data.get("assignee_ids", [])
        for assignee_id in assignee_ids:
            if frappe.db.exists("User", assignee_id):
                # Kiểm tra assignee là member của project
                if get_user_project_role(project_id, assignee_id):
                    assignee = frappe.get_doc({
                        "doctype": "PM Task Assignee",
                        "task_id": task.name,
                        "user_id": assignee_id,
                        "assigned_by": user
                    })
                    assignee.insert()
        
        frappe.db.commit()
        
        # Log change (đã được xử lý trong pm_task.py after_insert)
        
        # Enrich và return
        task_data = task.as_dict()
        enrich_task_data(task_data)
        
        return single_item_response(task_data, "Tạo task thành công")
        
    except Exception as e:
        frappe.log_error(f"Error creating task: {str(e)}")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["POST"])
def update_task():
    """
    Cập nhật thông tin task
    
    Query params:
        task_id: ID của task (required)
    
    Payload:
        title: Tiêu đề
        description: Mô tả
        status: Trạng thái
        priority: Độ ưu tiên
        due_date: Hạn hoàn thành
        tags: Tags
        assignee_ids: Danh sách user IDs để gán task
    
    Returns:
        Task sau khi cập nhật
    """
    try:
        user = frappe.session.user
        # Đọc task_id từ query parameters (hỗ trợ cả form_dict và request.args)
        task_id = frappe.form_dict.get("task_id") or frappe.local.request.args.get("task_id")
        
        if not task_id:
            return validation_error_response("Task ID là bắt buộc", {"task_id": ["Task ID không được để trống"]})
        
        data = json.loads(frappe.request.data) if frappe.request.data else {}
        
        # Kiểm tra task tồn tại
        if not frappe.db.exists("PM Task", task_id):
            return not_found_response(f"Task {task_id} không tồn tại")
        
        task = frappe.get_doc("PM Task", task_id)
        
        # Kiểm tra quyền
        if not check_task_permission(task.project_id, user):
            return forbidden_response("Bạn không có quyền chỉnh sửa task này")
        
        # Lưu old values
        old_values = {
            "title": task.title,
            "description": task.description,
            "status": task.status,
            "priority": task.priority,
            "due_date": str(task.due_date) if task.due_date else None,
            "tags": task.tags
        }
        
        # Cập nhật fields
        if "title" in data:
            task.title = data["title"]
        if "description" in data:
            task.description = data["description"]
        if "status" in data:
            valid_statuses = ["backlog", "todo", "in_progress", "review", "done"]
            if data["status"] in valid_statuses:
                task.status = data["status"]
        if "priority" in data:
            valid_priorities = ["low", "medium", "high", "critical"]
            if data["priority"] in valid_priorities:
                task.priority = data["priority"]
        if "due_date" in data:
            task.due_date = data["due_date"]
        if "tags" in data:
            task.tags = data["tags"]
        
        # Cập nhật assignees nếu có trong payload
        if "assignee_ids" in data:
            new_assignee_ids = data.get("assignee_ids", [])
            
            # Lấy danh sách assignees hiện tại
            current_assignees = frappe.get_all(
                "PM Task Assignee",
                filters={"task_id": task_id},
                pluck="user_id"
            )
            
            # Tìm assignees cần xóa
            to_remove = set(current_assignees) - set(new_assignee_ids)
            for user_id in to_remove:
                assignee_name = frappe.db.get_value(
                    "PM Task Assignee",
                    {"task_id": task_id, "user_id": user_id}
                )
                if assignee_name:
                    frappe.delete_doc("PM Task Assignee", assignee_name, force=True)
            
            # Tìm assignees cần thêm
            to_add = set(new_assignee_ids) - set(current_assignees)
            for user_id in to_add:
                if frappe.db.exists("User", user_id):
                    # Kiểm tra user là member của project
                    if get_user_project_role(task.project_id, user_id):
                        assignee = frappe.get_doc({
                            "doctype": "PM Task Assignee",
                            "task_id": task_id,
                            "user_id": user_id,
                            "assigned_by": user
                        })
                        assignee.insert()
        
        task.save()
        frappe.db.commit()
        
        # Enrich và return
        task_data = task.as_dict()
        enrich_task_data(task_data)
        
        return single_item_response(task_data, "Cập nhật task thành công")
        
    except Exception as e:
        frappe.log_error(f"Error updating task: {str(e)}")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["POST"])
def move_task():
    """
    Di chuyển task (drag-drop trong Kanban)
    
    Payload:
        task_id: ID của task (required)
        from_status: Trạng thái cũ (required - để log chính xác)
        to_status: Trạng thái mới (required)
        new_order_index: Vị trí mới trong column (required)
    
    Returns:
        Task sau khi di chuyển
    """
    try:
        user = frappe.session.user
        data = json.loads(frappe.request.data) if frappe.request.data else {}
        
        # Validate required fields
        errors = {}
        if not data.get("task_id"):
            errors["task_id"] = ["Task ID là bắt buộc"]
        if not data.get("from_status"):
            errors["from_status"] = ["From status là bắt buộc"]
        if not data.get("to_status"):
            errors["to_status"] = ["To status là bắt buộc"]
        if data.get("new_order_index") is None:
            errors["new_order_index"] = ["New order index là bắt buộc"]
        
        if errors:
            return validation_error_response("Thiếu thông tin bắt buộc", errors)
        
        task_id = data.get("task_id")
        from_status = data.get("from_status")
        to_status = data.get("to_status")
        new_order_index = int(data.get("new_order_index"))
        
        # Kiểm tra task tồn tại
        if not frappe.db.exists("PM Task", task_id):
            return not_found_response(f"Task {task_id} không tồn tại")
        
        task = frappe.get_doc("PM Task", task_id)
        
        # Kiểm tra quyền move
        if not check_task_permission(task.project_id, user):
            return forbidden_response("Bạn không có quyền di chuyển task này")
        
        # Validate statuses
        valid_statuses = ["backlog", "todo", "in_progress", "review", "done"]
        if from_status not in valid_statuses or to_status not in valid_statuses:
            return validation_error_response(
                "Status không hợp lệ",
                {"status": [f"Status phải là một trong: {', '.join(valid_statuses)}"]}
            )
        
        # Lưu old values
        old_values = {
            "status": task.status,
            "order_index": task.order_index
        }
        
        # Nếu chuyển sang column khác
        if from_status != to_status:
            # Cập nhật order_index của các task khác trong column mới
            frappe.db.sql("""
                UPDATE `tabPM Task`
                SET order_index = order_index + 1
                WHERE project_id = %s 
                AND status = %s 
                AND order_index >= %s
                AND name != %s
            """, (task.project_id, to_status, new_order_index, task_id))
            
            # Cập nhật order_index của các task trong column cũ
            frappe.db.sql("""
                UPDATE `tabPM Task`
                SET order_index = order_index - 1
                WHERE project_id = %s 
                AND status = %s 
                AND order_index > %s
            """, (task.project_id, from_status, task.order_index))
        else:
            # Di chuyển trong cùng column
            if new_order_index > task.order_index:
                # Di chuyển xuống
                frappe.db.sql("""
                    UPDATE `tabPM Task`
                    SET order_index = order_index - 1
                    WHERE project_id = %s 
                    AND status = %s 
                    AND order_index > %s 
                    AND order_index <= %s
                    AND name != %s
                """, (task.project_id, to_status, task.order_index, new_order_index, task_id))
            else:
                # Di chuyển lên
                frappe.db.sql("""
                    UPDATE `tabPM Task`
                    SET order_index = order_index + 1
                    WHERE project_id = %s 
                    AND status = %s 
                    AND order_index >= %s 
                    AND order_index < %s
                    AND name != %s
                """, (task.project_id, to_status, new_order_index, task.order_index, task_id))
        
        # Cập nhật task
        task.status = to_status
        task.order_index = new_order_index
        task.save()
        frappe.db.commit()
        
        # Log change
        log_task_change(task.project_id, task_id, "task_moved", old_values, {
            "status": to_status,
            "order_index": new_order_index,
            "from_status": from_status
        })
        
        # Enrich và return
        task_data = task.as_dict()
        enrich_task_data(task_data)
        
        return single_item_response(task_data, "Di chuyển task thành công")
        
    except Exception as e:
        frappe.log_error(f"Error moving task: {str(e)}")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["POST"])
def delete_task():
    """
    Xóa task
    
    Query params:
        task_id: ID của task (required)
    
    Returns:
        Success message
    """
    try:
        user = frappe.session.user
        # Đọc task_id từ query parameters (hỗ trợ cả form_dict và request.args)
        task_id = frappe.form_dict.get("task_id") or frappe.local.request.args.get("task_id")
        
        if not task_id:
            return validation_error_response("Task ID là bắt buộc", {"task_id": ["Task ID không được để trống"]})
        
        # Kiểm tra task tồn tại
        if not frappe.db.exists("PM Task", task_id):
            return not_found_response(f"Task {task_id} không tồn tại")
        
        task = frappe.get_doc("PM Task", task_id)
        project_id = task.project_id
        
        # Kiểm tra quyền
        if not check_task_permission(project_id, user):
            return forbidden_response("Bạn không có quyền xóa task này")
        
        # Lưu info để log
        task_info = {
            "title": task.title,
            "status": task.status,
            "priority": task.priority
        }
        
        # Xóa assignees trước
        frappe.db.delete("PM Task Assignee", {"task_id": task_id})
        
        # Xóa resources liên quan
        frappe.db.delete("PM Resource", {"target_type": "task", "target_id": task_id})
        
        # Xóa task
        frappe.delete_doc("PM Task", task_id, force=True)
        frappe.db.commit()
        
        # Log change
        log_task_change(project_id, task_id, "task_deleted", task_info, None)
        
        return success_response(message="Xóa task thành công")
        
    except Exception as e:
        frappe.log_error(f"Error deleting task: {str(e)}")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["POST"])
def assign_task(task_id: str, user_ids: list = None):
    """
    Gán users vào task
    
    Args:
        task_id: ID của task
        user_ids: List user IDs để assign (từ request body)
    
    Returns:
        Task sau khi assign
    """
    try:
        user = frappe.session.user
        
        if user_ids is None:
            data = json.loads(frappe.request.data) if frappe.request.data else {}
            user_ids = data.get("user_ids", [])
        
        # Kiểm tra task tồn tại
        if not frappe.db.exists("PM Task", task_id):
            return not_found_response(f"Task {task_id} không tồn tại")
        
        task = frappe.get_doc("PM Task", task_id)
        
        # Kiểm tra quyền
        if not check_task_permission(task.project_id, user):
            return forbidden_response("Bạn không có quyền assign task này")
        
        assigned = []
        skipped = []
        
        for user_id in user_ids:
            # Kiểm tra user tồn tại
            if not frappe.db.exists("User", user_id):
                skipped.append({"user_id": user_id, "reason": "User không tồn tại"})
                continue
            
            # Kiểm tra user là member của project
            if not get_user_project_role(task.project_id, user_id):
                skipped.append({"user_id": user_id, "reason": "User không phải member của project"})
                continue
            
            # Kiểm tra đã assign chưa
            existing = frappe.db.exists("PM Task Assignee", {
                "task_id": task_id,
                "user_id": user_id
            })
            
            if existing:
                skipped.append({"user_id": user_id, "reason": "Đã được assign"})
                continue
            
            # Tạo assignee
            assignee = frappe.get_doc({
                "doctype": "PM Task Assignee",
                "task_id": task_id,
                "user_id": user_id,
                "assigned_by": user
            })
            assignee.insert()
            assigned.append(user_id)
        
        frappe.db.commit()
        
        # Log change
        if assigned:
            log_task_change(task.project_id, task_id, "assignees_added", None, {
                "added_users": assigned
            })
        
        # Enrich và return
        task_data = task.as_dict()
        enrich_task_data(task_data)
        
        return success_response(
            data={
                "task": task_data,
                "assigned": assigned,
                "skipped": skipped
            },
            message=f"Đã assign {len(assigned)} users"
        )
        
    except Exception as e:
        frappe.log_error(f"Error assigning task: {str(e)}")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["POST"])
def unassign_task(task_id: str, user_id: str):
    """
    Bỏ assign user khỏi task
    
    Args:
        task_id: ID của task
        user_id: User ID cần bỏ assign
    
    Returns:
        Success message
    """
    try:
        user = frappe.session.user
        
        # Kiểm tra task tồn tại
        if not frappe.db.exists("PM Task", task_id):
            return not_found_response(f"Task {task_id} không tồn tại")
        
        task = frappe.get_doc("PM Task", task_id)
        
        # Kiểm tra quyền
        if not check_task_permission(task.project_id, user):
            return forbidden_response("Bạn không có quyền thực hiện hành động này")
        
        # Tìm và xóa assignee
        assignee = frappe.db.get_value(
            "PM Task Assignee",
            {"task_id": task_id, "user_id": user_id},
            "name"
        )
        
        if not assignee:
            return not_found_response(f"User {user_id} không được assign vào task này")
        
        frappe.delete_doc("PM Task Assignee", assignee, force=True)
        frappe.db.commit()
        
        # Log change
        log_task_change(task.project_id, task_id, "assignee_removed", 
                       {"user_id": user_id}, None)
        
        return success_response(message="Đã bỏ assign thành công")
        
    except Exception as e:
        frappe.log_error(f"Error unassigning task: {str(e)}")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def search_tasks():
    """
    Tìm kiếm và filter tasks
    
    Args:
        project_id: ID của project (from query params)
        query: Từ khóa tìm kiếm (title, description)
        status: Filter theo status
        priority: Filter theo priority
        assignee_id: Filter theo assignee
        has_due_date: Filter task có due_date (true/false)
        overdue: Filter task quá hạn (true/false)
    
    Returns:
        List tasks matching filters
    """
    try:
        user = frappe.session.user
        
        # Lấy params từ GET query params
        project_id = frappe.request.args.get("project_id") or frappe.form_dict.get("project_id")
        query = frappe.request.args.get("query") or frappe.form_dict.get("query")
        status = frappe.request.args.get("status") or frappe.form_dict.get("status")
        priority = frappe.request.args.get("priority") or frappe.form_dict.get("priority")
        assignee_id = frappe.request.args.get("assignee_id") or frappe.form_dict.get("assignee_id")
        has_due_date = frappe.request.args.get("has_due_date") or frappe.form_dict.get("has_due_date")
        overdue = frappe.request.args.get("overdue") or frappe.form_dict.get("overdue")
        
        # Validate project_id
        if not project_id:
            return error_response("project_id is required", code="MISSING_PARAMETER")
        
        # Kiểm tra quyền
        if not check_project_access(project_id, user):
            return forbidden_response("Bạn không có quyền truy cập dự án này")
        
        # Build SQL query
        conditions = ["project_id = %s"]
        values = [project_id]
        
        if query:
            conditions.append("(title LIKE %s OR description LIKE %s)")
            search_term = f"%{query}%"
            values.extend([search_term, search_term])
        
        if status:
            conditions.append("status = %s")
            values.append(status)
        
        if priority:
            conditions.append("priority = %s")
            values.append(priority)
        
        if has_due_date == "true":
            conditions.append("due_date IS NOT NULL")
        elif has_due_date == "false":
            conditions.append("due_date IS NULL")
        
        if overdue == "true":
            conditions.append("due_date < CURDATE() AND status != 'done'")
        
        where_clause = " AND ".join(conditions)
        
        # Query tasks
        tasks = frappe.db.sql(f"""
            SELECT name, title, description, status, priority,
                   created_by, due_date, tags, order_index,
                   creation, modified
            FROM `tabPM Task`
            WHERE {where_clause}
            ORDER BY order_index ASC, modified DESC
        """, values, as_dict=True)
        
        # Filter by assignee (cần query riêng vì là child table)
        if assignee_id:
            assigned_task_ids = frappe.get_all(
                "PM Task Assignee",
                filters={"user_id": assignee_id},
                pluck="task_id"
            )
            tasks = [t for t in tasks if t["name"] in assigned_task_ids]
        
        # Enrich data
        for task in tasks:
            enrich_task_data(task)
        
        return success_response(
            data=tasks,
            message=f"Tìm thấy {len(tasks)} task"
        )
        
    except Exception as e:
        frappe.log_error(f"Error searching tasks: {str(e)}")
        return error_response(str(e))


# ==================== TASK COMMENT APIs ====================

@frappe.whitelist()
def get_task_comments(task_id: str):
    """
    Lấy tất cả comments của một task
    
    Returns: List comments với thông tin người tạo
    """
    try:
        # Kiểm tra task tồn tại
        task = frappe.get_doc("PM Task", task_id)
        
        # Kiểm tra quyền đọc task (phải là member của project)
        if not check_project_access(task.project_id, frappe.session.user):
            return forbidden_response("Bạn không có quyền xem task này")
        
        # Lấy comments
        comments = frappe.get_all(
            "PM Task Comment",
            filters={"task_id": task_id},
            fields=["name", "task_id", "comment_text", "created_by", "creation_date", "creation", "modified"],
            order_by="creation DESC"
        )
        
        # Enrich with user info
        for comment in comments:
            user_info = frappe.db.get_value(
                "User",
                comment["created_by"],
                ["full_name", "user_image"],
                as_dict=True
            )
            if user_info:
                comment["created_by_full_name"] = user_info.get("full_name")
                comment["created_by_image"] = user_info.get("user_image")
        
        return success_response(
            data=comments,
            message=f"Tìm thấy {len(comments)} comment"
        )
        
    except frappe.DoesNotExistError:
        return not_found_response("Task")
    except Exception as e:
        frappe.log_error(f"Error getting task comments: {str(e)}")
        return error_response(str(e))


@frappe.whitelist()
def create_task_comment(task_id: str, comment_text: str):
    """
    Tạo comment mới cho task
    
    Args:
        task_id: ID của task
        comment_text: Nội dung comment
        
    Returns: Comment vừa tạo
    """
    try:
        # Validate input
        if not comment_text or not comment_text.strip():
            return validation_error_response("Nội dung comment không được để trống")
        
        # Kiểm tra task tồn tại
        task = frappe.get_doc("PM Task", task_id)
        
        # Kiểm tra quyền (phải là member của project)
        if not check_project_access(task.project_id, frappe.session.user):
            return forbidden_response("Bạn không có quyền comment vào task này")
        
        # Tạo comment
        comment = frappe.get_doc({
            "doctype": "PM Task Comment",
            "task_id": task_id,
            "comment_text": comment_text.strip(),
        })
        comment.insert()
        frappe.db.commit()
        
        # Enrich with user info
        user_info = frappe.db.get_value(
            "User",
            comment.created_by,
            ["full_name", "user_image"],
            as_dict=True
        )
        
        result = {
            "name": comment.name,
            "task_id": comment.task_id,
            "comment_text": comment.comment_text,
            "created_by": comment.created_by,
            "creation_date": comment.creation_date,
            "creation": comment.creation,
            "modified": comment.modified,
        }
        
        if user_info:
            result["created_by_full_name"] = user_info.get("full_name")
            result["created_by_image"] = user_info.get("user_image")
        
        return single_item_response(result, "Comment đã được tạo")
        
    except frappe.DoesNotExistError:
        return not_found_response("Task")
    except Exception as e:
        frappe.log_error(f"Error creating task comment: {str(e)}")
        return error_response(str(e))


@frappe.whitelist()
def update_task_comment(comment_id: str, comment_text: str):
    """
    Cập nhật comment
    
    Args:
        comment_id: ID của comment
        comment_text: Nội dung mới
        
    Returns: Comment đã cập nhật
    """
    try:
        # Validate input
        if not comment_text or not comment_text.strip():
            return validation_error_response("Nội dung comment không được để trống")
        
        # Lấy comment
        comment = frappe.get_doc("PM Task Comment", comment_id)
        
        # Kiểm tra quyền (chỉ người tạo mới được sửa)
        if comment.created_by != frappe.session.user:
            return forbidden_response("Bạn chỉ có thể sửa comment của mình")
        
        # Cập nhật
        comment.comment_text = comment_text.strip()
        comment.save()
        frappe.db.commit()
        
        # Enrich with user info
        user_info = frappe.db.get_value(
            "User",
            comment.created_by,
            ["full_name", "user_image"],
            as_dict=True
        )
        
        result = {
            "name": comment.name,
            "task_id": comment.task_id,
            "comment_text": comment.comment_text,
            "created_by": comment.created_by,
            "creation_date": comment.creation_date,
            "creation": comment.creation,
            "modified": comment.modified,
        }
        
        if user_info:
            result["created_by_full_name"] = user_info.get("full_name")
            result["created_by_image"] = user_info.get("user_image")
        
        return single_item_response(result, "Comment đã được cập nhật")
        
    except frappe.DoesNotExistError:
        return not_found_response("Comment")
    except Exception as e:
        frappe.log_error(f"Error updating task comment: {str(e)}")
        return error_response(str(e))


@frappe.whitelist()
def delete_task_comment(comment_id: str):
    """
    Xóa comment
    
    Args:
        comment_id: ID của comment
        
    Returns: Success message
    """
    try:
        # Lấy comment
        comment = frappe.get_doc("PM Task Comment", comment_id)
        
        # Kiểm tra quyền (chỉ người tạo hoặc owner/manager của project mới được xóa)
        task = frappe.get_doc("PM Task", comment.task_id)
        user_role = get_user_project_role(task.project_id, frappe.session.user)
        
        can_delete = (
            comment.created_by == frappe.session.user or
            user_role in ["owner", "manager"]
        )
        
        if not can_delete:
            return forbidden_response("Bạn không có quyền xóa comment này")
        
        # Xóa comment
        frappe.delete_doc("PM Task Comment", comment_id)
        frappe.db.commit()
        
        return success_response(message="Comment đã được xóa")
        
    except frappe.DoesNotExistError:
        return not_found_response("Comment")
    except Exception as e:
        frappe.log_error(f"Error deleting task comment: {str(e)}")
        return error_response(str(e))


@frappe.whitelist()
def get_task_comment_count(task_id: str):
    """
    Lấy số lượng comments của task
    
    Returns: {"count": int}
    """
    try:
        count = frappe.db.count("PM Task Comment", {"task_id": task_id})
        return success_response(data={"count": count})
        
    except Exception as e:
        frappe.log_error(f"Error getting comment count: {str(e)}")
        return error_response(str(e))

