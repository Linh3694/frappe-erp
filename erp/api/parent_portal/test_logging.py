"""
Test endpoint to verify API logging works
"""

import frappe


@frappe.whitelist()
def test_api_logging():
	"""
	Simple test endpoint to verify API logging
	Call this from Parent Portal or Postman
	
	URL: /api/method/erp.api.parent_portal.test_logging.test_api_logging
	"""
	user = frappe.session.user
	
	return {
		"success": True,
		"message": "Test API called successfully",
		"user": user,
		"instruction": "Check logging.log for this API call"
	}


@frappe.whitelist(allow_guest=True)
def test_guest_api():
	"""
	Test endpoint for guest users
	"""
	return {
		"success": True,
		"message": "Guest API works",
		"note": "This should be logged in logging.log"
	}


