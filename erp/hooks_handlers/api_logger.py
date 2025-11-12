"""
API Request Logging Handler
Logs all API calls with response times and status codes
"""

import frappe
import time
from erp.utils.centralized_logger import log_api_call


def log_api_request_start(**kwargs):
    """Hook called before API request execution"""
    try:
        # Store start time in frappe.local for later use
        frappe.local.request_start_time = time.time()
        frappe.local.request_path = frappe.request.path
        frappe.local.request_method = frappe.request.method
    except Exception as e:
        frappe.errprint(f"Error in log_api_request_start: {str(e)}")


def log_api_request_end(**kwargs):
    """Hook called after API request execution"""
    try:
        if not hasattr(frappe.local, 'request_start_time'):
            return
        
        # Calculate response time
        response_time_ms = (time.time() - frappe.local.request_start_time) * 1000
        
        # Skip health checks and system endpoints
        path = getattr(frappe.local, 'request_path', '').lower()
        if any(x in path for x in ['/health', '/api/ping', '/__pycache__', '.js', '.css']):
            return
        
        # Get user
        user = frappe.session.user if hasattr(frappe, 'session') else 'Guest'
        
        # Get method
        method = getattr(frappe.local, 'request_method', 'GET')
        
        # Get endpoint
        endpoint = getattr(frappe.local, 'request_path', '')
        
        # Try to get status code from response
        try:
            status_code = frappe.response.get('_status_code', 200)
            if isinstance(status_code, str):
                status_code = int(status_code.split()[0]) if ' ' in status_code else 200
        except:
            status_code = 200
        
        # Get IP
        ip = frappe.get_request_header('X-Forwarded-For') or frappe.request.remote_addr or 'unknown'
        if ip and ',' in ip:
            ip = ip.split(',')[0].strip()
        
        # Log the API call
        log_api_call(
            user=user,
            method=method,
            endpoint=endpoint,
            response_time_ms=response_time_ms,
            status_code=status_code,
            details={
                'ip': ip,
                'timestamp': frappe.utils.now()
            }
        )
    except Exception as e:
        frappe.errprint(f"Error in log_api_request_end: {str(e)}")

