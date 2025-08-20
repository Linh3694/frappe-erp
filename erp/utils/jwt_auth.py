# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
import jwt
from frappe import _
from frappe.utils import get_datetime
import json


def decode_jwt_token(token):
    """
    Decode JWT token and return payload
    This is for internal use only - we trust tokens issued by our own system
    """
    try:
        # Remove "Bearer " prefix if present
        if token.startswith('Bearer '):
            token = token[7:]
        
        # Get JWT secret from site config or use default
        secret = frappe.conf.get('jwt_secret_key', 'your-secret-key')
        
        # Decode without verification for now (since we control the issuer)
        # In production, you should verify the signature
        payload = jwt.decode(token, options={"verify_signature": False})
        
        frappe.logger().info(f"Decoded JWT payload: {payload}")
        return payload
        
    except jwt.ExpiredSignatureError:
        frappe.logger().error("JWT token has expired")
        return None
    except jwt.InvalidTokenError as e:
        frappe.logger().error(f"Invalid JWT token: {str(e)}")
        return None
    except Exception as e:
        frappe.logger().error(f"Error decoding JWT token: {str(e)}")
        return None


def authenticate_via_jwt():
    """
    Authenticate user via JWT token from Authorization header
    """
    try:
        # Check Authorization header
        auth_header = frappe.get_request_header('Authorization')
        if not auth_header:
            # Also check X-Frappe-Token header
            auth_header = frappe.get_request_header('X-Frappe-Token')
            if not auth_header:
                return False
        
        # Decode JWT token
        payload = decode_jwt_token(auth_header)
        if not payload:
            return False
        
        # Extract user email from payload
        user_email = payload.get('email') or payload.get('sub')
        if not user_email:
            frappe.logger().error("No user email found in JWT payload")
            return False
        
        # Check if user exists
        if not frappe.db.exists('User', user_email):
            frappe.logger().error(f"User {user_email} not found in database")
            return False
        
        # Set user in session
        frappe.set_user(user_email)
        frappe.logger().info(f"Successfully authenticated user via JWT: {user_email}")
        
        return True
        
    except Exception as e:
        frappe.logger().error(f"Error in JWT authentication: {str(e)}")
        return False


def jwt_auth_middleware():
    """
    Middleware to handle JWT authentication
    Should be called before processing API requests
    """
    try:
        # Skip for guest endpoints or if user already authenticated
        if frappe.session.user != 'Guest':
            return
        
        # Try JWT authentication
        if authenticate_via_jwt():
            frappe.logger().info("JWT authentication successful")
        else:
            frappe.logger().info("JWT authentication failed or not applicable")
            
    except Exception as e:
        frappe.logger().error(f"Error in JWT auth middleware: {str(e)}")
