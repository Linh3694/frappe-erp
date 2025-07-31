"""
Microsoft Authentication API
Handles Microsoft Azure AD authentication and user sync
"""

import frappe
from frappe import _
import requests
import json
from datetime import datetime
import secrets
import base64
import urllib.parse


@frappe.whitelist(allow_guest=True)
def microsoft_login_redirect():
    """Get Microsoft login redirect URL"""
    try:
        # Get Microsoft auth config
        config = get_microsoft_config()
        
        # Generate state parameter for security
        state = secrets.token_urlsafe(32)
        frappe.cache().set_value(f"ms_auth_state_{state}", True, expires_in_sec=600)  # 10 minutes
        
        # Build authorization URL
        auth_url = "https://login.microsoftonline.com/{}/oauth2/v2.0/authorize".format(config["tenant_id"])
        
        params = {
            "client_id": config["client_id"],
            "response_type": "code",
            "redirect_uri": config["redirect_uri"],
            "response_mode": "query",
            "scope": "openid profile email User.Read",
            "state": state
        }
        
        redirect_url = f"{auth_url}?{urllib.parse.urlencode(params)}"
        
        return {
            "status": "success",
            "redirect_url": redirect_url,
            "state": state
        }
        
    except Exception as e:
        frappe.log_error(f"Microsoft login redirect error: {str(e)}", "Microsoft Auth")
        frappe.throw(_("Error generating Microsoft login URL: {0}").format(str(e)))


@frappe.whitelist(allow_guest=True)
def microsoft_callback(code, state):
    """Handle Microsoft authentication callback"""
    try:
        # Verify state parameter
        if not frappe.cache().get_value(f"ms_auth_state_{state}"):
            frappe.throw(_("Invalid state parameter"))
        
        # Clear state
        frappe.cache().delete_value(f"ms_auth_state_{state}")
        
        # Get access token
        token_data = get_microsoft_access_token(code)
        
        # Get user info from Microsoft Graph
        user_info = get_microsoft_user_info(token_data["access_token"])
        
        # Create or update Microsoft user
        ms_user = create_or_update_microsoft_user(user_info)
        
        # Login or create Frappe user
        frappe_user = handle_microsoft_user_login(ms_user)
        
        # Generate JWT token
        from erp.user_management.api.auth import generate_jwt_token
        jwt_token = generate_jwt_token(frappe_user.email)
        
        return {
            "status": "success",
            "message": _("Microsoft login successful"),
            "user": {
                "email": frappe_user.email,
                "full_name": frappe_user.full_name,
                "provider": "microsoft"
            },
            "token": jwt_token
        }
        
    except Exception as e:
        frappe.log_error(f"Microsoft callback error: {str(e)}", "Microsoft Auth")
        frappe.throw(_("Microsoft authentication failed: {0}").format(str(e)))


def sync_microsoft_users_scheduler():
    """Sync users from Microsoft Graph API - For Scheduler (no throw exceptions)"""
    try:
        result = sync_microsoft_users_internal()
        frappe.logger().info(f"Scheduled Microsoft sync completed: {result}")
        return result
    except Exception as e:
        frappe.log_error(f"Scheduled Microsoft users sync error: {str(e)}", "Microsoft Sync Scheduler")
        frappe.logger().error(f"Microsoft sync scheduler failed: {str(e)}")
        return {"status": "error", "message": str(e)}


@frappe.whitelist()
def sync_microsoft_users():
    """Sync users from Microsoft Graph API - For API calls"""
    try:
        return sync_microsoft_users_internal()
    except Exception as e:
        frappe.log_error(f"Microsoft users sync error: {str(e)}", "Microsoft Sync")
        frappe.throw(_("Error syncing Microsoft users: {0}").format(str(e)))


