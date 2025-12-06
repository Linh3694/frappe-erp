"""
API Request Logging Handler
Logs all API calls with response times and status codes
"""

import frappe
import time
import re
from erp.utils.centralized_logger import log_api_call

# Module patterns - ONLY modules matching Parent Portal folder pages
# Excluded: Profile, Landing, Documentation, Notifications, Login
PARENT_PORTAL_MODULES = {
    'Announcements': r'/api/method/erp\.api\.parent_portal\.announcements',
    'Attendance': r'/api/method/erp\.api\.parent_portal\.attendance',
    'Bus': r'/api/method/erp\.api\.parent_portal\.bus',
    'Calendar': r'/api/method/erp\.api\.parent_portal\.calendar',
    'Communication': r'/api/method/erp\.api\.parent_portal\.contact_log',
    'Feedback': r'/api/method/erp\.api\.parent_portal\.feedback',
    'Leave': r'/api/method/erp\.api\.parent_portal\.leave',
    'Menu': r'/api/method/erp\.api\.parent_portal\.daily_menu',
    'News': r'/api/method/erp\.api\.parent_portal\.news',
    'Report Card': r'/api/method/erp\.api\.parent_portal\.report_card',
    'Timetable': r'/api/method/erp\.api\.parent_portal\.timetable',
}


def detect_module(endpoint: str) -> str:
    """Detect which Parent Portal module an endpoint belongs to"""
    for module_name, pattern in PARENT_PORTAL_MODULES.items():
        if re.search(pattern, endpoint):
            return module_name
    return None


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
        if any(x in path for x in ['/health', '/api/ping', '/__pycache__', '.js', '.css', '/api/method/frappe.client.get_count']):
            return
        
        # Get user
        user = frappe.session.user if hasattr(frappe, 'session') else 'Guest'
        
        # Get method
        method = getattr(frappe.local, 'request_method', 'GET')
        
        # Get endpoint
        endpoint = getattr(frappe.local, 'request_path', '')
        
        # Detect Parent Portal module
        module_name = detect_module(endpoint)
        
        # Only log Parent Portal APIs with detailed module info
        if 'parent_portal' in endpoint.lower():
            if module_name:
                frappe.errprint(f"🔵 [api_logger] Module: {module_name} | Endpoint: {endpoint}")
            else:
                # API is parent_portal but not in tracked modules (e.g., interface, otp_auth, notification_center)
                frappe.errprint(f"🔵 [api_logger] Untracked parent_portal API: {endpoint}")
            
            # DEDUPLICATION: Skip if same user + endpoint was logged within last 3 seconds
            dedup_key = f"api_log_dedup:{user}:{endpoint}"
            if frappe.cache().get_value(dedup_key):
                frappe.errprint(f"🔵 [api_logger] Skipping duplicate: {module_name or 'untracked'} | {endpoint}")
                return
            
            # Set dedup cache for 3 seconds
            frappe.cache().set_value(dedup_key, True, expires_in_sec=3)
        
        # Try to get status code from multiple sources
        status_code = 200
        try:
            # First try: frappe.response dict
            if hasattr(frappe, 'response') and isinstance(frappe.response, dict):
                code = frappe.response.get('_status_code', 200)
                if code is not None:
                    status_code = code
            # Second try: from flask response
            if hasattr(frappe.local, 'response') and hasattr(frappe.local.response, 'status_code'):
                code = frappe.local.response.status_code
                if code is not None:
                    status_code = code
            
            # Clean up string status codes
            if isinstance(status_code, str):
                status_code = int(status_code.split()[0]) if ' ' in status_code else 200
            
            # Ensure it's an int
            if not isinstance(status_code, int) or status_code is None:
                status_code = 200
        except:
            status_code = 200
        
        # Get IP
        ip = frappe.get_request_header('X-Forwarded-For') or frappe.request.remote_addr or 'unknown'
        if ip and ',' in ip:
            ip = ip.split(',')[0].strip()
        
        # Skip OPTIONS requests (CORS preflight)
        if method == 'OPTIONS':
            return
        
        # Get User-Agent safely
        user_agent = frappe.get_request_header('User-Agent') or 'unknown'
        if user_agent != 'unknown' and len(user_agent) > 100:
            user_agent = user_agent[:100]
        
        # Log the API call with module info
        log_api_call(
            user=user,
            method=method,
            endpoint=endpoint,
            response_time_ms=response_time_ms,
            status_code=status_code,
            details={
                'ip': ip,
                'user_agent': user_agent,
                'status_code': status_code,
                'timestamp': frappe.utils.now(),
                'module': module_name  # Track which module this API belongs to
            }
        )
    except Exception as e:
        import traceback
        frappe.errprint(f"❌ [api_logger] Error: {str(e)}")
        frappe.errprint(traceback.format_exc())

