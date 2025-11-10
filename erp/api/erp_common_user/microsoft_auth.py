"""
Microsoft Authentication API
Handles Microsoft Azure AD authentication and user sync
"""

import frappe
from frappe import _
import requests
import json
from datetime import datetime
from datetime import timedelta
import secrets
import base64
import urllib.parse
from erp.utils.api_response import success_response, error_response


def _extract_origin(url: str | None) -> str | None:
    """Trả về origin ở dạng scheme://host[:port] từ 1 URL/Origin bất kỳ.

    Ví dụ: https://a.example.com:5173/path?q=1 -> https://a.example.com:5173
    """
    try:
        if not url:
            return None
        # Nếu là list, lấy phần tử đầu
        if isinstance(url, (list, tuple)):
            for item in url:
                o = _extract_origin(str(item))
                if o:
                    return o
            return None
        url = str(url).strip()
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme and parsed.netloc:
            origin = f"{parsed.scheme}://{parsed.netloc}"
            return origin.rstrip('/')
        # Nếu thiếu scheme nhưng có dạng host hoặc host:port → mặc định https
        # urlparse("example.com:3000").netloc == '' và path == 'example.com:3000'
        candidate = url
        if '://' in candidate:
            # Trường hợp origin không có path: scheme://host[:port]
            try:
                scheme = candidate.split('://', 1)[0]
                hostport = candidate.split('://', 1)[1].split('/', 1)[0]
                if scheme and hostport:
                    return f"{scheme}://{hostport}".rstrip('/')
            except Exception:
                pass
        else:
            # Không có scheme → thêm https làm mặc định
            # Hỗ trợ cả 'localhost:3000' hoặc 'example.com'
            hostport = candidate.split('/', 1)[0]
            if hostport:
                return f"https://{hostport}".rstrip('/')
        return None
    except Exception:
        return None


def _get_default_frontend_origin() -> str | None:
    """Lấy origin mặc định từ cấu hình `frontend_url`."""
    try:
        cfg_val = (
            (frappe.conf and frappe.conf.get("frontend_url"))
            or (frappe.get_site_config() and frappe.get_site_config().get("frontend_url"))
        )
        # Có thể là string hoặc list
        if isinstance(cfg_val, (list, tuple)):
            for item in cfg_val:
                origin = _extract_origin(str(item))
                if origin:
                    return origin
            return None
        origin = _extract_origin(cfg_val)
        return origin
    except Exception:
        return None


def _get_allowed_frontend_origins() -> list[str]:
    """Đọc allowlist origins cho frontend từ site_config/frappe.conf.

    Hỗ trợ các key:
    - frontend_allowed_origins (list hoặc chuỗi CSV)
    - frontend_allowlist (list hoặc chuỗi CSV)
    - frontend_urls (list hoặc chuỗi CSV)
    Ngoài ra luôn bao gồm `frontend_url` làm mặc định nếu có.
    """
    origins: list[str] = []
    try:
        candidates = []
        for source in (frappe.conf, frappe.get_site_config()):
            if not source:
                continue
            for key in ("frontend_allowed_origins", "frontend_allowlist", "frontend_urls", "allow_cors", "frontend_url"):
                raw = source.get(key)
                if raw:
                    if isinstance(raw, list):
                        candidates.extend([str(x) for x in raw])
                    else:
                        candidates.extend([s.strip() for s in str(raw).split(',') if s.strip()])
        # Luôn thêm default frontend
        default_origin = _get_default_frontend_origin()
        if default_origin:
            candidates.append(default_origin)
        # Chuẩn hóa và loại trùng
        normalized = []
        seen = set()
        for c in candidates:
            o = _extract_origin(c)
            if o and o not in seen:
                seen.add(o)
                normalized.append(o)
        origins = normalized
    except Exception:
        pass
    return origins


def _is_allowed_origin(origin: str | None, allowlist: list[str]) -> bool:
    """Kiểm tra origin có nằm trong allowlist không. Nếu allowlist rỗng, chỉ cho phép default."""
    if not origin:
        return False
    if allowlist:
        return origin.rstrip('/') in {o.rstrip('/') for o in allowlist}
    default_origin = _get_default_frontend_origin()
    return origin.rstrip('/') == (default_origin.rstrip('/') if default_origin else None)


def _pick_frontend_origin(frontend_param: str | None) -> str | None:
    """Chọn origin frontend hợp lệ theo thứ tự ưu tiên: param -> Origin header -> Referer -> default.

    Chỉ trả về origin nếu nằm trong allowlist, nếu không sẽ fallback về default.
    """
    allowlist = _get_allowed_frontend_origins()

    # 1) Tham số truyền vào
    cand = _extract_origin(frontend_param)
    if _is_allowed_origin(cand, allowlist):
        return cand

    # 2) Header Origin
    try:
        origin_hdr = None
        try:
            origin_hdr = frappe.get_request_header('Origin')
        except Exception:
            origin_hdr = None
        if not origin_hdr and getattr(frappe, 'request', None):
            origin_hdr = getattr(frappe.request, 'headers', {}).get('Origin') if hasattr(frappe.request, 'headers') else None
        cand = _extract_origin(origin_hdr)
        if _is_allowed_origin(cand, allowlist):
            return cand
    except Exception:
        pass

    # 3) Header Referer
    try:
        referer = None
        try:
            referer = frappe.get_request_header('Referer')
        except Exception:
            referer = None
        if not referer and getattr(frappe, 'request', None):
            referer = getattr(frappe.request, 'headers', {}).get('Referer') if hasattr(frappe.request, 'headers') else None
        cand = _extract_origin(referer)
        if _is_allowed_origin(cand, allowlist):
            return cand
    except Exception:
        pass

    # 4) Fallback default
    return _get_default_frontend_origin()


