# -*- coding: utf-8 -*-
# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from typing import Dict, Any, List, Optional


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
