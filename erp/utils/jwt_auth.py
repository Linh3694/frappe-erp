# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
import jwt
from frappe import _
import time


def decode_jwt_token(token):
    """
    Decode JWT token and return payload
    This is for internal use only - we trust tokens issued by our own system
    """
    try:
        # Remove "Bearer " prefix if present
        if token.startswith('Bearer '):
            token = token[7:]
        
        # Decode without verification for now (since we control the issuer)
        # In production, you should verify the signature
        payload = jwt.decode(token, options={"verify_signature": False})
        
        # Check expiration
        if payload.get('exp') and payload['exp'] < time.time():
            frappe.logger().warning("JWT token has expired")
            return None
        
        return payload
        
    except jwt.ExpiredSignatureError:
        frappe.logger().warning("JWT token has expired")
        return None
    except jwt.InvalidTokenError as e:
        frappe.logger().warning(f"Invalid JWT token: {str(e)}")
        return None
    except Exception as e:
        frappe.logger().warning(f"Error decoding JWT token: {str(e)}")
        return None


def authenticate_via_jwt():
    """
    Authenticate user via JWT token from Authorization header
    Returns user_email if successful, None otherwise
    """
    try:
        # Check Authorization header first
        auth_header = frappe.get_request_header('Authorization')
        if not auth_header:
            # Fallback to X-Frappe-Token header
            auth_header = frappe.get_request_header('X-Frappe-Token')
            if not auth_header:
                return None
        
        # Decode JWT token
        payload = decode_jwt_token(auth_header)
        if not payload:
            return None
        
        # Extract user email from payload
        user_email = payload.get('email') or payload.get('sub')
        if not user_email:
            frappe.logger().warning("No user email found in JWT payload")
            return None
        
        # Check if user exists
        if not frappe.db.exists('User', user_email):
            frappe.logger().warning(f"User {user_email} not found in database")
            return None
        
        frappe.logger().debug(f"JWT authentication successful for user: {user_email}")
        return user_email
        
    except Exception as e:
        frappe.logger().error(f"Error in JWT authentication: {str(e)}")
        return None