def sync_microsoft_users_internal():
    """Internal sync function - shared logic"""
    # Get app-only access token
    token = get_microsoft_app_token()
    
    # Get all users from Microsoft Graph
    users = get_all_microsoft_users(token)
    
    synced_count = 0
    failed_count = 0
    
    for user_data in users:
        try:
            # Create or update Microsoft user
            ms_user = create_or_update_microsoft_user(user_data)
            synced_count += 1
            
        except Exception as e:
            failed_count += 1
            frappe.log_error(f"Error syncing Microsoft user {user_data.get('id')}: {str(e)}", "Microsoft Sync")
    
    return {
        "status": "success",
        "message": _("Microsoft users sync completed"),
        "synced_count": synced_count,
        "failed_count": failed_count,
        "total_users": len(users)
    }


@frappe.whitelist()
def map_microsoft_user(microsoft_user_id, frappe_user_email=None, create_new=False):
    """Map Microsoft user to Frappe user"""
    try:
        # Get Microsoft user
        ms_user = frappe.get_doc("ERP Microsoft User", microsoft_user_id)
        
        if create_new:
            # Create new Frappe user
            success = ms_user.map_to_frappe_user()
        else:
            # Map to existing user
            if not frappe_user_email:
                frappe.throw(_("Frappe user email is required"))
            
            success = ms_user.map_to_frappe_user(frappe_user_email)
        
        if success:
            return {
                "status": "success",
                "message": _("Microsoft user mapped successfully"),
                "mapped_user": ms_user.mapped_user_id
            }
        else:
            return {
                "status": "failed",
                "message": _("Failed to map Microsoft user"),
                "error": ms_user.sync_error
            }
        
    except Exception as e:
        frappe.log_error(f"Microsoft user mapping error: {str(e)}", "Microsoft Mapping")
        frappe.throw(_("Error mapping Microsoft user: {0}").format(str(e)))


def get_microsoft_config():
    """Get Microsoft authentication configuration from site_config.json or frappe.conf"""
    config = {
        "tenant_id": frappe.conf.get("microsoft_tenant_id") or frappe.get_site_config().get("microsoft_tenant_id"),
        "client_id": frappe.conf.get("microsoft_client_id") or frappe.get_site_config().get("microsoft_client_id"),
        "client_secret": frappe.conf.get("microsoft_client_secret") or frappe.get_site_config().get("microsoft_client_secret"),
        "redirect_uri": frappe.conf.get("microsoft_redirect_uri") or frappe.get_site_config().get("microsoft_redirect_uri") or f"{frappe.utils.get_url()}/api/method/erp.user_management.api.microsoft_auth.microsoft_callback",
        "hourly_sync": frappe.conf.get("microsoft_hourly_sync") or frappe.get_site_config().get("microsoft_hourly_sync", False),
        "group_ids": frappe.conf.get("microsoft_group_ids") or frappe.get_site_config().get("microsoft_group_ids", "dd475730-881b-4c7e-8c8b-13f2160da442,989da314-610e-4be4-9f67-1d6d63e2fc34")
    }
    
    # Validate required fields
    required_fields = ["tenant_id", "client_id", "client_secret"]
    missing_fields = [field for field in required_fields if not config.get(field)]
    
    if missing_fields:
        frappe.throw(_(f"Missing Microsoft configuration: {', '.join(missing_fields)}. Please check your site_config.json"))
    
    return config


def get_microsoft_access_token(code):
    """Exchange authorization code for access token"""
    config = get_microsoft_config()
    
    token_url = f"https://login.microsoftonline.com/{config['tenant_id']}/oauth2/v2.0/token"
    
    data = {
        "client_id": config["client_id"],
        "client_secret": config["client_secret"],
        "code": code,
        "redirect_uri": config["redirect_uri"],
        "grant_type": "authorization_code"
    }
    
    response = requests.post(token_url, data=data)
    
    if response.status_code != 200:
        raise Exception(f"Token request failed: {response.text}")
    
    return response.json()


