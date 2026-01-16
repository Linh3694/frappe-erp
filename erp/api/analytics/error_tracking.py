# -*- coding: utf-8 -*-
# Copyright (c) 2026, Linh Nguyen and contributors
# For license information, please see license.txt

"""
Error Tracking API
APIs để lấy thông tin lỗi từ Parent Portal cho dashboard monitoring
"""

from __future__ import unicode_literals
import frappe
from frappe.utils import add_to_date, now_datetime
import json


@frappe.whitelist()
def get_recent_errors(limit=50, since_minutes=60):
    """
    Lấy danh sách lỗi gần đây từ Portal API Error
    
    Args:
        limit: Số lượng records tối đa (default 50)
        since_minutes: Lấy lỗi trong X phút gần đây (default 60)
        
    Returns:
        dict: {success, data: [errors]}
    """
    try:
        limit = int(limit)
        since_minutes = int(since_minutes)
        
        cutoff = add_to_date(None, minutes=-since_minutes)
        
        errors = frappe.get_all(
            "Portal API Error",
            filters={"occurred_at": [">=", cutoff]},
            fields=[
                "name", "error_id", "guardian_name", "api_endpoint", 
                "error_type", "error_message", "occurred_at", "is_resolved",
                "ip_address"
            ],
            order_by="occurred_at desc",
            limit=limit
        )
        
        # Format datetime
        for error in errors:
            if error.get('occurred_at'):
                error['occurred_at'] = str(error['occurred_at'])
        
        return {
            "success": True,
            "data": errors,
            "total": len(errors),
            "since_minutes": since_minutes
        }
        
    except Exception as e:
        frappe.log_error(f"Error getting recent errors: {str(e)}", "Error Tracking API")
        return {
            "success": False,
            "message": str(e),
            "data": []
        }


@frappe.whitelist()
def get_error_stats(period="24h"):
    """
    Thống kê lỗi theo endpoint và loại
    
    Args:
        period: Khoảng thời gian ("1h", "6h", "24h", "7d")
        
    Returns:
        dict: {success, data: {by_endpoint, by_type, total_errors, time_series}}
    """
    try:
        # Parse period
        if period == "1h":
            interval = "1 HOUR"
        elif period == "6h":
            interval = "6 HOUR"
        elif period == "7d":
            interval = "7 DAY"
        else:  # 24h default
            interval = "24 HOUR"
        
        # Tổng lỗi theo endpoint
        by_endpoint = frappe.db.sql(f"""
            SELECT api_endpoint, COUNT(*) as count
            FROM `tabPortal API Error`
            WHERE occurred_at >= DATE_SUB(NOW(), INTERVAL {interval})
            GROUP BY api_endpoint
            ORDER BY count DESC
            LIMIT 10
        """, as_dict=True)
        
        # Tổng lỗi theo loại
        by_type = frappe.db.sql(f"""
            SELECT error_type, COUNT(*) as count
            FROM `tabPortal API Error`
            WHERE occurred_at >= DATE_SUB(NOW(), INTERVAL {interval})
            GROUP BY error_type
            ORDER BY count DESC
        """, as_dict=True)
        
        # Tổng số lỗi
        total_errors = frappe.db.sql(f"""
            SELECT COUNT(*) as total
            FROM `tabPortal API Error`
            WHERE occurred_at >= DATE_SUB(NOW(), INTERVAL {interval})
        """, as_dict=True)[0].get('total', 0)
        
        # Số lỗi chưa resolved
        unresolved_errors = frappe.db.sql(f"""
            SELECT COUNT(*) as total
            FROM `tabPortal API Error`
            WHERE occurred_at >= DATE_SUB(NOW(), INTERVAL {interval})
            AND is_resolved = 0
        """, as_dict=True)[0].get('total', 0)
        
        # Time series (lỗi theo giờ)
        time_series = frappe.db.sql(f"""
            SELECT 
                DATE_FORMAT(occurred_at, '%Y-%m-%d %H:00') as hour,
                COUNT(*) as count
            FROM `tabPortal API Error`
            WHERE occurred_at >= DATE_SUB(NOW(), INTERVAL {interval})
            GROUP BY DATE_FORMAT(occurred_at, '%Y-%m-%d %H:00')
            ORDER BY hour ASC
        """, as_dict=True)
        
        return {
            "success": True,
            "data": {
                "by_endpoint": by_endpoint,
                "by_type": by_type,
                "total_errors": total_errors,
                "unresolved_errors": unresolved_errors,
                "time_series": time_series
            },
            "period": period
        }
        
    except Exception as e:
        frappe.log_error(f"Error getting error stats: {str(e)}", "Error Tracking API")
        return {
            "success": False,
            "message": str(e),
            "data": {}
        }