@frappe.whitelist(allow_guest=True)
def microsoft_login_redirect(frontend: str | None = None):
    """Get Microsoft login redirect URL.

    Hỗ trợ đa frontend bằng cách xác định origin frontend từ:
    - Tham số `frontend` (nếu truyền vào)
    - Header `Origin` hoặc `Referer` của request khởi tạo
    - Fallback cấu hình `frontend_url`

    Origin đã chọn sẽ được lưu theo `state` để callback sử dụng redirect phù hợp.
    """
    try:
        # Get Microsoft auth config
        config = get_microsoft_config()
        
        # Generate state parameter for security
        state = secrets.token_urlsafe(32)
        frappe.cache().set_value(f"ms_auth_state_{state}", True, expires_in_sec=600)  # 10 minutes
        
        # Xác định origin frontend và lưu theo state để callback dùng lại
        try:
            chosen_origin = _pick_frontend_origin(frontend)
            if chosen_origin:
                frappe.cache().set_value(f"ms_auth_frontend_{state}", chosen_origin, expires_in_sec=600)
        except Exception:
            pass
        
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

        return success_response(
            data={
                "redirect_url": redirect_url,
                "state": state
            },
            message="Microsoft login URL generated successfully"
        )
        
    except Exception as e:
        frappe.log_error("Microsoft Auth", f"Microsoft login redirect error: {str(e)}")
        return error_response(
            message=f"Error generating Microsoft login URL: {str(e)}",
            code="MICROSOFT_LOGIN_REDIRECT_ERROR"
        )


@frappe.whitelist(allow_guest=True)
def microsoft_callback(code, state):
    """Handle Microsoft authentication callback với redirect động theo frontend origin đã lưu."""
    try:
        # Verify state parameter
        if not frappe.cache().get_value(f"ms_auth_state_{state}"):
            frappe.throw(_("Invalid state parameter"))
        
        # Clear state
        frappe.cache().delete_value(f"ms_auth_state_{state}")
        # Lấy origin frontend đã lưu (nếu có) để dùng cho redirect
        frontend_origin_cached = frappe.cache().get_value(f"ms_auth_frontend_{state}")
        if frontend_origin_cached:
            try:
                frappe.cache().delete_value(f"ms_auth_frontend_{state}")
            except Exception:
                pass
        
        # Get access token
        token_data = get_microsoft_access_token(code)
        
        # Get user info from Microsoft Graph
        user_info = get_microsoft_user_info(token_data["access_token"])
        user_email = user_info.get("mail") or user_info.get("userPrincipalName")
        
        if not user_email:
            frappe.throw(_("No email found in Microsoft account"))

        
        # Skip ERP User Profile - use only Frappe User
        user_profile = None
        
        # Create or update Microsoft user record
        ms_user = create_or_update_microsoft_user(user_info)

        # Login or create Frappe user
        frappe_user = handle_microsoft_user_login(ms_user)

        # Cập nhật trực tiếp các trường trên User từ Microsoft
        try:
            if frappe_user and user_info:
                if hasattr(frappe_user, 'department') and user_info.get("department"):
                    frappe_user.department = user_info.get("department")
                if hasattr(frappe_user, 'designation') and user_info.get("jobTitle"):
                    frappe_user.designation = user_info.get("jobTitle")
                if hasattr(frappe_user, 'employee_code') and user_info.get("employeeId"):
                    frappe_user.employee_code = user_info.get("employeeId")
                if hasattr(frappe_user, 'microsoft_id') and getattr(ms_user, 'microsoft_id', None):
                    frappe_user.microsoft_id = ms_user.microsoft_id
                if hasattr(frappe_user, 'provider'):
                    frappe_user.provider = "microsoft"
                frappe_user.flags.ignore_permissions = True
                frappe_user.save()
        except Exception:
            pass
        
        # Commit any changes before querying roles
        frappe.db.commit()
        
        # Generate JWT token
        from erp.api.erp_common_user.auth import generate_jwt_token
        
        # Ensure user exists in database before generating JWT
        if not frappe.db.exists("User", frappe_user.email):
            frappe.throw(_("User not found in database: {0}").format(frappe_user.email))
        
        frappe.logger().info(f"Generating JWT token for Microsoft user: {frappe_user.email}")
        jwt_token = generate_jwt_token(frappe_user.email)
        frappe.logger().info(f"Generated JWT token: {jwt_token[:30] + '...' if jwt_token else 'None'}")
        
        # Get Frappe roles for the user
        frappe_roles = []
        manual_roles = []
        try:
            # Get all roles (including automatic ones)
            frappe_roles = frappe.get_roles(frappe_user.email) or []

            
            # Get only manual/assigned roles (without automatic ones)
            from frappe import permissions as frappe_permissions
            manual_roles = frappe_permissions.get_roles(frappe_user.email, with_standard=False) or []

                
        except Exception as e:

            frappe_roles = ["All", "Guest"]  # Fallback
            manual_roles = []
        
        # Ensure we have fallback roles
        if not frappe_roles:
            frappe_roles = ["All", "Guest"]
            

        
        # Create user data using only Frappe User and Microsoft info
        user_data = {
            "email": user_email,  # Use Microsoft email as primary
            "full_name": frappe_user.full_name,
            "first_name": frappe_user.first_name or "",
            "last_name": frappe_user.last_name or "",
            "provider": "microsoft",
            "microsoft_id": ms_user.microsoft_id if ms_user else None,
            "job_title": user_info.get("jobTitle", ""),
            "department": user_info.get("department", ""),
            "employee_code": user_info.get("employeeId", ""),
            "user_role": "user",  # Default role
            "frappe_roles": frappe_roles,  # All Frappe roles (including automatic)
            "manual_roles": manual_roles,  # Only manually assigned roles
            "active": frappe_user.enabled,
            "username": user_email,  # Use email as username
            "account_enabled": user_info.get("accountEnabled", True)
        }

        
        # Encode data for URL (base64 encode to avoid URL encoding issues)
        user_json = json.dumps(user_data)
        user_encoded = base64.b64encode(user_json.encode()).decode()
        
        # Chọn frontend origin để redirect ưu tiên theo cache; fallback về cấu hình, luôn kiểm tra allowlist
        allowlist = _get_allowed_frontend_origins()
        if frontend_origin_cached and _is_allowed_origin(frontend_origin_cached, allowlist):
            frontend_origin = frontend_origin_cached
        else:
            default_frontend = frappe.conf.get("frontend_url") or frappe.get_site_config().get("frontend_url") or "http://localhost:3000"
            frontend_origin = _extract_origin(default_frontend) or default_frontend.rstrip('/')

        # Redirect tới callback path chuẩn trên frontend
        callback_url = f"{frontend_origin}/auth/microsoft/callback?success=true&token={jwt_token}"
        
        # Set redirect response
        frappe.local.response["type"] = "redirect"
        frappe.local.response["location"] = callback_url
        
        return
        
    except Exception as e:
        frappe.log_error("Microsoft Auth", f"Microsoft callback error: {str(e)}")
        
        # Get frontend URL for error redirect
        try:
            # Ưu tiên origin đã lưu theo state nếu còn
            frontend_origin_cached = None
            try:
                frontend_origin_cached = frappe.cache().get_value(f"ms_auth_frontend_{state}") if state else None
            except Exception:
                frontend_origin_cached = None
            if frontend_origin_cached:
                allowlist = _get_allowed_frontend_origins()
                frontend_origin = frontend_origin_cached if _is_allowed_origin(frontend_origin_cached, allowlist) else (_get_default_frontend_origin() or "http://localhost:3000")
            else:
                default_frontend = frappe.conf.get("frontend_url") or frappe.get_site_config().get("frontend_url") or "http://localhost:3000"
                frontend_origin = _extract_origin(default_frontend) or default_frontend.rstrip('/')
        except Exception:
            frontend_origin = "http://localhost:3000"
        
        # Redirect to frontend with error
        error_message = urllib.parse.quote(str(e))
        callback_url = f"{frontend_origin}/auth/microsoft/callback?success=false&error={error_message}"
        
        # Set redirect response
        frappe.local.response["type"] = "redirect"
        frappe.local.response["location"] = callback_url
        
        return