def get_microsoft_app_token():
    """Get app-only access token for Microsoft Graph"""
    config = get_microsoft_config()
    
    token_url = f"https://login.microsoftonline.com/{config['tenant_id']}/oauth2/v2.0/token"
    
    data = {
        "client_id": config["client_id"],
        "client_secret": config["client_secret"],
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials"
    }
    
    response = requests.post(token_url, data=data)
    
    if response.status_code != 200:
        raise Exception(f"App token request failed: {response.text}")
    
    return response.json()["access_token"]


def get_microsoft_user_info(access_token):
    """Get user information from Microsoft Graph"""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    response = requests.get("https://graph.microsoft.com/v1.0/me", headers=headers)
    
    if response.status_code != 200:
        raise Exception(f"User info request failed: {response.text}")
    
    return response.json()


def get_all_microsoft_users(access_token):
    """Get users from Microsoft Graph groups (not all users)"""
    config = get_microsoft_config()
    group_ids = config.get("group_ids", "").split(",")
    group_ids = [gid.strip() for gid in group_ids if gid.strip()]
    
    if not group_ids:
        raise Exception("No Microsoft group IDs configured")
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    users = []
    # Include all fields we need for sync  
    fields = "id,displayName,givenName,surname,userPrincipalName,mail,jobTitle,department,officeLocation,businessPhones,mobilePhone,employeeId,employeeType,accountEnabled,preferredLanguage,usageLocation,companyName"
    
    # Get users from each group
    for group_id in group_ids:
        frappe.logger().info(f"Syncing users from group: {group_id}")
        
        url = f"https://graph.microsoft.com/v1.0/groups/{group_id}/members?$select={fields}&$top=100"
        
        while url:
            response = requests.get(url, headers=headers)
            
            if response.status_code != 200:
                frappe.log_error(f"Group {group_id} members request failed: {response.text}", "Microsoft Group Sync")
                break  # Skip this group but continue with others
            
            data = response.json()
            group_members = data.get("value", [])
            
            # Filter only user objects (exclude groups, devices, etc.)
            user_members = [member for member in group_members if member.get("@odata.type") == "#microsoft.graph.user"]
            users.extend(user_members)
            
            # Get next page
            url = data.get("@odata.nextLink")
    
    # Remove duplicates based on user ID (in case user is in multiple groups)
    seen_ids = set()
    unique_users = []
    for user in users:
        if user["id"] not in seen_ids:
            seen_ids.add(user["id"])
            unique_users.append(user)
    
    frappe.logger().info(f"Found {len(unique_users)} unique users from {len(group_ids)} groups")
    return unique_users


def create_or_update_microsoft_user(user_data):
    """Create or update Microsoft user in Frappe with local user mapping"""
    try:
        # 1. Create/Update Microsoft User record
        existing = frappe.db.get_value("ERP Microsoft User", {"microsoft_id": user_data["id"]})
        
        if existing:
            # Update existing user
            ms_user = frappe.get_doc("ERP Microsoft User", existing)
        else:
            # Create new user
            ms_user = frappe.get_doc({
                "doctype": "ERP Microsoft User",
                "microsoft_id": user_data["id"]
            })
        
        # Update Microsoft user fields
        ms_user.display_name = user_data.get("displayName")
        ms_user.given_name = user_data.get("givenName")
        ms_user.surname = user_data.get("surname")
        ms_user.user_principal_name = user_data.get("userPrincipalName")
        ms_user.mail = user_data.get("mail")
        ms_user.job_title = user_data.get("jobTitle")
        ms_user.department = user_data.get("department")
        ms_user.office_location = user_data.get("officeLocation")
        ms_user.mobile_phone = user_data.get("mobilePhone")
        ms_user.employee_id = user_data.get("employeeId")
        ms_user.employee_type = user_data.get("employeeType")
        ms_user.account_enabled = user_data.get("accountEnabled", True)
        ms_user.preferred_language = user_data.get("preferredLanguage")
        ms_user.usage_location = user_data.get("usageLocation")
        
        # Handle business phones (array)
        if user_data.get("businessPhones"):
            ms_user.business_phones = ", ".join(user_data["businessPhones"])
        
        ms_user.last_sync_at = datetime.now()
        ms_user.sync_status = "synced"
        ms_user.sync_error = ""
        
        # 2. Find or create corresponding Frappe User
        local_user = find_or_create_frappe_user(ms_user, user_data)
        
        # 3. Update mapping
        if local_user:
            ms_user.mapped_user_id = local_user.name
            ms_user.sync_status = "synced"
        
        ms_user.save()
        
        # 4. Create or update ERP User Profile
        if local_user:
            create_or_update_user_profile(local_user, ms_user, user_data)
        
        return ms_user
        
    except Exception as e:
        # Mark as failed sync
        if 'ms_user' in locals():
            ms_user.sync_status = "failed"
            ms_user.sync_error = str(e)
            ms_user.save()
        
        raise e