@frappe.whitelist()
def get_error_detail(error_id):
    """
    Lấy chi tiết một error (bao gồm stack trace, request params)
    
    Args:
        error_id: Error ID hoặc document name
        
    Returns:
        dict: {success, data: error_detail}
    """
    try:
        # Tìm theo error_id hoặc name
        error = None
        
        if frappe.db.exists("Portal API Error", {"error_id": error_id}):
            error = frappe.get_doc("Portal API Error", {"error_id": error_id})
        elif frappe.db.exists("Portal API Error", error_id):
            error = frappe.get_doc("Portal API Error", error_id)
        
        if not error:
            return {
                "success": False,
                "message": f"Error not found: {error_id}"
            }
        
        # Convert to dict và parse JSON fields
        error_data = error.as_dict()
        
        # Parse JSON fields
        for json_field in ['request_params', 'response_data', 'device_info']:
            if error_data.get(json_field):
                try:
                    error_data[json_field] = json.loads(error_data[json_field])
                except (json.JSONDecodeError, TypeError):
                    pass
        
        return {
            "success": True,
            "data": error_data
        }
        
    except Exception as e:
        frappe.log_error(f"Error getting error detail: {str(e)}", "Error Tracking API")
        return {
            "success": False,
            "message": str(e)
        }


@frappe.whitelist()
def mark_error_resolved(error_id):
    """
    Đánh dấu một error là đã resolved
    
    Args:
        error_id: Error ID hoặc document name
        
    Returns:
        dict: {success, message}
    """
    try:
        error = None
        
        if frappe.db.exists("Portal API Error", {"error_id": error_id}):
            error = frappe.get_doc("Portal API Error", {"error_id": error_id})
        elif frappe.db.exists("Portal API Error", error_id):
            error = frappe.get_doc("Portal API Error", error_id)
        
        if not error:
            return {
                "success": False,
                "message": f"Error not found: {error_id}"
            }
        
        error.is_resolved = 1
        error.resolved_at = now_datetime()
        error.resolved_by = frappe.session.user
        error.save(ignore_permissions=True)
        frappe.db.commit()
        
        return {
            "success": True,
            "message": "Error marked as resolved"
        }
        
    except Exception as e:
        frappe.log_error(f"Error marking error resolved: {str(e)}", "Error Tracking API")
        return {
            "success": False,
            "message": str(e)
        }


@frappe.whitelist()
def bulk_mark_resolved(error_ids):
    """
    Đánh dấu nhiều errors là đã resolved
    
    Args:
        error_ids: List of error IDs (JSON string or list)
        
    Returns:
        dict: {success, resolved_count}
    """
    try:
        if isinstance(error_ids, str):
            error_ids = json.loads(error_ids)
        
        resolved_count = 0
        
        for error_id in error_ids:
            result = mark_error_resolved(error_id)
            if result.get('success'):
                resolved_count += 1
        
        return {
            "success": True,
            "resolved_count": resolved_count,
            "total": len(error_ids)
        }
        
    except Exception as e:
        frappe.log_error(f"Error bulk marking resolved: {str(e)}", "Error Tracking API")
        return {
            "success": False,
            "message": str(e)
        }


