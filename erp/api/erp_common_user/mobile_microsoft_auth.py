# -*- coding: utf-8 -*-
# Copyright (c) 2024, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
import requests
import json
import urllib.parse
import base64
from frappe import _
from frappe.utils import cstr
from erp.api.erp_common_user.microsoft_auth import (
    get_microsoft_access_token, 
    get_microsoft_user_info,
    create_or_update_microsoft_user,
    handle_microsoft_user_login,
    get_microsoft_config
)
import requests


def get_microsoft_access_token_with_redirect(code, redirect_uri):
    """Exchange authorization code for access token with custom redirect URI"""
    config = get_microsoft_config()
    
    token_url = f"https://login.microsoftonline.com/{config['tenant_id']}/oauth2/v2.0/token"
    
    data = {
        "client_id": config["client_id"],
        "client_secret": config["client_secret"],
        "code": code,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code"
    }
    
    frappe.logger().info(f"Token exchange request: client_id={config['client_id']}, redirect_uri={redirect_uri}")
    
    response = requests.post(token_url, data=data)
    
    if response.status_code != 200:
        frappe.logger().error(f"Token exchange failed: {response.text}")
        raise Exception(f"Token request failed: {response.text}")
    
    return response.json()


def get_microsoft_access_token_public_client(code, redirect_uri):
    """Exchange authorization code for access token - Public Client (Mobile) version"""
    config = get_microsoft_config()
    
    token_url = f"https://login.microsoftonline.com/{config['tenant_id']}/oauth2/v2.0/token"
    
    # For public clients, don't send client_secret
    data = {
        "client_id": config["client_id"],
        "code": code,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code"
    }
    
    frappe.logger().info(f"Public client token exchange: client_id={config['client_id']}, redirect_uri={redirect_uri}")
    
    response = requests.post(token_url, data=data)
    
    if response.status_code != 200:
        frappe.logger().error(f"Public client token exchange failed: {response.text}")
        raise Exception(f"Token request failed: {response.text}")
    
    return response.json()


@frappe.whitelist(allow_guest=True, methods=["GET", "POST"])
def mobile_microsoft_callback(code, state=None):
    """
    Handle Microsoft authentication callback specifically for mobile apps
    Returns JSON response instead of redirect
    """
    try:
        frappe.logger().info(f"Mobile Microsoft callback received - Code length: {len(code) if code else 0}")
        
        if not code:
            return {
                "success": False,
                "error": "No authorization code provided",
                "error_code": "NO_CODE"
            }
        
        # State is optional for mobile apps (relaxed security for better UX)
        if state:
            # Try to verify state if provided
            stored_state = frappe.cache().get_value(f"ms_auth_state_{state}")
            if stored_state:
                # Clear state after use
                frappe.cache().delete_value(f"ms_auth_state_{state}")
            else:
                frappe.logger().warning(f"Invalid or expired state parameter: {state}")
                # Continue anyway for mobile compatibility
        
        # Exchange code for access token (with mobile redirect URI)
        try:
            # Get redirect URI from request parameters (sent by mobile app)
            mobile_redirect_uri = frappe.request.args.get('redirect_uri')
            frappe.logger().info(f"DEBUG: mobile_redirect_uri parameter = {mobile_redirect_uri}")
            frappe.logger().info(f"DEBUG: All request args = {dict(frappe.request.args)}")
            
            # For mobile app, use public client authentication with provided redirect URI
            # Mobile app ALWAYS sends redirect_uri parameter, so use it directly
            if mobile_redirect_uri:
                frappe.logger().info(f"Mobile app provided redirect URI: {mobile_redirect_uri}")
                frappe.logger().info(f"Using public client token exchange with mobile redirect URI")
                token_data = get_microsoft_access_token_public_client(code, mobile_redirect_uri)
            else:
                # If no mobile redirect URI provided, this might be a web request
                # Use standard confidential client flow
                frappe.logger().info("No mobile redirect URI provided, using confidential client flow")
                token_data = get_microsoft_access_token(code)
            frappe.logger().info("Successfully got Microsoft access token")
            frappe.logger().info(f"Token data keys: {list(token_data.keys()) if token_data else 'None'}")
        except Exception as e:
            frappe.logger().error(f"Failed to get Microsoft access token: {str(e)}")
            frappe.logger().error(f"Exception type: {type(e).__name__}")
            return {
                "success": False,
                "error": "Failed to exchange authorization code for access token",
                "error_code": "TOKEN_EXCHANGE_FAILED",
                "details": str(e)
            }
        
        # Get user info from Microsoft Graph
        try:
            user_info = get_microsoft_user_info(token_data["access_token"])
            user_email = user_info.get("mail") or user_info.get("userPrincipalName")
            frappe.logger().info(f"Got Microsoft user info for: {user_email}")
        except Exception as e:
            frappe.logger().error(f"Failed to get Microsoft user info: {str(e)}")
            return {
                "success": False,
                "error": "Failed to get user information from Microsoft",
                "error_code": "USER_INFO_FAILED",
                "details": str(e)
            }
        
        if not user_email:
            return {
                "success": False,
                "error": "No email found in Microsoft account",
                "error_code": "NO_EMAIL"
            }
        
        # Skip ERP User Profile - directly check/create Frappe user
        user_profile = None
        
        # Create or update Microsoft user record
        ms_user = create_or_update_microsoft_user(user_info)
        
        # Get or create Frappe user
        frappe_user = handle_microsoft_user_login(ms_user)
        frappe.logger().info(f"Microsoft login processed for: {frappe_user.email}")
        
        # Generate JWT token for API access
        try:
            from erp.api.erp_common_user.auth import generate_jwt_token
            jwt_token = generate_jwt_token(frappe_user.email)
            frappe.logger().info(f"JWT token generated for: {frappe_user.email}")
        except Exception as e:
            frappe.logger().error(f"Failed to generate JWT token: {str(e)}")
            return {
                "success": False,
                "error": "Failed to generate authentication token",
                "error_code": "TOKEN_GENERATION_FAILED",
                "details": str(e)
            }
        
        # Get user roles
        frappe_roles = []
        try:
            frappe_roles = frappe.get_roles(frappe_user.email) or ["Guest"]
        except Exception:
            frappe_roles = ["Guest"]
        
        # Create user data for mobile app using Microsoft Graph info
        user_data = {
            "email": user_email,
            "full_name": frappe_user.full_name,
            "first_name": frappe_user.first_name or "",
            "last_name": frappe_user.last_name or "",
            "provider": "microsoft",
            "job_title": user_info.get("jobTitle", ""),
            "department": user_info.get("department", ""),
            "employee_code": user_info.get("employeeId", ""),
            "user_role": "user",  # Default role
            "roles": frappe_roles,
            "active": frappe_user.enabled,
            "username": user_email,
            "user_image": frappe_user.user_image or "",
            "account_enabled": user_info.get("accountEnabled", True)
        }
        
        # Return success response
        return {
            "success": True,
            "message": "Microsoft authentication successful",
            "token": jwt_token,
            "expires_in": 24 * 60 * 60,  # 24 hours in seconds
            "user": user_data
        }
        
    except Exception as e:
        frappe.logger().error(f"Unexpected error in mobile Microsoft callback: {str(e)}")
        
        # Log the full error for debugging
        frappe.log_error(f"Mobile Microsoft callback error: {str(e)}", "Mobile Microsoft Auth")
        
        return {
            "success": False,
            "error": "An unexpected error occurred during authentication",
            "error_code": "UNEXPECTED_ERROR",
            "details": str(e)
        }


