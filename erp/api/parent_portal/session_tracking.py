"""
Parent Portal Session Tracking
Track app opens, resumes, and user activity for analytics
"""

import frappe
from frappe import _
from erp.utils.centralized_logger import log_authentication


@frappe.whitelist(allow_guest=False)
def track_app_session():
	"""
	Track when parent opens or resumes the app
	
	Mobile app should call this endpoint:
	- On app start (cold start)
	- On app resume (from background)
	- Optionally: Every X minutes while app is active
	
	Returns:
		dict: Success status
	"""
	try:
		user = frappe.session.user
		
		# Only track Parent Portal users
		if not user or '@parent.wellspring.edu.vn' not in user:
			return {
				"success": False,
				"message": "Not a Parent Portal user"
			}
		
		# Get guardian info
		try:
			guardian_id = user.split('@')[0]
			guardian = frappe.get_doc("SIS Guardian", guardian_id)
			guardian_name = guardian.guardian_name or guardian_id
			phone_number = guardian.mobile or guardian.phone or ""
		except Exception:
			guardian_name = user
			phone_number = ""
		
		# Get IP address
		try:
			ip = frappe.request.headers.get('X-Forwarded-For', frappe.request.remote_addr)
			if ',' in ip:
				ip = ip.split(',')[0].strip()
		except Exception:
			ip = 'unknown'
		
		# Log the session start
		log_authentication(
			user=user,
			action='app_session',  # New action type
			ip=ip,
			status='success',
			details={
				'fullname': guardian_name,
				'guardian_id': guardian_id,
				'phone_number': phone_number,
				'timestamp': frappe.utils.now(),
				'session_type': 'app_open'  # Can be: app_open, app_resume, active
			}
		)
		
		return {
			"success": True,
			"message": "Session tracked successfully"
		}
		
	except Exception as e:
		frappe.log_error(f"Error tracking app session: {str(e)}", "Session Tracking Error")
		return {
			"success": False,
			"message": str(e)
		}


@frappe.whitelist(allow_guest=False)
def track_app_close():
	"""
	Optional: Track when parent closes or backgrounds the app
	
	Returns:
		dict: Success status
	"""
	try:
		user = frappe.session.user
		
		if not user or '@parent.wellspring.edu.vn' not in user:
			return {"success": False}
		
		# Get IP
		try:
			ip = frappe.request.headers.get('X-Forwarded-For', frappe.request.remote_addr)
			if ',' in ip:
				ip = ip.split(',')[0].strip()
		except Exception:
			ip = 'unknown'
		
		# Log session end
		log_authentication(
			user=user,
			action='app_session_end',
			ip=ip,
			status='success',
			details={
				'timestamp': frappe.utils.now(),
				'session_type': 'app_close'
			}
		)
		
		return {
			"success": True,
			"message": "Session end tracked"
		}
		
	except Exception as e:
		return {"success": False, "message": str(e)}