def find_or_create_frappe_user(ms_user, user_data):
    """Find existing Frappe user or create new one based on Microsoft data"""
    try:
        local_user = None
        
        # 1. First try to find by existing mapping
        if hasattr(ms_user, 'mapped_user_id') and ms_user.mapped_user_id:
            try:
                local_user = frappe.get_doc("User", ms_user.mapped_user_id)
                if local_user.enabled:
                    # Update existing user
                    update_frappe_user(local_user, ms_user, user_data)
                    return local_user
            except frappe.DoesNotExistError:
                pass
        
        # 2. Try to find by email
        email = user_data.get("mail") or user_data.get("userPrincipalName")
        if email:
            existing_user = frappe.db.get_value("User", {"email": email})
            if existing_user:
                local_user = frappe.get_doc("User", existing_user)
                if local_user.enabled:
                    # Update existing user
                    update_frappe_user(local_user, ms_user, user_data)
                    return local_user
        
        # 3. Try to find by userPrincipalName if different from email
        upn = user_data.get("userPrincipalName")
        if upn and upn != email:
            existing_user = frappe.db.get_value("User", {"email": upn})
            if existing_user:
                local_user = frappe.get_doc("User", existing_user)
                if local_user.enabled:
                    # Update existing user
                    update_frappe_user(local_user, ms_user, user_data)
                    return local_user
        
        # 4. Create new user if not found
        if not local_user and email:
            local_user = create_frappe_user(ms_user, user_data)
            return local_user
            
        return None
        
    except Exception as e:
        frappe.log_error(f"Error in find_or_create_frappe_user: {str(e)}", "Microsoft User Mapping")
        return None


def create_frappe_user(ms_user, user_data):
    """Create new Frappe user from Microsoft data"""
    try:
        email = user_data.get("mail") or user_data.get("userPrincipalName")
        if not email:
            return None
            
        # Create new user
        user_doc = frappe.get_doc({
            "doctype": "User",
            "email": email,
            "first_name": user_data.get("givenName") or "",
            "last_name": user_data.get("surname") or "",
            "full_name": user_data.get("displayName") or email,
            "enabled": user_data.get("accountEnabled", True),
            "user_type": "System User",
            "send_welcome_email": 0,
            # Custom fields for Microsoft data
            "employee_id": user_data.get("employeeId"),
            "department": user_data.get("department"),
            "designation": user_data.get("jobTitle"),
            "location": user_data.get("officeLocation"),
            "mobile_no": user_data.get("mobilePhone"),
            "phone": ", ".join(user_data.get("businessPhones", [])) if user_data.get("businessPhones") else None
        })
        
        user_doc.flags.ignore_permissions = True
        user_doc.insert()
        
        frappe.logger().info(f"Created Frappe user: {email}")
        return user_doc
        
    except Exception as e:
        frappe.log_error(f"Error creating Frappe user: {str(e)}", "Microsoft User Creation")
        return None