@frappe.whitelist(allow_guest=True, methods=["GET"])
def mobile_auth_status():
    """
    Simple endpoint to check if mobile Microsoft auth is available
    """
    try:
        # Check if Microsoft client is configured
        site_config = frappe.get_site_config()
        client_id = site_config.get("microsoft_client_id") or frappe.conf.get("microsoft_client_id")
        tenant_id = site_config.get("microsoft_tenant_id") or frappe.conf.get("microsoft_tenant_id")
        
        return {
            "success": True,
            "microsoft_auth_available": bool(client_id and tenant_id),
            "tenant_id": tenant_id if tenant_id else None,
            "client_id": client_id[:8] + "..." if client_id else None  # Partial client ID for verification
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@frappe.whitelist(allow_guest=True, methods=["POST"])
def mobile_direct_token_auth(microsoft_token):
    """
    Alternative endpoint for mobile apps that already have Microsoft token
    Directly authenticates using the Microsoft access token
    """
    try:
        if not microsoft_token:
            return {
                "success": False,
                "error": "No Microsoft token provided",
                "error_code": "NO_TOKEN"
            }
        
        # Get user info from Microsoft Graph using the provided token
        try:
            user_info = get_microsoft_user_info(microsoft_token)
            user_email = user_info.get("mail") or user_info.get("userPrincipalName")
            frappe.logger().info(f"Direct token auth - Got user info for: {user_email}")
        except Exception as e:
            frappe.logger().error(f"Failed to get user info with direct token: {str(e)}")
            return {
                "success": False,
                "error": "Invalid or expired Microsoft token",
                "error_code": "INVALID_TOKEN",
                "details": str(e)
            }
        
        if not user_email:
            return {
                "success": False,
                "error": "No email found in Microsoft token",
                "error_code": "NO_EMAIL"
            }
        
        # Skip ERP User Profile - use only Frappe User
        user_profile = None
        
        # Create or update Microsoft user record
        ms_user = create_or_update_microsoft_user(user_info)
        
        # Login or create Frappe user
        frappe_user = handle_microsoft_user_login(ms_user)
        
        # Generate JWT token
        from erp.api.erp_common_user.auth import generate_jwt_token
        jwt_token = generate_jwt_token(frappe_user.email)
        
        # Get user roles
        frappe_roles = frappe.get_roles(frappe_user.email) or ["Guest"]
        
        # Create user data using Microsoft Graph info
        user_data = {
            "email": user_email,
            "full_name": frappe_user.full_name,
            "provider": "microsoft",
            "job_title": user_info.get("jobTitle", ""),
            "department": user_info.get("department", ""),
            "employee_code": user_info.get("employeeId", ""),
            "user_role": "user",  # Default role
            "roles": frappe_roles,
            "active": frappe_user.enabled,
            "username": user_email
        }
        
        return {
            "success": True,
            "message": "Direct token authentication successful",
            "token": jwt_token,
            "expires_in": 24 * 60 * 60,
            "user": user_data
        }
        
    except Exception as e:
        frappe.log_error(f"Direct token auth error: {str(e)}", "Mobile Microsoft Auth")
        return {
            "success": False,
            "error": "Authentication failed",
            "error_code": "AUTH_FAILED",
            "details": str(e)
        }