"""
NOTE: Hệ thống đã dùng Microsoft Graph Subscriptions (webhook) nên các job đồng bộ theo giờ/ngày không còn cần thiết.
Các hàm đồng bộ định kỳ đã được loại bỏ để tránh nhầm lẫn; chỉ giữ cơ chế cập nhật theo thông báo thay đổi từ Microsoft (microsoft_webhook).
"""


@frappe.whitelist()
def sync_microsoft_users():
    """[Deprecated] Không còn dùng đồng bộ định kỳ vì đã có webhook."""
    return success_response(
        message="No-op; use webhook subscription instead",
        data={"status": "success"}
    )


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
            return success_response(
                data={
                    "mapped_user": ms_user.mapped_user_id,
                    "status": "success"
                },
                message="Microsoft user mapped successfully"
            )
        else:
            return error_response(
                message="Failed to map Microsoft user",
                code="MICROSOFT_USER_MAPPING_FAILED"
            )
        
    except Exception as e:
        frappe.log_error("Microsoft Mapping", f"Microsoft user mapping error: {str(e)}")
        frappe.throw(_("Error mapping Microsoft user: {0}").format(str(e)))



def get_microsoft_config():
    """Get Microsoft authentication configuration from site_config.json or frappe.conf"""
    config = {
        "tenant_id": frappe.conf.get("microsoft_tenant_id") or frappe.get_site_config().get("microsoft_tenant_id"),
        "client_id": frappe.conf.get("microsoft_client_id") or frappe.get_site_config().get("microsoft_client_id"),
        "client_secret": frappe.conf.get("microsoft_client_secret") or frappe.get_site_config().get("microsoft_client_secret"),
        "redirect_uri": frappe.conf.get("microsoft_redirect_uri") or frappe.get_site_config().get("microsoft_redirect_uri") or f"{frappe.utils.get_url()}/api/method/erp.api.erp_common_user.microsoft_auth.microsoft_callback",
    }
    
    # Validate required fields
    required_fields = ["tenant_id", "client_id", "client_secret"]
    missing_fields = [field for field in required_fields if not config.get(field)]
    
    if missing_fields:
        raise Exception(f"Missing Microsoft configuration: {', '.join(missing_fields)}. Please check your site_config.json")
    
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
    
    # Include all fields we need for sync (same as get_all_microsoft_users)
    fields = "id,displayName,givenName,surname,userPrincipalName,mail,jobTitle,department,officeLocation,businessPhones,mobilePhone,employeeId,employeeType,accountEnabled,preferredLanguage,usageLocation,companyName"
    
    response = requests.get(f"https://graph.microsoft.com/v1.0/me?$select={fields}", headers=headers)
    
    if response.status_code != 200:
        raise Exception(f"User info request failed: {response.text}")
    
    return response.json()


def get_all_microsoft_users(*args, **kwargs):
    """[Deprecated] Không còn dùng group-based fetch vì đã có webhook subscriptions."""
    return []


def _get_allowed_group_ids() -> list[str]:
    """Đọc danh sách group id được phép đồng bộ từ cấu hình `microsoft_group_ids`.

    Hỗ trợ chuỗi phân tách bởi dấu phẩy trong site_config/frappe.conf.
    Trả về list rỗng nếu không cấu hình (nghĩa là không lọc group).
    """
    try:
        raw = (
            frappe.conf.get("microsoft_group_ids")
            or frappe.get_site_config().get("microsoft_group_ids")
        )
        if not raw:
            return []
        if isinstance(raw, list):
            return [str(x).strip() for x in raw if str(x).strip()]
        return [s.strip() for s in str(raw).split(",") if s.strip()]
    except Exception:
        return []


def _is_user_in_allowed_groups(user_id: str, app_headers: dict) -> bool:
    """Kiểm tra membership user thuộc các group được phép bằng API `checkMemberGroups`.

    Nếu không cấu hình group → mặc định True.
    """
    allowed = _get_allowed_group_ids()
    if not allowed:
        return True
    try:
        url = f"https://graph.microsoft.com/v1.0/users/{user_id}/checkMemberGroups"
        payload = {"groupIds": allowed}
        resp = requests.post(url, headers=app_headers, json=payload)
        if resp.status_code != 200:
            return False
        data = resp.json() or {}
        returned = data if isinstance(data, list) else data.get("value", [])
        return bool(returned)
    except Exception:
        return False

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
        
        # Bypass permission vì webhook chạy allow_guest
        ms_user.flags.ignore_permissions = True
        ms_user.flags.ignore_permissions = True
        ms_user.save()
        
        return ms_user
        
    except Exception as e:
        # Mark as failed sync
        if 'ms_user' in locals():
            ms_user.sync_status = "failed"
            ms_user.sync_error = str(e)
            try:
                ms_user.flags.ignore_permissions = True
                ms_user.save()
            except Exception:
                pass
        
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
        
        # 4. Create new Frappe user if doesn't exist
        if not local_user and email:
            # Create Frappe user directly - no need to check ERP User Profile
            local_user = create_frappe_user(ms_user, user_data)
            return local_user
            
        return None
        
    except Exception as e:
        frappe.log_error("Microsoft User Mapping", f"Error in find_or_create_frappe_user: {str(e)}")
        return None