def update_frappe_user(user_doc, ms_user, user_data):
    """Update existing Frappe user with Microsoft data"""
    try:
        # Update basic info
        user_doc.first_name = user_data.get("givenName") or user_doc.first_name
        user_doc.last_name = user_data.get("surname") or user_doc.last_name
        user_doc.full_name = user_data.get("displayName") or user_doc.full_name
        user_doc.enabled = user_data.get("accountEnabled", True)
        
        # Update Microsoft-specific fields (if they exist)
        if hasattr(user_doc, 'employee_id'):
            user_doc.employee_id = user_data.get("employeeId") or user_doc.employee_id
        if hasattr(user_doc, 'department'):
            user_doc.department = user_data.get("department") or user_doc.department
        if hasattr(user_doc, 'designation'):
            user_doc.designation = user_data.get("jobTitle") or user_doc.designation
        if hasattr(user_doc, 'location'):
            user_doc.location = user_data.get("officeLocation") or user_doc.location
        if hasattr(user_doc, 'mobile_no'):
            user_doc.mobile_no = user_data.get("mobilePhone") or user_doc.mobile_no
        if hasattr(user_doc, 'phone'):
            business_phones = ", ".join(user_data.get("businessPhones", [])) if user_data.get("businessPhones") else None
            user_doc.phone = business_phones or user_doc.phone
        
        user_doc.flags.ignore_permissions = True
        user_doc.save()
        
        frappe.logger().info(f"Updated Frappe user: {user_doc.email}")
        return user_doc
        
    except Exception as e:
        frappe.log_error(f"Error updating Frappe user {user_doc.email}: {str(e)}", "Microsoft User Update")
        return user_doc


def create_or_update_user_profile(frappe_user, ms_user, user_data):
    """Create or update ERP User Profile from Microsoft data"""
    try:
        # Check if ERP User Profile already exists
        existing_profile = frappe.db.get_value("ERP User Profile", {"user": frappe_user.name})
        
        if existing_profile:
            # Update existing profile
            profile = frappe.get_doc("ERP User Profile", existing_profile)
        else:
            # Create new profile
            profile = frappe.get_doc({
                "doctype": "ERP User Profile",
                "user": frappe_user.name
            })
        
        # Update profile fields with Microsoft data
        profile.full_name = user_data.get("displayName") or frappe_user.full_name
        profile.first_name = user_data.get("givenName") or frappe_user.first_name
        profile.last_name = user_data.get("surname") or frappe_user.last_name
        profile.email = user_data.get("mail") or user_data.get("userPrincipalName") or frappe_user.email
        
        # Microsoft-specific fields
        profile.employee_id = user_data.get("employeeId")
        profile.department = user_data.get("department")
        profile.job_title = user_data.get("jobTitle")
        profile.office_location = user_data.get("officeLocation")
        profile.mobile_phone = user_data.get("mobilePhone")
        profile.company_name = user_data.get("companyName")
        
        # Handle business phones
        if user_data.get("businessPhones"):
            profile.business_phones = ", ".join(user_data["businessPhones"])
        
        # Additional info
        profile.account_enabled = user_data.get("accountEnabled", True)
        profile.employee_type = user_data.get("employeeType")
        profile.preferred_language = user_data.get("preferredLanguage")
        profile.usage_location = user_data.get("usageLocation")
        
        # Sync info
        profile.microsoft_user_id = ms_user.microsoft_id
        profile.last_microsoft_sync = datetime.now()
        profile.sync_source = "Microsoft 365"
        
        profile.flags.ignore_permissions = True
        if existing_profile:
            profile.save()
        else:
            profile.insert()
        
        frappe.logger().info(f"Created/Updated ERP User Profile for: {frappe_user.email}")
        return profile
        
    except Exception as e:
        frappe.log_error(f"Error creating/updating ERP User Profile for {frappe_user.email}: {str(e)}", "ERP User Profile Sync")
        return None


