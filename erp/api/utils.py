# -*- coding: utf-8 -*-
# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from typing import Dict, Any, List, Optional
import unicodedata


# ========================================================================
# Vietnamese Name Formatting Utilities
# ========================================================================

# Danh sách họ Việt Nam phổ biến - dùng để detect format tên
VIETNAMESE_SURNAMES = [
    'nguyễn', 'nguyen', 'trần', 'tran', 'lê', 'le', 'phạm', 'pham',
    'huỳnh', 'huynh', 'hoàng', 'hoang', 'vũ', 'vu', 'võ', 'vo',
    'phan', 'trương', 'truong', 'bùi', 'bui', 'đặng', 'dang',
    'đỗ', 'do', 'ngô', 'ngo', 'hồ', 'ho', 'dương', 'duong',
    'đinh', 'dinh', 'lý', 'ly', 'lương', 'luong', 'mai', 'đào', 'dao',
    'trịnh', 'trinh', 'tô', 'to', 'tạ', 'ta', 'chu', 'châu', 'chau',
    'quách', 'quach', 'cao', 'la', 'thái', 'thai', 'lưu', 'luu',
    'phùng', 'phung', 'vương', 'vuong', 'từ', 'tu', 'hà', 'ha',
    'kiều', 'kieu', 'đoàn', 'doan', 'tăng', 'tang', 'lam', 'mã', 'ma',
    'tống', 'tong', 'triệu', 'trieu', 'nghiêm', 'nghiem', 'thạch', 'thach',
    'quang', 'doãn', 'doan', 'khương', 'khuong', 'ninh'
]


def remove_vietnamese_tones(text: str) -> str:
    """Loại bỏ dấu tiếng Việt để so sánh"""
    if not text:
        return ''
    text = unicodedata.normalize('NFD', text)
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    text = text.replace('đ', 'd').replace('Đ', 'D')
    return text.lower()


def is_vietnamese_surname(word: str) -> bool:
    """Kiểm tra xem một từ có phải là họ Việt Nam không"""
    if not word:
        return False
    normalized = remove_vietnamese_tones(word.lower())
    return normalized in [remove_vietnamese_tones(s) for s in VIETNAMESE_SURNAMES]


def format_vietnamese_name(name: str) -> str:
    """
    Format tên sang chuẩn Việt Nam (Họ + Đệm + Tên) với logic phát hiện thông minh
    
    Ví dụ:
    - 'Duy Hiếu Nguyễn' -> 'Nguyễn Duy Hiếu' (format Tây -> VN)
    - 'Nguyễn Hải Linh' -> 'Nguyễn Hải Linh' (đã chuẩn VN -> giữ nguyên)
    
    Logic:
    - Nếu phần đầu là họ VN -> đã chuẩn format VN, giữ nguyên
    - Nếu phần cuối là họ VN -> format Tây, cần đảo
    """
    if not name:
        return name
    
    parts = name.strip().split()
    
    if len(parts) <= 1:
        return name
    
    first_part = parts[0]
    last_part = parts[-1]
    
    # Nếu phần đầu là họ VN -> đã chuẩn format VN
    if is_vietnamese_surname(first_part):
        return name
    
    # Nếu phần cuối là họ VN -> format Tây, cần đảo
    if is_vietnamese_surname(last_part):
        # Đảo: [First, Middle, Last] -> [Last, First, Middle]
        return ' '.join([last_part] + parts[:-1])
    
    # Không xác định được -> giữ nguyên
    return name


# ========================================================================
# Standard CRUD Utilities
# ========================================================================


def get_list(doctype: str, page: int = 1, limit: int = 20, filters: Optional[Dict[str, Any]] = None,
             fields: Optional[List[str]] = None, order_by: str = "modified desc") -> Dict[str, Any]:
    """Get list of documents with pagination"""
    try:
        # Build filters
        doc_filters = {}
        if filters:
            doc_filters.update(filters)

        # Get total count
        total_count = frappe.db.count(doctype, filters=doc_filters)

        # Calculate offset
        offset = (page - 1) * limit

        # Get data
        data = frappe.get_list(
            doctype,
            filters=doc_filters,
            fields=fields or ["name"],
            order_by=order_by,
            limit_page_length=limit,
            limit_start=offset
        )

        # Map field names to correct format
        for item in data:
            if 'creation' in item:
                item['created_at'] = item.pop('creation')
            if 'modified' in item:
                item['updated_at'] = item.pop('modified')

        # Calculate total pages
        total_pages = (total_count + limit - 1) // limit

        return {
            "success": True,
            "data": data,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total_count,
                "total_pages": total_pages
            }
        }
    except Exception as e:
        frappe.log_error(f"Error in get_list: {str(e)}")
        return {
            "success": False,
            "message": f"Failed to get list: {str(e)}"
        }


def get_single(doctype: str, name: str) -> Dict[str, Any]:
    """Get single document by name"""
    try:
        doc = frappe.get_doc(doctype, name)
        return {
            "success": True,
            "data": doc.as_dict()
        }
    except Exception as e:
        frappe.log_error(f"Error in get_single: {str(e)}")
        return {
            "success": False,
            "message": f"Document not found: {str(e)}"
        }


def create_doc(doctype: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Create new document"""
    try:
        doc = frappe.get_doc({
            "doctype": doctype,
            **data
        })
        doc.insert()
        frappe.db.commit()

        return {
            "success": True,
            "data": doc.as_dict(),
            "message": "Document created successfully"
        }
    except Exception as e:
        frappe.log_error(f"Error in create_doc: {str(e)}")
        frappe.db.rollback()
        return {
            "success": False,
            "message": f"Failed to create document: {str(e)}"
        }


def update_doc(doctype: str, name: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Update existing document"""
    try:
        doc = frappe.get_doc(doctype, name)
        doc.update(data)
        doc.save()
        frappe.db.commit()

        return {
            "success": True,
            "data": doc.as_dict(),
            "message": "Document updated successfully"
        }
    except Exception as e:
        frappe.log_error(f"Error in update_doc: {str(e)}")
        frappe.db.rollback()
        return {
            "success": False,
            "message": f"Failed to update document: {str(e)}"
        }


def delete_doc(doctype: str, name: str) -> Dict[str, Any]:
    """Delete document"""
    try:
        frappe.delete_doc(doctype, name)
        frappe.db.commit()

        return {
            "success": True,
            "message": "Document deleted successfully"
        }
    except Exception as e:
        frappe.log_error(f"Error in delete_doc: {str(e)}")
        frappe.db.rollback()
        return {
            "success": False,
            "message": f"Failed to delete document: {str(e)}"
        }
