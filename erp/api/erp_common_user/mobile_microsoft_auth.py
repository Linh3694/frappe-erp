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
            
            # For mobile_microsoft_callback endpoint, always try mobile redirect URI first
            # Try common mobile redirect URI patterns
            if mobile_redirect_uri:
                frappe.logger().info(f"Using provided mobile redirect URI: {mobile_redirect_uri}")
                redirect_uri_to_use = mobile_redirect_uri
            else:
                # Auto-detect mobile redirect URI from the authorization code error
                # Since we know the authorization was made with exp://... URI, try to use it
                frappe.logger().info("No redirect_uri parameter, trying common mobile patterns")
                
                # Try to extract the actual redirect URI from the authorization request
                # For now, use a common pattern - we'll improve this
                user_agent = frappe.request.headers.get('User-Agent', '')
                if 'WellspringMobile' in user_agent:
                    # This is a mobile request, try to get mobile redirect URI
                    # We need to use the same redirect URI that was used for authorization
                    # Since we can't easily get it, we'll try the URL from the error message if available
                    redirect_uri_to_use = "staffportal://auth"  # Try custom scheme first
                    frappe.logger().info(f"Detected mobile request, using custom scheme: {redirect_uri_to_use}")
                else:
                    redirect_uri_to_use = None
            
            # Try to exchange token with mobile redirect URI using public client method
            if redirect_uri_to_use:
                try:
                    frappe.logger().info(f"Attempting public client token exchange with mobile redirect URI: {redirect_uri_to_use}")
                    token_data = get_microsoft_access_token_public_client(code, redirect_uri_to_use)
                except Exception as redirect_error:
                    frappe.logger().error(f"Public client mobile redirect URI failed: {str(redirect_error)}")
                    
                    # If custom scheme failed, try exp:// scheme pattern
                    if redirect_uri_to_use == "staffportal://auth":
                        try:
                            # Try a common exp:// pattern
                            exp_redirect_uri = "exp://10.1.32.175:8081/--/auth"
                            frappe.logger().info(f"Retrying public client with exp:// scheme: {exp_redirect_uri}")
                            token_data = get_microsoft_access_token_public_client(code, exp_redirect_uri)
                        except Exception as exp_error:
                            frappe.logger().error(f"Public client exp:// scheme also failed: {str(exp_error)}")
                            frappe.logger().info("Falling back to confidential client with default web redirect URI")
                            token_data = get_microsoft_access_token(code)
                    else:
                        frappe.logger().info("Falling back to confidential client with default web redirect URI")
                        token_data = get_microsoft_access_token(code)
            else:
                # Fallback to web redirect URI
                frappe.logger().info("Using default web redirect URI for token exchange")
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
        
        # Check if user profile exists in ERP
        user_profile = None
        try:
            user_profile = frappe.get_doc("ERP User Profile", {"email": user_email})
            frappe.logger().info(f"Found ERP User Profile for: {user_email}")
        except frappe.DoesNotExistError:
            frappe.logger().warning(f"ERP User Profile not found for: {user_email}")
            return {
                "success": False,
                "error": "Tài khoản chưa được đăng ký trong hệ thống",
                "error_code": "USER_NOT_REGISTERED",
                "user_email": user_email
            }
        except Exception as e:
            frappe.logger().error(f"Error checking user profile: {str(e)}")
            return {
                "success": False,
                "error": "Error checking user registration",
                "error_code": "USER_CHECK_FAILED",
                "details": str(e)
            }
        
        # Create or update Microsoft user record
        try:
            ms_user = create_or_update_microsoft_user(user_info)
            frappe.logger().info(f"Microsoft user record updated")
        except Exception as e:
            frappe.logger().warning(f"Failed to update Microsoft user record: {str(e)}")
            # Continue anyway, this is not critical
            ms_user = None
        
        # Login or create Frappe user
        try:
            frappe_user = handle_microsoft_user_login(ms_user)
            frappe.logger().info(f"Frappe user login handled: {frappe_user.email}")
        except Exception as e:
            frappe.logger().error(f"Failed to handle Frappe user login: {str(e)}")
            return {
                "success": False,
                "error": "Failed to login user",
                "error_code": "LOGIN_FAILED",
                "details": str(e)
            }
        
        # Update user profile with latest Microsoft data
        if user_profile and user_info:
            try:
                # Update profile with fresh data from Microsoft
                if user_info.get("jobTitle"):
                    user_profile.job_title = user_info.get("jobTitle")
                if user_info.get("department"):
                    user_profile.department = user_info.get("department")
                if user_info.get("employeeId"):
                    user_profile.employee_code = user_info.get("employeeId")
                
                if ms_user:
                    user_profile.microsoft_id = ms_user.microsoft_id
                user_profile.provider = "microsoft"
                user_profile.save(ignore_permissions=True)
                frappe.logger().info(f"User profile updated with Microsoft data")
            except Exception as e:
                frappe.logger().warning(f"Failed to update user profile: {str(e)}")
                # Continue anyway, this is not critical
        
        # Commit changes
        frappe.db.commit()
        
        # Generate JWT token for API access
        try:
            from erp.api.erp_common_user.auth import generate_jwt_token
            jwt_token = generate_jwt_token(frappe_user.email)
            frappe.logger().info(f"JWT token generated")
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
        
        # Create user data for mobile app
        user_data = {
            "email": user_email,
            "full_name": frappe_user.full_name,
            "first_name": frappe_user.first_name or "",
            "last_name": frappe_user.last_name or "",
            "provider": "microsoft",
            "microsoft_id": ms_user.microsoft_id if ms_user else None,
            "job_title": user_profile.job_title if user_profile and user_profile.job_title else "",
            "department": user_profile.department if user_profile and user_profile.department else "",
            "employee_code": user_profile.employee_code if user_profile and user_profile.employee_code else "",
            "user_role": user_profile.user_role if user_profile else "user",
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
        
        # Check if user profile exists
        try:
            user_profile = frappe.get_doc("ERP User Profile", {"email": user_email})
        except frappe.DoesNotExistError:
            return {
                "success": False,
                "error": "Tài khoản chưa được đăng ký trong hệ thống",
                "error_code": "USER_NOT_REGISTERED",
                "user_email": user_email
            }
        
        # Create or update Microsoft user record
        ms_user = create_or_update_microsoft_user(user_info)
        
        # Login or create Frappe user
        frappe_user = handle_microsoft_user_login(ms_user)
        
        # Generate JWT token
        from erp.api.erp_common_user.auth import generate_jwt_token
        jwt_token = generate_jwt_token(frappe_user.email)
        
        # Get user roles
        frappe_roles = frappe.get_roles(frappe_user.email) or ["Guest"]
        
        # Create user data
        user_data = {
            "email": user_email,
            "full_name": frappe_user.full_name,
            "provider": "microsoft",
            "job_title": user_profile.job_title if user_profile else "",
            "department": user_profile.department if user_profile else "",
            "employee_code": user_profile.employee_code if user_profile else "",
            "user_role": user_profile.user_role if user_profile else "user",
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