@frappe.whitelist()
def sync_existing_users_to_profiles():
    """Sync all existing Microsoft users to ERP User Profiles"""
    try:
        # Get all Microsoft users that have mapped Frappe users
        ms_users = frappe.db.sql("""
            SELECT name, microsoft_id, mapped_user_id 
            FROM `tabERP Microsoft User` 
            WHERE mapped_user_id IS NOT NULL AND mapped_user_id != ''
        """, as_dict=True)
        
        synced_count = 0
        failed_count = 0
        
        for ms_user_data in ms_users:
            try:
                # Get full Microsoft user doc
                ms_user = frappe.get_doc("ERP Microsoft User", ms_user_data.name)
                
                # Get Frappe user
                frappe_user = frappe.get_doc("User", ms_user_data.mapped_user_id)
                
                # Reconstruct user_data from Microsoft user
                user_data = {
                    "id": ms_user.microsoft_id,
                    "displayName": ms_user.display_name,
                    "givenName": ms_user.given_name,
                    "surname": ms_user.surname,
                    "userPrincipalName": ms_user.user_principal_name,
                    "mail": ms_user.mail,
                    "jobTitle": ms_user.job_title,
                    "department": ms_user.department,
                    "officeLocation": ms_user.office_location,
                    "businessPhones": ms_user.business_phones.split(", ") if ms_user.business_phones else [],
                    "mobilePhone": ms_user.mobile_phone,
                    "employeeId": ms_user.employee_id,
                    "employeeType": ms_user.employee_type,
                    "accountEnabled": ms_user.account_enabled,
                    "preferredLanguage": ms_user.preferred_language,
                    "usageLocation": ms_user.usage_location,
                    "companyName": ""  # Not stored in Microsoft user
                }
                
                # Create/update user profile
                profile = create_or_update_user_profile(frappe_user, ms_user, user_data)
                if profile:
                    synced_count += 1
                else:
                    failed_count += 1
                    
            except Exception as e:
                failed_count += 1
                frappe.log_error(f"Error syncing user profile for {ms_user_data.microsoft_id}: {str(e)}", "User Profile Sync")
        
        return {
            "status": "success",
            "message": _("User profiles sync completed"),
            "synced_count": synced_count,
            "failed_count": failed_count,
            "total_users": len(ms_users)
        }
        
    except Exception as e:
        frappe.log_error(f"Error syncing user profiles: {str(e)}", "User Profile Sync")
        frappe.throw(_("Error syncing user profiles: {0}").format(str(e)))


@frappe.whitelist()
def full_microsoft_sync():
    """Complete Microsoft sync: Users + Frappe Users + User Profiles"""
    try:
        results = {}
        
        # 1. Sync Microsoft users
        frappe.logger().info("Starting Microsoft users sync...")
        ms_result = sync_microsoft_users_internal()
        results["microsoft_users"] = ms_result
        
        # 2. Sync User Profiles
        frappe.logger().info("Starting User Profiles sync...")
        profile_result = sync_existing_users_to_profiles()
        results["user_profiles"] = profile_result
        
        # 3. Get final counts
        ms_count = frappe.db.sql("SELECT COUNT(*) FROM `tabERP Microsoft User`")[0][0]
        profile_count = frappe.db.sql("SELECT COUNT(*) FROM `tabERP User Profile`")[0][0]
        user_count = frappe.db.sql("SELECT COUNT(*) FROM `tabUser` WHERE user_type = 'System User' AND name != 'Administrator'")[0][0]
        
        results["final_counts"] = {
            "microsoft_users": ms_count,
            "user_profiles": profile_count,
            "frappe_users": user_count
        }
        
        return {
            "status": "success",
            "message": _("Full Microsoft sync completed successfully"),
            "results": results
        }
        
    except Exception as e:
        frappe.log_error(f"Error in full Microsoft sync: {str(e)}", "Full Microsoft Sync")
        frappe.throw(_("Error in full Microsoft sync: {0}").format(str(e)))


