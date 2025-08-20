# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
import jwt
from frappe.auth import LoginManager
import json


@frappe.whitelist(allow_guest=True)
def jwt_to_session():
    """
    Convert JWT token to Frappe session
    """
    try:
        # Get JWT token from headers or form data
        token = None
        
        # Try Authorization header
        auth_header = frappe.get_request_header('Authorization')
        if auth_header:
            if auth_header.startswith('Bearer '):
                token = auth_header[7:]
            else:
                token = auth_header
        
        # Try X-Frappe-Token header
        if not token:
            token = frappe.get_request_header('X-Frappe-Token')
        
        # Try form data
        if not token:
            token = frappe.local.form_dict.get('token')
        
        if not token:
            return {
                "success": False,
                "message": "No JWT token provided"
            }
        
        frappe.logger().info(f"Converting JWT to session, token: {token[:20]}...")
        
        # Decode JWT token (without verification for now)
        try:
            payload = jwt.decode(token, options={"verify_signature": False})
        except Exception as e:
            frappe.logger().error(f"Error decoding JWT: {str(e)}")
            return {
                "success": False,
                "message": f"Invalid JWT token: {str(e)}"
            }
        
        # Extract user email
        user_email = payload.get('email') or payload.get('sub')
        if not user_email:
            return {
                "success": False,
                "message": "No user email found in JWT"
            }
        
        # Check if user exists
        if not frappe.db.exists('User', user_email):
            return {
                "success": False,
                "message": f"User {user_email} not found"
            }
        
        # Check token expiration
        import time
        if payload.get('exp') and payload['exp'] < time.time():
            return {
                "success": False,
                "message": "JWT token has expired"
            }
        
        # Create Frappe session
        frappe.set_user(user_email)
        frappe.local.login_manager = LoginManager()
        frappe.local.login_manager.user = user_email
        frappe.local.login_manager.post_login()
        
        # Get user info
        user = frappe.get_doc('User', user_email)
        
        return {
            "success": True,
            "message": "Session created successfully",
            "data": {
                "user": {
                    "email": user.email,
                    "full_name": user.full_name,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "user_image": user.user_image,
                    "roles": frappe.get_roles(user_email)
                },
                "session_id": frappe.session.sid
            }
        }
        
    except Exception as e:
        frappe.logger().error(f"Error in jwt_to_session: {str(e)}")
        import traceback
        frappe.logger().error(traceback.format_exc())
        
        return {
            "success": False,
            "message": f"Error creating session: {str(e)}"
        }