def create_frappe_user(ms_user, user_data):
    """Create new Frappe user from Microsoft data"""
    try:
        email = user_data.get("mail") or user_data.get("userPrincipalName")
        if not email:
            return None
            
        # Create new user
        first_name = user_data.get("givenName") or ""
        last_name = user_data.get("surname") or ""
        display_name = (user_data.get("displayName") or f"{first_name} {last_name}" or email).strip()
        
        # Frappe requires first_name to be non-empty, fallback to display_name or email username
        if not first_name:
            first_name = display_name or email.split('@')[0]
        if not last_name:
            last_name = ""  # last_name can be empty

        user_doc = frappe.get_doc({
            "doctype": "User",
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            # Full Name phải khớp Display Name từ Microsoft
            "full_name": display_name,
            "enabled": user_data.get("accountEnabled", True),
            "user_type": "System User",
            "send_welcome_email": 0,
            # Custom fields for Microsoft data (chỉ giữ Employee Code, bỏ Employee ID)
            "department": user_data.get("department"),
            # Prefer core/custom field `job_title`; also set legacy `designation` for compatibility
            "job_title": user_data.get("jobTitle"),
            "designation": user_data.get("jobTitle"),
            "location": user_data.get("officeLocation"),
            "mobile_no": user_data.get("mobilePhone"),
            "phone": ", ".join(user_data.get("businessPhones", [])) if user_data.get("businessPhones") else None
        })
        
        user_doc.flags.ignore_permissions = True
        user_doc.insert()
        # Clear middle_name nếu có, và đảm bảo full_name = display_name
        try:
            if hasattr(user_doc, 'middle_name'):
                setattr(user_doc, 'middle_name', "")
            user_doc.full_name = display_name
            user_doc.flags.ignore_permissions = True
            user_doc.save()
        except Exception:
            pass

        # Publish redis event for realtime microservices
        try:
            from erp.common.redis_events import publish_user_event, is_user_events_enabled
            if is_user_events_enabled():
                publish_user_event('user_created', user_doc.email)
        except Exception:
            pass

        return user_doc
        
    except Exception as e:
        frappe.log_error("Microsoft User Creation", f"Error creating Frappe user: {str(e)}")
        return None


def update_frappe_user(user_doc, ms_user, user_data):
    """Update existing Frappe user with Microsoft data"""
    try:
        # Update basic info
        new_first = user_data.get("givenName") or user_doc.first_name
        new_last = user_data.get("surname") or user_doc.last_name
        # Full Name phải khớp Display Name từ Microsoft nếu có
        display_name = (user_data.get("displayName") or user_doc.full_name)
        
        # Frappe requires first_name to be non-empty
        if not new_first:
            new_first = display_name or user_doc.email.split('@')[0]
        
        user_doc.first_name = new_first
        user_doc.last_name = new_last
        user_doc.full_name = display_name
        user_doc.enabled = user_data.get("accountEnabled", True)
        
        # Update Microsoft-specific fields (if they exist)
        if hasattr(user_doc, 'department'):
            user_doc.department = user_data.get("department") or user_doc.department
        # Prefer updating `job_title` field if present; otherwise fall back to `designation`
        if hasattr(user_doc, 'job_title'):
            user_doc.job_title = user_data.get("jobTitle") or getattr(user_doc, 'job_title')
        elif hasattr(user_doc, 'designation'):
            user_doc.designation = user_data.get("jobTitle") or user_doc.designation
        if hasattr(user_doc, 'location'):
            user_doc.location = user_data.get("officeLocation") or user_doc.location
        if hasattr(user_doc, 'mobile_no'):
            user_doc.mobile_no = user_data.get("mobilePhone") or user_doc.mobile_no
        if hasattr(user_doc, 'phone'):
            business_phones = ", ".join(user_data.get("businessPhones", [])) if user_data.get("businessPhones") else None
            user_doc.phone = business_phones or user_doc.phone
        
        # Clear middle_name nếu có
        try:
            if hasattr(user_doc, 'middle_name'):
                setattr(user_doc, 'middle_name', "")
        except Exception:
            pass

        user_doc.flags.ignore_permissions = True
        user_doc.save()

        # Publish redis event for realtime microservices
        try:
            from erp.common.redis_events import publish_user_event, is_user_events_enabled
            if is_user_events_enabled():
                publish_user_event('user_updated', user_doc.email)
        except Exception:
            pass

        return user_doc
        
    except Exception as e:
        frappe.log_error("Microsoft User Update", f"Error updating Frappe user {user_doc.email}: {str(e)}")
        return user_doc


def create_or_update_user_profile(*args, **kwargs):
    """[Deprecated] Không còn dùng Profile; giữ để tương thích ngược."""
    return None


@frappe.whitelist()
def sync_existing_users_to_profiles():
    """[Deprecated] Giữ endpoint để không gãy client cũ, nhưng không còn làm gì."""
    return success_response(
        message="No-op; profiles are deprecated",
        data={"status": "success"}
    )


@frappe.whitelist()
def full_microsoft_sync():
    """Đã chuyển sang webhook; hàm này chỉ trả về thống kê tổng quan."""
    ms_count = frappe.db.sql("SELECT COUNT(*) FROM `tabERP Microsoft User`")[0][0]
    user_count = frappe.db.sql("SELECT COUNT(*) FROM `tabUser` WHERE user_type = 'System User' AND name != 'Administrator'")[0][0]
    return {
        "status": "success",
        "message": _("Stats only; syncing is webhook-driven"),
        "results": {
            "final_counts": {"microsoft_users": ms_count, "frappe_users": user_count}
        }
    }


def handle_microsoft_user_login(ms_user):
    """Handle Microsoft user login - simplified to use only Frappe User"""
    try:
        # Get email from Microsoft user
        email = ms_user.mail or ms_user.user_principal_name
        
        # Check if Frappe user exists with same email
        if frappe.db.exists("User", email):
            frappe_user = frappe.get_doc("User", email)
            return frappe_user
        else:
            # Create new Frappe user directly
            frappe_user = frappe.new_doc("User")
            frappe_user.email = email
            frappe_user.first_name = ms_user.given_name or email.split('@')[0]
            frappe_user.last_name = ms_user.surname or ""
            frappe_user.full_name = f"{frappe_user.first_name} {frappe_user.last_name}".strip()
            frappe_user.enabled = 1
            frappe_user.send_welcome_email = 0  # Don't send welcome email
            frappe_user.user_type = "System User"
            
            # Add Microsoft-specific fields if they exist
            if hasattr(frappe_user, 'microsoft_id'):
                frappe_user.microsoft_id = ms_user.id
            if hasattr(frappe_user, 'provider'):
                frappe_user.provider = "microsoft"
            
            frappe_user.flags.ignore_permissions = True
            frappe_user.insert()
            frappe.db.commit()
            
            return frappe_user
        
    except Exception as e:
        frappe.log_error("Microsoft Login", f"Microsoft user login error: {str(e)}")
        raise e