def handle_microsoft_user_login(ms_user):
    """Handle Microsoft user login"""
    try:
        # Check if already mapped to Frappe user
        if ms_user.mapped_user_id:
            frappe_user = frappe.get_doc("User", ms_user.mapped_user_id)
            
            # Update user profile
            update_user_profile_from_microsoft(frappe_user.email, ms_user)
            
            return frappe_user
        
        # Check if Frappe user exists with same email
        email = ms_user.mail or ms_user.user_principal_name
        if frappe.db.exists("User", email):
            # Map to existing user
            ms_user.map_to_frappe_user(email)
            frappe_user = frappe.get_doc("User", email)
            
            # Update user profile
            update_user_profile_from_microsoft(email, ms_user)
            
            return frappe_user
        
        # Create new Frappe user
        ms_user.map_to_frappe_user()
        frappe_user = frappe.get_doc("User", ms_user.mapped_user_id)
        
        # Create user profile
        create_user_profile_from_microsoft(frappe_user.email, ms_user)
        
        return frappe_user
        
    except Exception as e:
        frappe.log_error(f"Microsoft user login error: {str(e)}", "Microsoft Login")
        raise e


def update_user_profile_from_microsoft(user_email, ms_user):
    """Update user profile with Microsoft data"""
    try:
        # Get or create user profile
        profile_name = frappe.db.get_value("ERP User Profile", {"user": user_email})
        
        if profile_name:
            profile = frappe.get_doc("ERP User Profile", profile_name)
        else:
            profile = frappe.get_doc({
                "doctype": "ERP User Profile",
                "user": user_email
            })
        
        # Update fields from Microsoft data
        profile.provider = "microsoft"
        profile.microsoft_id = ms_user.microsoft_id
        profile.job_title = ms_user.job_title
        profile.department = ms_user.department
        profile.employee_code = ms_user.employee_id
        
        # Generate username if not set
        if not profile.username and ms_user.user_principal_name:
            profile.username = ms_user.user_principal_name.split('@')[0]
        
        profile.save()
        
        return profile
        
    except Exception as e:
        frappe.log_error(f"User profile update error: {str(e)}", "Microsoft Profile Update")
        raise e


def create_user_profile_from_microsoft(user_email, ms_user):
    """Create user profile from Microsoft data"""
    try:
        profile = frappe.get_doc({
            "doctype": "ERP User Profile",
            "user": user_email,
            "provider": "microsoft",
            "microsoft_id": ms_user.microsoft_id,
            "job_title": ms_user.job_title,
            "department": ms_user.department,
            "employee_code": ms_user.employee_id,
            "username": ms_user.user_principal_name.split('@')[0] if ms_user.user_principal_name else None,
            "active": ms_user.account_enabled
        })
        
        profile.insert()
        
        return profile
        
    except Exception as e:
        frappe.log_error(f"User profile creation error: {str(e)}", "Microsoft Profile Creation")
        raise e


@frappe.whitelist()
def get_microsoft_sync_stats():
    """Get Microsoft sync statistics"""
    try:
        stats = {
            "total_microsoft_users": frappe.db.count("ERP Microsoft User"),
            "synced_users": frappe.db.count("ERP Microsoft User", {"sync_status": "synced"}),
            "pending_users": frappe.db.count("ERP Microsoft User", {"sync_status": "pending"}),
            "failed_users": frappe.db.count("ERP Microsoft User", {"sync_status": "failed"}),
            "mapped_users": frappe.db.count("ERP Microsoft User", {"mapped_user_id": ["!=", ""]}),
            "unmapped_users": frappe.db.count("ERP Microsoft User", {"mapped_user_id": ["in", ["", None]]})
        }
        
        return {
            "status": "success",
            "stats": stats
        }
        
    except Exception as e:
        frappe.log_error(f"Microsoft sync stats error: {str(e)}", "Microsoft Stats")
        frappe.throw(_("Error getting Microsoft sync stats: {0}").format(str(e)))


