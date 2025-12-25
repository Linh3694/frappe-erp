# Copyright (c) 2024, Wellspring and contributors
# For license information, please see license.txt

"""
API endpoints cho Change Log
"""

import frappe
from frappe import _
import json
from erp.utils.api_response import (
    success_response,
    error_response,
    not_found_response,
    forbidden_response
)
from .project import check_project_access


def enrich_log_data(log: dict) -> dict:
    """Bổ sung thông tin cho change log"""
    # Enrich actor info
    if log.get("actor_id"):
        actor_info = frappe.db.get_value(
            "User",
            log["actor_id"],
            ["full_name", "user_image"],
            as_dict=True
        )
        if actor_info:
            log["actor_full_name"] = actor_info.get("full_name")
            log["actor_image"] = actor_info.get("user_image")
    
    # Parse JSON values
    if log.get("old_value"):
        try:
            log["old_value_parsed"] = json.loads(log["old_value"])
        except:
            log["old_value_parsed"] = log["old_value"]
    
    if log.get("new_value"):
        try:
            log["new_value_parsed"] = json.loads(log["new_value"])
        except:
            log["new_value_parsed"] = log["new_value"]
    
    # Tạo description đọc được
    log["description"] = format_log_description(log)
    
    return log


def format_log_description(log: dict) -> str:
    """Tạo mô tả đọc được cho log entry"""
    action = log.get("action", "")
    actor = log.get("actor_full_name", log.get("actor_id", "Unknown"))
    target_type = log.get("target_type", "")
    
    descriptions = {
        "project_created": f"{actor} đã tạo dự án",
        "project_updated": f"{actor} đã cập nhật thông tin dự án",
        "project_archived": f"{actor} đã archive dự án",
        "project_restored": f"{actor} đã khôi phục dự án",
        "member_invited": f"{actor} đã mời thành viên mới",
        "member_joined": f"{actor} đã tham gia dự án",
        "member_left": f"{actor} đã rời dự án",
        "member_removed": f"{actor} đã xóa thành viên khỏi dự án",
        "member_role_updated": f"{actor} đã thay đổi vai trò thành viên",
        "ownership_transferred": f"{actor} đã chuyển quyền sở hữu dự án",
        "task_created": f"{actor} đã tạo task mới",
        "task_updated": f"{actor} đã cập nhật task",
        "task_moved": f"{actor} đã di chuyển task",
        "task_deleted": f"{actor} đã xóa task",
        "assignees_added": f"{actor} đã gán người thực hiện vào task",
        "assignee_removed": f"{actor} đã bỏ người thực hiện khỏi task",
        "requirement_created": f"{actor} đã tạo yêu cầu mới",
        "requirement_updated": f"{actor} đã cập nhật yêu cầu",
        "requirement_deleted": f"{actor} đã xóa yêu cầu"
    }
    
    return descriptions.get(action, f"{actor} đã thực hiện: {action}")