def update_user_profile_from_microsoft(*args, **kwargs):
    """[Deprecated] Không còn dùng Profile; giữ để tương thích ngược."""
    return None


def create_user_profile_from_microsoft(*args, **kwargs):
    """[Deprecated] Không còn dùng Profile; giữ để tương thích ngược."""
    return None


@frappe.whitelist() 
def force_create_missing_users():
    """[Deprecated] No longer needed after removing ERP User Profile"""
    return {
        "status": "success",
        "message": "ERP User Profile removed - function deprecated",
        "created_count": 0
    }


@frappe.whitelist()
def fix_user_providers():
    """[Deprecated] No longer needed after removing ERP User Profile"""
    return {
        "status": "success", 
        "message": "ERP User Profile removed - function deprecated",
        "updated_count": 0
    }


@frappe.whitelist()
def fix_missing_employee_codes():
    """[Deprecated] No longer needed after removing ERP User Profile"""
    return {
        "status": "success", 
        "message": "ERP User Profile removed - function deprecated", 
        "updated_count": 0
    }


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
        frappe.log_error("Microsoft Stats", f"Microsoft sync stats error: {str(e)}")
        frappe.throw(_("Error getting Microsoft sync stats: {0}").format(str(e)))


# Removed test_microsoft_config() - not needed in production


# Removed test_microsoft_connection() - not needed in production


# Removed get_microsoft_test_users() - not needed in production


# === Microsoft Graph change notifications (webhook) ===
from urllib.parse import unquote_plus
from werkzeug.wrappers import Response
from typing import Any

def _get_webhook_logger():
    """Always get a fresh site-aware logger. Avoid module-level init before site context exists."""
    try:
        return frappe.logger("microsoft_webhook", allow_site=True, file_count=5)
    except Exception:
        return None