@frappe.whitelist()
def test_microsoft_config():
    """Test Microsoft configuration"""
    try:
        config = get_microsoft_config()
        
        # Test if all required fields are present
        required_fields = ["tenant_id", "client_id", "client_secret"]
        config_status = {}
        
        for field in required_fields:
            if config.get(field):
                config_status[field] = "✓ Configured"
            else:
                config_status[field] = "✗ Missing"
        
        # Mask sensitive data
        display_config = {
            "tenant_id": config.get("tenant_id", "Not configured"),
            "client_id": config.get("client_id", "Not configured"),
            "client_secret": "***" + config.get("client_secret", "")[-4:] if config.get("client_secret") else "Not configured",
            "redirect_uri": config.get("redirect_uri", "Not configured"),
            "hourly_sync": config.get("hourly_sync", False)
        }
        
        return {
            "status": "success",
            "message": "Microsoft configuration test completed",
            "config": display_config,
            "config_status": config_status,
            "all_configured": all(config.get(field) for field in required_fields)
        }
        
    except Exception as e:
        frappe.log_error(f"Microsoft config test error: {str(e)}", "Microsoft Config Test")
        return {
            "status": "error",
            "message": str(e),
            "config": {},
            "config_status": {},
            "all_configured": False
        }


@frappe.whitelist()
def test_microsoft_connection():
    """Test connection to Microsoft Graph API"""
    try:
        # Get app-only token to test connection
        token = get_microsoft_app_token()
        
        # Test basic Graph API call
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        # Try to get basic organization info
        response = requests.get("https://graph.microsoft.com/v1.0/organization", headers=headers)
        
        if response.status_code == 200:
            org_data = response.json()
            org_info = org_data.get("value", [{}])[0] if org_data.get("value") else {}
            
            return {
                "status": "success",
                "message": "Microsoft Graph API connection successful",
                "connection_test": "✓ Connected",
                "organization": {
                    "display_name": org_info.get("displayName", "Unknown"),
                    "id": org_info.get("id", "Unknown"),
                    "verified_domains": len(org_info.get("verifiedDomains", []))
                }
            }
        else:
            return {
                "status": "error",
                "message": f"Microsoft Graph API connection failed: {response.text}",
                "connection_test": "✗ Failed",
                "status_code": response.status_code
            }
        
    except Exception as e:
        frappe.log_error(f"Microsoft connection test error: {str(e)}", "Microsoft Connection Test")
        return {
            "status": "error",
            "message": str(e),
            "connection_test": "✗ Failed"
        }


@frappe.whitelist()
def get_microsoft_test_users(limit=5):
    """Get a few Microsoft users for testing"""
    try:
        # Get app-only token
        token = get_microsoft_app_token()
        
        # Get first few users
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        response = requests.get(f"https://graph.microsoft.com/v1.0/users?$top={limit}", headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            users = data.get("value", [])
            
            # Clean up user data for display
            clean_users = []
            for user in users:
                clean_users.append({
                    "id": user.get("id"),
                    "displayName": user.get("displayName"),
                    "userPrincipalName": user.get("userPrincipalName"),
                    "mail": user.get("mail"),
                    "jobTitle": user.get("jobTitle"),
                    "department": user.get("department"),
                    "accountEnabled": user.get("accountEnabled")
                })
            
            return {
                "status": "success",
                "message": f"Retrieved {len(clean_users)} test users",
                "users": clean_users,
                "total_found": len(clean_users)
            }
        else:
            return {
                "status": "error",
                "message": f"Failed to get test users: {response.text}",
                "status_code": response.status_code
            }
        
    except Exception as e:
        frappe.log_error(f"Microsoft test users error: {str(e)}", "Microsoft Test Users")
        return {
            "status": "error",
            "message": str(e)
        }