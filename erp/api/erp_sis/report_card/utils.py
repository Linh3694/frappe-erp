# -*- coding: utf-8 -*-
"""
Report Card Utils
=================

Shared utility functions cho Report Card module.
Tập trung các helper functions dùng chung để tránh code duplicate.
"""

import frappe
import json
from typing import Any, Dict, Optional


def get_request_payload() -> Dict[str, Any]:
    """
    Đọc request JSON hoặc form_dict một cách an toàn.
    
    Returns:
        Dict chứa dữ liệu request
    """
    data: Dict[str, Any] = {}
    if getattr(frappe, "request", None) and getattr(frappe.request, "data", None):
        try:
            raw = frappe.request.data
            body = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw
            parsed = json.loads(body or "{}")
            if isinstance(parsed, dict):
                data = parsed
        except Exception:
            data = frappe.local.form_dict or {}
    else:
        data = frappe.local.form_dict or {}
    return data


def get_current_campus_id() -> str:
    """
    Lấy campus ID hiện tại từ context.
    
    Returns:
        Campus ID string, fallback về "campus-1" nếu không có
    """
    from erp.utils.campus_utils import get_current_campus_from_context
    
    campus_id = get_current_campus_from_context()
    if not campus_id:
        campus_id = "campus-1"
    return campus_id


def parse_json_field(value: Any, default: Any = None) -> Any:
    """
    Parse JSON string thành dict/list, xử lý an toàn.
    
    Args:
        value: Giá trị cần parse (có thể là string JSON hoặc đã là dict/list)
        default: Giá trị mặc định nếu parse thất bại
    
    Returns:
        Dict/List đã parse hoặc default value
    """
    if value is None:
        return default
    
    if isinstance(value, (dict, list)):
        return value
    
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return default
    
    return default


def sanitize_float(value: Any) -> Optional[float]:
    """
    Convert giá trị sang float một cách an toàn.
    
    Args:
        value: Giá trị cần convert (int, float, string, None)
    
    Returns:
        Float value hoặc None nếu invalid
    """
    if value is None or value == "" or value == "null":
        return None
    
    if isinstance(value, (int, float)):
        return float(value)
    
    if isinstance(value, str):
        value = value.strip()
        if value == "":
            return None
        try:
            return float(value)
        except ValueError:
            return None
    
    return None


def resolve_actual_subject_title(subject_id: Optional[str]) -> str:
    """
    Lấy title của môn học từ SIS Actual Subject.
    
    Args:
        subject_id: ID của môn học
    
    Returns:
        Title tiếng Việt của môn học hoặc subject_id nếu không tìm thấy
    """
    if not subject_id:
        return ""
    
    try:
        doc = frappe.get_doc("SIS Actual Subject", subject_id)
        return doc.title_vn or doc.title_en or subject_id
    except frappe.DoesNotExistError:
        return subject_id
    except Exception:
        return subject_id


def resolve_teacher_names(actual_subject_id: str, class_id: str) -> list:
    """
    Lấy danh sách tên giáo viên dạy môn học trong lớp.
    
    Args:
        actual_subject_id: ID môn học
        class_id: ID lớp
    
    Returns:
        List tên giáo viên
    """
    try:
        if not class_id:
            return []

        assignments = frappe.db.sql("""
            SELECT COALESCE(NULLIF(u.full_name, ''), t.user_id) as teacher_name
            FROM `tabSIS Subject Assignment` sa
            LEFT JOIN `tabSIS Teacher` t ON sa.teacher_id = t.name
            LEFT JOIN `tabUser` u ON t.user_id = u.name
            WHERE sa.actual_subject_id = %s AND sa.class_id = %s
            ORDER BY sa.creation
        """, (actual_subject_id, class_id), as_dict=True)

        return [a.get("teacher_name", "") for a in assignments if a.get("teacher_name")]
    except Exception:
        return []


def resolve_homeroom_teacher_name(teacher_id: str) -> str:
    """
    Lấy tên giáo viên chủ nhiệm với format tiếng Việt.
    
    Args:
        teacher_id: ID giáo viên
    
    Returns:
        Tên giáo viên với format: Họ + Tên
    """
    try:
        if not teacher_id:
            return ""
        
        teacher_data = frappe.db.sql("""
            SELECT COALESCE(NULLIF(u.full_name, ''), t.user_id, t.name) as teacher_name,
                   u.first_name, u.last_name
            FROM `tabSIS Teacher` t
            LEFT JOIN `tabUser` u ON t.user_id = u.name
            WHERE t.name = %s
            LIMIT 1
        """, (teacher_id,), as_dict=True)
        
        if not teacher_data:
            return teacher_id
            
        first_name = teacher_data[0].get('first_name', '') or ''
        last_name = teacher_data[0].get('last_name', '') or ''
        
        if first_name and last_name:
            # Vietnamese format: Last name + First name
            return f"{last_name.strip()} {first_name.strip()}".strip()
        else:
            return teacher_data[0]['teacher_name'] or teacher_id
            
    except Exception:
        return teacher_id