@frappe.whitelist(allow_guest=True)
def microsoft_webhook():
    # Debug switch
    try:
        debug_enabled = (
            frappe.conf.get("microsoft_webhook_debug")
            or frappe.get_site_config().get("microsoft_webhook_debug")
        )
    except Exception:
        debug_enabled = False
    # Always write a minimal trace to the dedicated webhook log (even if debug is off)
    _logger = _get_webhook_logger()
    if _logger:
        try:
            _logger.info("Webhook hit: start handling request")
        except Exception:
            pass
    token = None
    try:
        token = frappe.form_dict.get('validationToken') or frappe.form_dict.get('validationtoken')
    except Exception:
        token = None
    if not token:
        try:
            args = getattr(frappe.request, 'args', None)
            if args:
                token = args.get('validationToken') or args.get('validationtoken')
        except Exception:
            token = None

    if token:
        try:
            decoded = unquote_plus(token)
        except Exception:
            decoded = token
        try:
            if debug_enabled:
                frappe.log_error("Microsoft Webhook", f"Validation echo received, token_len={len(decoded)}")
            _logger = _get_webhook_logger()
            if _logger:
                _logger.info(f"Validation echo received, token_len={len(decoded)}")
        except Exception:
            pass
        return Response(decoded, mimetype="text/plain", status=200)

    try:
        if getattr(frappe.request, 'method', 'GET') == 'POST' and not getattr(frappe.request, 'data', None):
            try:
                if debug_enabled:
                    frappe.log_error("Microsoft Webhook", "Received empty POST (reachability)")
                _logger = _get_webhook_logger()
                if _logger:
                    _logger.info("Received empty POST (reachability)")
            except Exception:
                pass
            return Response('', mimetype='text/plain', status=200)
        
    except Exception:
        pass

    data = {}
    try:
        raw = None
        if frappe.request:
            raw = getattr(frappe.request, 'data', None)
            if not raw and hasattr(frappe.request, 'get_data'):
                raw = frappe.request.get_data()
        if raw:
            data = frappe.parse_json(raw)

        # Fallback 1: dùng get_json() nếu parse_json thất bại hoặc không có key 'value'
        if not isinstance(data, dict) or 'value' not in data:
            try:
                json_data = frappe.request.get_json(silent=True)
            except Exception:
                json_data = None
            if isinstance(json_data, dict) and json_data:
                data = json_data

        # Fallback 2: một số trường hợp Frappe gom payload vào form_dict
        if (not isinstance(data, dict)) or ('value' not in data):
            try:
                form_dict = getattr(frappe, 'form_dict', None)
                if form_dict:
                    maybe_value = form_dict.get('value') if hasattr(form_dict, 'get') else None
                    if maybe_value is not None:
                        if isinstance(maybe_value, str):
                            try:
                                parsed_val = frappe.parse_json(maybe_value)
                                data = {'value': parsed_val}
                            except Exception:
                                data = {'value': []}
                        elif isinstance(maybe_value, list):
                            data = {'value': maybe_value}
            except Exception:
                pass

        try:
            method = getattr(frappe.request, 'method', '')
            hdrs = getattr(frappe.request, 'headers', {}) or {}
            sub_id = hdrs.get('ms-notification-subscription-id') if hasattr(hdrs, 'get') else ''
            tenant = hdrs.get('ms-notification-tenant-id') if hasattr(hdrs, 'get') else ''
            body_len = len(raw or b'')
            msg = f"Request method={method} body_len={body_len} sub_id={sub_id} tenant={tenant}"
            if debug_enabled:
                frappe.log_error("Microsoft Webhook", msg)
            _logger = _get_webhook_logger()
            if _logger:
                _logger.info(msg)
        except Exception:
            pass
    except Exception:
        try:
            data = frappe.request.get_json(silent=True) or {}
        except Exception:
            data = {}

    notifications = data.get('value', []) if isinstance(data, dict) else []
    # Lưu dấu vết lần nhận gần nhất để kiểm tra nhanh (không phụ thuộc Error Log)
    try:
        cache = frappe.cache()
        from datetime import timezone
        cache.set_value("ms_webhook_last_received_at", datetime.now(timezone.utc).isoformat())
        cache.set_value("ms_webhook_last_notifications_count", len(notifications))
        # Lưu preview an toàn để debug (tối đa 2KB)
        try:
            body_preview = json.dumps(notifications)[:2048]
        except Exception:
            body_preview = str(notifications)[:2048]
        cache.set_value("ms_webhook_last_preview", body_preview)
        total = cache.get_value("ms_webhook_total") or 0
        try:
            total = int(total)
        except Exception:
            total = 0
        cache.set_value("ms_webhook_total", total + 1)
    except Exception:
        pass
    try:
        debug_enabled = (
            frappe.conf.get("microsoft_webhook_debug")
            or frappe.get_site_config().get("microsoft_webhook_debug")
        )
    except Exception:
        debug_enabled = False
    try:
        preview = ""
        try:
            preview = json.dumps(notifications)[:1000]
        except Exception:
            preview = str(notifications)[:1000]
        msg = f"Received notifications: count={len(notifications)} preview={preview}"
        if debug_enabled:
            frappe.log_error("Microsoft Webhook", msg)
        _logger = _get_webhook_logger()
        if _logger:
            _logger.info(msg)
    except Exception:
        pass
    if not notifications:
        return Response(json.dumps({"status": "ok", "received": 0}), mimetype="application/json", status=202)

    app_token = get_microsoft_app_token()
    headers = {"Authorization": f"Bearer {app_token}", "Content-Type": "application/json"}
    fields = "id,displayName,givenName,surname,userPrincipalName,mail,jobTitle,department,officeLocation,businessPhones,mobilePhone,employeeId,employeeType,accountEnabled,preferredLanguage,usageLocation,companyName"

    processed = 0
    debug_info = []
    for n in notifications:
        stage = "start"
        try:
            # Extract user id
            user_id = None
            if n.get('resourceData') and n['resourceData'].get('id'):
                user_id = n['resourceData']['id']
            else:
                resource = n.get('resource')  # e.g., users/{id}
                if resource and '/' in resource:
                    user_id = resource.split('/')[-1]
            if not user_id:
                # Log skip if cannot determine user id
                try:
                    msg = f"Skip notification: cannot determine user_id from payload={json.dumps(n)[:500]}"
                    if debug_enabled:
                        frappe.log_error("Microsoft Webhook", msg)
                    _logger = _get_webhook_logger()
                    if _logger:
                        _logger.info(msg)
                    if debug_enabled:
                        debug_info.append({
                            "note": "missing_user_id",
                            "payload_preview": json.dumps(n)[:500]
                        })
                except Exception:
                    pass
                continue

            # Fetch latest user data from Graph
            stage = "graph_fetch"
            resp = requests.get(f"https://graph.microsoft.com/v1.0/users/{user_id}?$select={fields}", headers=headers)
            if resp.status_code != 200:
                try:
                    body_preview = resp.text[:500] if hasattr(resp, 'text') else ''
                    msg = f"Graph fetch failed for user_id={user_id} status={resp.status_code} body={body_preview}"
                    if debug_enabled:
                        frappe.log_error("Microsoft Webhook", msg)
                    _logger = _get_webhook_logger()
                    if _logger:
                        _logger.info(msg)
                    if debug_enabled:
                        debug_info.append({
                            "user_id": user_id,
                            "graph_status": resp.status_code,
                            "graph_body": body_preview,
                            "note": "graph_fetch_failed"
                        })
                except Exception:
                    pass
                continue
            user_data = resp.json()
            # Kiểm tra group membership để quyết định enabled status
            is_in_allowed_groups = True
            try:
                is_in_allowed_groups = _is_user_in_allowed_groups(user_id, headers)
            except Exception:
                is_in_allowed_groups = False
            
            # Ghi đè accountEnabled dựa trên group membership
            # User sẽ được tạo nhưng disabled nếu không thuộc group được phép
            user_data['accountEnabled'] = user_data.get('accountEnabled', True) and is_in_allowed_groups
            
            if debug_enabled and not is_in_allowed_groups:
                debug_info.append({
                    "note": "user_not_in_allowed_groups_will_be_disabled",
                    "user_id": user_id,
                    "email": user_data.get('mail') or user_data.get('userPrincipalName')
                })
            
            # Tiếp tục xử lý (không skip)
            if debug_enabled:
                debug_info.append({
                    "user_id": user_id,
                    "graph_status": resp.status_code,
                    "note": "graph_fetch_ok"
                })

            # Upsert Microsoft and Frappe user
            stage = "create_or_update_microsoft_user"
            ms_user = create_or_update_microsoft_user(user_data)
            email = user_data.get('mail') or user_data.get('userPrincipalName')
            existed = bool(email and frappe.db.exists('User', email))

            stage = "find_or_create_frappe_user"
            local_user = find_or_create_frappe_user(ms_user, user_data)
            if local_user:
                stage = "update_frappe_user"
                update_frappe_user(local_user, ms_user, user_data)
                try:
                    msg = f"Processed user change id={user_id} email={email} existed={existed}"
                    if debug_enabled:
                        frappe.log_error("Microsoft Webhook", msg)
                    _logger = _get_webhook_logger()
                    if _logger:
                        _logger.info(msg)
                except Exception:
                    pass
                try:
                    from erp.common.redis_events import publish_user_event, is_user_events_enabled
                    if is_user_events_enabled() and email:
                        publish_user_event('user_updated' if existed else 'user_created', email)
                except Exception:
                    pass
            processed += 1
        except Exception as e:
            # Ghi lại lỗi xử lý 1 notification để chẩn đoán vì sao processed không tăng
            try:
                import traceback as _tb
                err_msg = str(e) or e.__class__.__name__
                tb = _tb.format_exc()[-2000:]
                if debug_enabled:
                    frappe.log_error("Microsoft Webhook", f"Processing exception stage={stage}: {err_msg}\n{tb}")
                _logger = _get_webhook_logger()
                if _logger:
                    _logger.info(f"Processing exception stage={stage}: {err_msg}")
                if debug_enabled:
                    debug_info.append({
                        "note": "processing_exception",
                        "stage": stage,
                        "error": err_msg
                    })
            except Exception:
                pass
            continue

    # Kèm thêm debug_info khi bật debug để hỗ trợ chẩn đoán nhanh
    resp_payload = {"status": "ok", "received": len(notifications), "processed": processed}
    try:
        if debug_enabled:
            resp_payload["debug"] = debug_info
    except Exception:
        pass
    return Response(json.dumps(resp_payload), mimetype="application/json", status=202)