@frappe.whitelist(allow_guest=False)
def get_logs(project_id: str = None, target_type: str = None, target_id: str = None,
            limit: int = 50, offset: int = 0):
    """
    Lấy danh sách change logs của project
    
    Args:
        project_id: ID của project (required)
        target_type: Filter theo loại target (project/requirement/task/member)
        target_id: Filter theo target cụ thể
        limit: Giới hạn số records (default: 50)
        offset: Offset cho pagination (default: 0)
    
    Returns:
        List change logs
    """
    try:
        user = frappe.session.user
        
        # Validate project_id
        if not project_id:
            return error_response("project_id is required", code="MISSING_PARAMETER")
        
        # Kiểm tra project tồn tại
        if not frappe.db.exists("PM Project", project_id):
            return not_found_response(f"Project {project_id} không tồn tại")
        
        # Kiểm tra quyền truy cập
        if not check_project_access(project_id, user):
            return forbidden_response("Bạn không có quyền truy cập dự án này")
        
        # Build filters
        filters = {"project_id": project_id}
        if target_type:
            filters["target_type"] = target_type
        if target_id:
            filters["target_id"] = target_id
        
        # Validate limit
        limit = min(int(limit), 200)  # Max 200 records
        offset = max(int(offset), 0)
        
        # Đếm tổng số records
        total_count = frappe.db.count("PM Change Log", filters)
        
        # Lấy logs
        logs = frappe.get_all(
            "PM Change Log",
            filters=filters,
            fields=["name", "action", "actor_id", "target_type", "target_id",
                   "old_value", "new_value", "creation"],
            order_by="creation desc",
            limit_start=offset,
            limit_page_length=limit
        )
        
        # Enrich data
        for log in logs:
            enrich_log_data(log)
        
        return success_response(
            data=logs,
            message=f"Tìm thấy {len(logs)} bản ghi",
            meta={
                "total": total_count,
                "limit": limit,
                "offset": offset,
                "has_more": offset + len(logs) < total_count
            }
        )
        
    except Exception as e:
        frappe.log_error(f"Error getting change logs: {str(e)}")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def get_task_logs(task_id: str, limit: int = 20):
    """
    Lấy change logs của một task cụ thể
    
    Args:
        task_id: ID của task
        limit: Giới hạn số records (default: 20)
    
    Returns:
        List change logs của task
    """
    try:
        user = frappe.session.user
        
        # Kiểm tra task tồn tại
        if not frappe.db.exists("PM Task", task_id):
            return not_found_response(f"Task {task_id} không tồn tại")
        
        # Lấy project_id của task
        project_id = frappe.db.get_value("PM Task", task_id, "project_id")
        
        # Kiểm tra quyền truy cập
        if not check_project_access(project_id, user):
            return forbidden_response("Bạn không có quyền truy cập task này")
        
        # Validate limit
        limit = min(int(limit), 100)
        
        # Lấy logs
        logs = frappe.get_all(
            "PM Change Log",
            filters={
                "project_id": project_id,
                "target_type": "task",
                "target_id": task_id
            },
            fields=["name", "action", "actor_id", "old_value", "new_value", "creation"],
            order_by="creation desc",
            limit_page_length=limit
        )
        
        # Enrich data
        for log in logs:
            enrich_log_data(log)
        
        return success_response(
            data=logs,
            message=f"Tìm thấy {len(logs)} bản ghi"
        )
        
    except Exception as e:
        frappe.log_error(f"Error getting task logs: {str(e)}")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def get_activity_summary(project_id: str = None, days: int = 7):
    """
    Lấy tóm tắt hoạt động của project trong N ngày gần nhất
    
    Args:
        project_id: ID của project
        days: Số ngày (default: 7)
    
    Returns:
        Tóm tắt hoạt động theo ngày và theo action
    """
    try:
        user = frappe.session.user
        
        # Validate project_id
        if not project_id:
            return error_response("project_id is required", code="MISSING_PARAMETER")
        
        # Kiểm tra quyền truy cập
        if not check_project_access(project_id, user):
            return forbidden_response("Bạn không có quyền truy cập dự án này")
        
        # Giới hạn days
        days = min(int(days), 30)
        
        # Thống kê theo ngày
        daily_stats = frappe.db.sql("""
            SELECT DATE(creation) as date, COUNT(*) as count
            FROM `tabPM Change Log`
            WHERE project_id = %s
            AND creation >= DATE_SUB(NOW(), INTERVAL %s DAY)
            GROUP BY DATE(creation)
            ORDER BY date DESC
        """, (project_id, days), as_dict=True)
        
        # Thống kê theo action
        action_stats = frappe.db.sql("""
            SELECT action, COUNT(*) as count
            FROM `tabPM Change Log`
            WHERE project_id = %s
            AND creation >= DATE_SUB(NOW(), INTERVAL %s DAY)
            GROUP BY action
            ORDER BY count DESC
        """, (project_id, days), as_dict=True)
        
        # Top contributors
        contributor_stats = frappe.db.sql("""
            SELECT actor_id, COUNT(*) as action_count
            FROM `tabPM Change Log`
            WHERE project_id = %s
            AND creation >= DATE_SUB(NOW(), INTERVAL %s DAY)
            GROUP BY actor_id
            ORDER BY action_count DESC
            LIMIT 5
        """, (project_id, days), as_dict=True)
        
        # Enrich contributor info
        for contrib in contributor_stats:
            user_info = frappe.db.get_value(
                "User",
                contrib["actor_id"],
                ["full_name", "user_image"],
                as_dict=True
            )
            if user_info:
                contrib["full_name"] = user_info.get("full_name")
                contrib["user_image"] = user_info.get("user_image")
        
        return success_response(
            data={
                "daily": daily_stats,
                "by_action": action_stats,
                "top_contributors": contributor_stats,
                "period_days": days
            },
            message="Lấy tóm tắt hoạt động thành công"
        )
        
    except Exception as e:
        frappe.log_error(f"Error getting activity summary: {str(e)}")
        return error_response(str(e))