@frappe.whitelist()
def get_slow_apis(limit=50, since_minutes=60, min_response_time=1000):
    """
    Lấy danh sách API có response chậm
    
    Args:
        limit: Số lượng records tối đa (default 50)
        since_minutes: Lấy trong X phút gần đây (default 60)
        min_response_time: Ngưỡng response time ms (default 1000)
        
    Returns:
        dict: {success, data: [slow_apis]}
    """
    try:
        limit = int(limit)
        since_minutes = int(since_minutes)
        min_response_time = int(min_response_time)
        
        cutoff = add_to_date(None, minutes=-since_minutes)
        
        slow_apis = frappe.get_all(
            "Portal Slow API",
            filters={
                "occurred_at": [">=", cutoff],
                "response_time_ms": [">=", min_response_time]
            },
            fields=[
                "name", "api_endpoint", "method", "response_time_ms",
                "guardian", "user", "occurred_at", "severity", "ip_address"
            ],
            order_by="occurred_at desc",
            limit=limit
        )
        
        # Format datetime và lấy guardian name
        for api in slow_apis:
            if api.get('occurred_at'):
                api['occurred_at'] = str(api['occurred_at'])
            
            # Lấy guardian name nếu có
            if api.get('guardian'):
                api['guardian_name'] = frappe.db.get_value(
                    "CRM Guardian", api['guardian'], "guardian_name"
                ) or api['guardian']
            else:
                api['guardian_name'] = api.get('user', 'Unknown')
        
        return {
            "success": True,
            "data": slow_apis,
            "total": len(slow_apis),
            "since_minutes": since_minutes
        }
        
    except Exception as e:
        frappe.log_error(f"Error getting slow APIs: {str(e)}", "Error Tracking API")
        return {
            "success": False,
            "message": str(e),
            "data": []
        }


@frappe.whitelist()
def get_slow_api_stats(period="24h"):
    """
    Thống kê slow APIs theo endpoint
    
    Args:
        period: Khoảng thời gian ("1h", "6h", "24h", "7d")
        
    Returns:
        dict: {success, data: {by_endpoint, by_severity, avg_response_time}}
    """
    try:
        # Parse period
        if period == "1h":
            interval = "1 HOUR"
        elif period == "6h":
            interval = "6 HOUR"
        elif period == "7d":
            interval = "7 DAY"
        else:  # 24h default
            interval = "24 HOUR"
        
        # Top slow endpoints
        by_endpoint = frappe.db.sql(f"""
            SELECT 
                api_endpoint,
                COUNT(*) as count,
                AVG(response_time_ms) as avg_time,
                MAX(response_time_ms) as max_time
            FROM `tabPortal Slow API`
            WHERE occurred_at >= DATE_SUB(NOW(), INTERVAL {interval})
            GROUP BY api_endpoint
            ORDER BY count DESC
            LIMIT 10
        """, as_dict=True)
        
        # Format avg_time
        for item in by_endpoint:
            item['avg_time'] = round(item['avg_time'] or 0, 0)
        
        # Count by severity
        by_severity = frappe.db.sql(f"""
            SELECT severity, COUNT(*) as count
            FROM `tabPortal Slow API`
            WHERE occurred_at >= DATE_SUB(NOW(), INTERVAL {interval})
            GROUP BY severity
            ORDER BY count DESC
        """, as_dict=True)
        
        # Total và averages
        totals = frappe.db.sql(f"""
            SELECT 
                COUNT(*) as total,
                AVG(response_time_ms) as avg_response_time,
                MAX(response_time_ms) as max_response_time
            FROM `tabPortal Slow API`
            WHERE occurred_at >= DATE_SUB(NOW(), INTERVAL {interval})
        """, as_dict=True)[0]
        
        return {
            "success": True,
            "data": {
                "by_endpoint": by_endpoint,
                "by_severity": by_severity,
                "total_slow_calls": totals.get('total', 0),
                "avg_response_time": round(totals.get('avg_response_time') or 0, 0),
                "max_response_time": totals.get('max_response_time', 0)
            },
            "period": period
        }
        
    except Exception as e:
        frappe.log_error(f"Error getting slow API stats: {str(e)}", "Error Tracking API")
        return {
            "success": False,
            "message": str(e),
            "data": {}
        }