@frappe.whitelist()
def get_webhook_status():
    """Xem nhanh tình trạng webhook: lần nhận gần nhất, số lượng notification, preview…"""
    cache = frappe.cache()
    return {
        "last_received_at": cache.get_value("ms_webhook_last_received_at"),
        "last_notifications_count": cache.get_value("ms_webhook_last_notifications_count"),
        "last_preview": cache.get_value("ms_webhook_last_preview"),
        "total_hits": cache.get_value("ms_webhook_total") or 0,
    }


@frappe.whitelist()
def sync_one_microsoft_user(identifier: str):
    """Đồng bộ thủ công 1 user từ Microsoft Graph theo `identifier` (email/UPN hoặc objectId).

    Ví dụ:
    bench --site <site> execute erp.api.erp_common_user.microsoft_auth.sync_one_microsoft_user --kwargs '{"identifier": "user@domain.com"}'
    """
    try:
        if not identifier:
            frappe.throw(_("Missing identifier"))

        token = get_microsoft_app_token()
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        fields = (
            "id,displayName,givenName,surname,userPrincipalName,mail,"
            "jobTitle,department,officeLocation,businessPhones,mobilePhone,"
            "employeeId,employeeType,accountEnabled,preferredLanguage,usageLocation,companyName"
        )

        # Có thể truy vấn /users/{idOrUPN}
        resp = requests.get(f"https://graph.microsoft.com/v1.0/users/{identifier}?$select={fields}", headers=headers)
        if resp.status_code != 200:
            frappe.throw(_(f"Graph fetch failed: {resp.text}"))

        user_data = resp.json()
        ms_user = create_or_update_microsoft_user(user_data)
        email = user_data.get("mail") or user_data.get("userPrincipalName")

        local_user = find_or_create_frappe_user(ms_user, user_data)
        if not local_user:
            return success_response(
                message="User data saved in MS record, no local User found",
                data={"status": "success", "email": email}
            )

        update_frappe_user(local_user, ms_user, user_data)
        return success_response(
            data={
                "email": email,
                "status": "success",
                "updated_fields": {
                    "department": user_data.get("department"),
                    "job_title": user_data.get("jobTitle")
                }
            },
            message="User synced successfully"
        )

    except Exception as e:
        frappe.log_error("Microsoft Manual Sync", f"sync_one_microsoft_user error: {str(e)}")
        frappe.throw(_(f"Error: {str(e)}"))

@frappe.whitelist()
def create_users_subscription():
    """Tạo subscription cho resource `users` để nhận realtime notifications.

    Cấu hình cần có `microsoft_webhook_url` trong site_config hoặc frappe.conf.
    """
    try:
        notification_url = (
            frappe.conf.get("microsoft_webhook_url")
            or frappe.get_site_config().get("microsoft_webhook_url")
        )
        if not notification_url:
            frappe.throw(_("Missing microsoft_webhook_url in site_config"))

        token = get_microsoft_app_token()
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        from datetime import timezone
        expiration = (datetime.now(timezone.utc) + timedelta(minutes=55)).strftime("%Y-%m-%dT%H:%M:%SZ")
        body = {
            "changeType": "created,updated,deleted",
            "notificationUrl": notification_url,
            "resource": "users",
            "expirationDateTime": expiration,
            "clientState": secrets.token_hex(16),
        }

        resp = requests.post("https://graph.microsoft.com/v1.0/subscriptions", headers=headers, json=body)
        if resp.status_code not in (200, 201):
            frappe.throw(_(f"Create subscription failed: {resp.text}"))

        return {"status": "success", "subscription": resp.json()}
    except Exception as e:
        frappe.log_error("Microsoft Subscription", f"Create users subscription error: {str(e)}")
        frappe.throw(_(f"Error creating users subscription: {str(e)}"))


def _list_users_subscriptions(token: str):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    resp = requests.get("https://graph.microsoft.com/v1.0/subscriptions", headers=headers)
    if resp.status_code != 200:
        return []
    data = resp.json() or {}
    return [s for s in data.get('value', []) if s.get('resource') == 'users']


def _renew_subscription(token: str, sub_id: str, new_expiration_utc_iso: str):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = {"expirationDateTime": new_expiration_utc_iso}
    resp = requests.patch(f"https://graph.microsoft.com/v1.0/subscriptions/{sub_id}", headers=headers, json=body)
    return resp.status_code in (200, 202)


@frappe.whitelist()
def ensure_users_subscription():
    """Gia hạn/tạo mới subscription cho resource `users` nếu sắp hết hạn.

    - Nếu không có subscription nào → tạo mới
    - Nếu có, nhưng còn < 20 phút → renew
    """
    try:
        token = get_microsoft_app_token()
        subs = _list_users_subscriptions(token)

        # Nếu không có, tạo mới
        if not subs:
            return create_users_subscription()

        # Kiểm tra từng subscription, renew nếu sắp hết hạn
        from datetime import datetime as dt
        from dateutil import parser as dtparser

        renewed = 0
        for s in subs:
            exp = s.get('expirationDateTime')
            try:
                exp_dt = dtparser.isoparse(exp) if exp else None
            except Exception:
                exp_dt = None
            if not exp_dt:
                continue
            # Đảm bảo cả 2 datetime đều timezone-aware
            from datetime import timezone
            now_utc = dt.now(timezone.utc)
            # nếu còn dưới 20 phút thì renew lên ~55 phút
            minutes_left = (exp_dt - now_utc).total_seconds() / 60.0
            if minutes_left < 20:
                new_exp = (now_utc + timedelta(minutes=55)).strftime("%Y-%m-%dT%H:%M:%SZ")
                if _renew_subscription(token, s.get('id'), new_exp):
                    renewed += 1

        return {"status": "success", "checked": len(subs), "renewed": renewed}

    except Exception as e:
        frappe.log_error("Microsoft Subscription", f"ensure_users_subscription error: {str(e)}")
        return {"status": "error", "message": str(e)}


@frappe.whitelist()
def list_users_subscriptions():
    """Liệt kê chi tiết subscriptions hiện có cho resource `users`."""
    try:
        token = get_microsoft_app_token()
        subs = _list_users_subscriptions(token)
        return {"status": "success", "subscriptions": subs}
    except Exception as e:
        frappe.log_error("Microsoft Subscription", f"list_users_subscriptions error: {str(e)}")
        return {"status": "error", "message": str(e)}


@frappe.whitelist()
def delete_users_subscription(sub_id: str):
    """Xóa 1 subscription theo id để tạo lại sạch sẽ."""
    try:
        token = get_microsoft_app_token()
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        resp = requests.delete(f"https://graph.microsoft.com/v1.0/subscriptions/{sub_id}", headers=headers)
        if resp.status_code not in (200, 204):
            frappe.throw(_(f"Delete subscription failed: {resp.text}"))
        return {"status": "success", "deleted": sub_id}
    except Exception as e:
        frappe.log_error("Microsoft Subscription", f"delete_users_subscription error: {str(e)}")
        return {"status": "error", "message": str(e)}


@frappe.whitelist()
def sync_all_microsoft_users_once(limit: int | None = None, page_size: int = 50) -> dict:
    """Đồng bộ toàn bộ Users từ Microsoft Graph (một lần), có phân trang.

    - Tải danh sách /v1.0/users theo trang ($top) và gọi luồng tạo/cập nhật hiện có.
    - Tham số:
        - limit: số lượng tối đa users để đồng bộ (None = không giới hạn)
        - page_size: số lượng users mỗi trang (mặc định 50, tối đa 999 theo Graph)
    - Trả về thống kê processed/created/updated/errors.
    """
    try:
        # Bảo vệ tham số
        try:
            page_size = int(page_size)
        except Exception:
            page_size = 50
        if page_size < 1:
            page_size = 50
        if page_size > 999:
            page_size = 999

        token = get_microsoft_app_token()
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        fields = (
            "id,displayName,givenName,surname,userPrincipalName,mail,"
            "jobTitle,department,officeLocation,businessPhones,mobilePhone,"
            "employeeId,employeeType,accountEnabled,preferredLanguage,usageLocation,companyName"
        )

        url = f"https://graph.microsoft.com/v1.0/users?$select={fields}&$top={page_size}"
        processed = 0
        created = 0
        updated = 0
        errors = 0
        emails_seen: set[str] = set()

        while url:
            resp = requests.get(url, headers=headers)
            if resp.status_code != 200:
                return {"status": "error", "message": f"Graph list users failed: {resp.status_code} {resp.text[:300]}"}

            data = resp.json() or {}
            values = data.get("value", [])
            for user_data in values:
                try:
                    try:
                        user_id = user_data.get("id")
                        if user_id and not _is_user_in_allowed_groups(user_id, headers):
                            continue
                    except Exception:
                        continue

                    ms_user = create_or_update_microsoft_user(user_data)
                    email = user_data.get("mail") or user_data.get("userPrincipalName")
                    if email:
                        existed = bool(frappe.db.exists('User', email))
                        local_user = find_or_create_frappe_user(ms_user, user_data)
                        if local_user:
                            update_frappe_user(local_user, ms_user, user_data)
                        if existed:
                            updated += 1
                        else:
                            created += 1
                        emails_seen.add(email)
                    processed += 1
                except Exception:
                    errors += 1

                # Giới hạn tổng nếu được yêu cầu
                if limit is not None and processed >= int(limit):
                    break

            # Kiểm tra limit sau mỗi trang
            if limit is not None and processed >= int(limit):
                break

            # Phân trang tiếp theo
            url = data.get('@odata.nextLink')

        return {
            "status": "success",
            "processed": processed,
            "created": created,
            "updated": updated,
            "errors": errors,
            "unique_emails": len(emails_seen),
        }

    except Exception as e:
        frappe.log_error("Microsoft Bulk Sync", f"sync_all_microsoft_users_once error: {str(e)}")
        return {"status": "error", "message": str(e)}


@frappe.whitelist()
def sync_microsoft_group_members_once(group_ids: str | None = None, limit: int | None = None, page_size: int = 100) -> dict:
    """Đồng bộ tất cả thành viên của các group chỉ định (hoặc từ `microsoft_group_ids`)."""
    try:
        # Danh sách group
        if group_ids and isinstance(group_ids, str):
            groups = [g.strip() for g in group_ids.split(',') if g.strip()]
        else:
            groups = _get_allowed_group_ids()
        if not groups:
            return {"status": "error", "message": "No group_ids provided or configured"}

        # Chuẩn hóa tham số
        try:
            page_size = int(page_size)
        except Exception:
            page_size = 100
        if page_size < 1:
            page_size = 100
        if page_size > 999:
            page_size = 999

        token = get_microsoft_app_token()
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        fields = (
            "id,displayName,givenName,surname,userPrincipalName,mail,"
            "jobTitle,department,officeLocation,businessPhones,mobilePhone,"
            "employeeId,employeeType,accountEnabled,preferredLanguage,usageLocation,companyName"
        )

        processed = 0
        created = 0
        updated = 0
        errors = 0
        seen_users: set[str] = set()

        for gid in groups:
            url = f"https://graph.microsoft.com/v1.0/groups/{gid}/members?$select={fields}&$top={page_size}"
            while url:
                resp = requests.get(url, headers=headers)
                if resp.status_code != 200:
                    return {"status": "error", "message": f"Graph list members failed for {gid}: {resp.status_code} {resp.text[:300]}"}
                data = resp.json() or {}
                values = data.get('value', [])
                for m in values:
                    try:
                        # Loại bỏ object không phải user
                        if not (m.get('userPrincipalName') or m.get('mail')):
                            continue
                        user_id = m.get('id')
                        if not user_id or user_id in seen_users:
                            continue
                        seen_users.add(user_id)

                        ms_user = create_or_update_microsoft_user(m)
                        email = m.get('mail') or m.get('userPrincipalName')
                        if email:
                            existed = bool(frappe.db.exists('User', email))
                            local_user = find_or_create_frappe_user(ms_user, m)
                            if local_user:
                                update_frappe_user(local_user, ms_user, m)
                            if existed:
                                updated += 1
                            else:
                                created += 1
                        processed += 1
                    except Exception:
                        errors += 1

                    if limit is not None and processed >= int(limit):
                        break

                if limit is not None and processed >= int(limit):
                    break

                url = data.get('@odata.nextLink')

            if limit is not None and processed >= int(limit):
                break

        return {
            "status": "success",
            "processed": processed,
            "created": created,
            "updated": updated,
            "errors": errors,
            "unique_users": len(seen_users),
            "groups": groups,
        }

    except Exception as e:
        frappe.log_error("Microsoft Group Bulk Sync", f"sync_microsoft_group_members_once error: {str(e)}")
        return {"status": "error", "message": str(e)}


 