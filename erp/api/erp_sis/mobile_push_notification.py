"""
Mobile Push Notification API for React Native Apps
Handles Expo push notifications for iOS/Android devices
"""

import json

import frappe
from frappe import _
from erp.utils.api_response import success_response, error_response
from erp.common.notification_emit import emit_notify, emit_notify_bulk

# Bundle đăng ký push — tiêu đề Wislife/journal theo app (yêu cầu UX)
BUNDLE_PARENT_PORTAL = "com.hailinh.n23.parentportalmobile"
BUNDLE_WORKSPACE_IDS = frozenset(
    {
        "com.wellspring.workspace",
        "com.hailinh.n23.workspace",  # Android workspace (nếu gửi package thay vì iOS id)
    }
)


def _wislife_push_title_for_bundle(bundle_id, fallback_title):
    """Tiêu đề noti Nhật ký: Parent Portal vs workspace-mobile."""
    bid = (bundle_id or "").strip().lower()
    if bid == BUNDLE_PARENT_PORTAL.lower():
        return "WISer's Diaries"
    if bid in BUNDLE_WORKSPACE_IDS:
        return "Hoạt động"
    return fallback_title


def _mobile_notify_via_redis_stream_only():
    """site_config: MOBILE_NOTIFY_VIA_REDIS_STREAM_ONLY=1 — gửi qua notification-service (Streams)."""
    return bool(frappe.utils.cint(frappe.conf.get("MOBILE_NOTIFY_VIA_REDIS_STREAM_ONLY") or 0))


# ===== Sync sang notification-service (Phase 3) =====
# App PH device thật chưa register trực tiếp tới notification-service do Nginx chưa proxy
# /api/notifications/* sang microservice. Để đảm bảo notification-service luôn có Mobile
# Device Token mới nhất, Frappe gọi sync sau mỗi lần register/unregister.

def _notification_service_url():
    """Cho phép cấu hình NOTIFICATION_SERVICE_URL ở site_config hoặc env."""
    return (frappe.conf.get("NOTIFICATION_SERVICE_URL") or "").rstrip("/")


def _internal_service_secret():
    return (frappe.conf.get("INTERNAL_SERVICE_SECRET") or "").strip()


def _sync_register_to_notification_service(user_email, payload):
    """Gửi POST /devices/register-internal — fail không chặn flow chính, chỉ log."""
    base = _notification_service_url()
    secret = _internal_service_secret()
    if not base or not secret:
        return  # Chưa cấu hình thì im lặng (giống behavior cũ)
    try:
        import requests as _requests
        body = {
            "userEmail": user_email,
            "deviceToken": payload.get("device_token"),
            "platform": payload.get("platform"),
            "appType": payload.get("app_type"),
            "deviceId": payload.get("device_id"),
            "bundleId": payload.get("bundle_id"),
            "deviceName": payload.get("device_name"),
            "os": payload.get("os"),
            "osVersion": payload.get("os_version"),
            "appVersion": payload.get("app_version"),
            "language": payload.get("language"),
            "timezone": payload.get("timezone"),
        }
        resp = _requests.post(
            f"{base}/api/notifications/devices/register-internal",
            json=body,
            headers={
                "Content-Type": "application/json",
                "X-Service-Token": secret,
                "X-Service-Name": "frappe-erp",
            },
            timeout=5,
        )
        if 200 <= resp.status_code < 300:
            frappe.logger().info(
                f"[NotiSync] register OK user={user_email} app_type={payload.get('app_type')}"
            )
        else:
            frappe.logger().warning(
                f"[NotiSync] register HTTP {resp.status_code}: {resp.text[:200]}"
            )
    except Exception as e:
        frappe.logger().warning(f"[NotiSync] register lỗi: {str(e)}")


def _sync_unregister_to_notification_service(user_email, device_token=None):
    base = _notification_service_url()
    secret = _internal_service_secret()
    if not base or not secret:
        return
    try:
        import requests as _requests
        body = {"userEmail": user_email}
        if device_token:
            body["deviceToken"] = device_token
        resp = _requests.post(
            f"{base}/api/notifications/devices/unregister-internal",
            json=body,
            headers={
                "Content-Type": "application/json",
                "X-Service-Token": secret,
                "X-Service-Name": "frappe-erp",
            },
            timeout=5,
        )
        if 200 <= resp.status_code < 300:
            frappe.logger().info(
                f"[NotiSync] unregister OK user={user_email} token={(device_token or '*')[:24]}"
            )
        else:
            frappe.logger().warning(
                f"[NotiSync] unregister HTTP {resp.status_code}: {resp.text[:200]}"
            )
    except Exception as e:
        frappe.logger().warning(f"[NotiSync] unregister lỗi: {str(e)}")


# ===== MOBILE NOTIFICATION SERVICE =====

def ensure_mobile_device_token_doctype():
    """Create Mobile Device Token DocType if it doesn't exist"""
    if not frappe.db.exists("DocType", "Mobile Device Token"):
        doc = frappe.get_doc({
            "doctype": "DocType",
            "name": "Mobile Device Token",
            "module": "Erp",
            "custom": 0,
            "is_submittable": 0,
            "is_child_table": 0,
            "track_changes": 0,
            "quick_entry": 0,
            "fields": [
                {
                    "fieldname": "user",
                    "label": "User",
                    "fieldtype": "Link",
                    "options": "User",
                    "reqd": 1
                },
                {
                    "fieldname": "device_token",
                    "label": "Device Token",
                    "fieldtype": "Data",
                    "reqd": 1,
                    "unique": 1
                },
                {
                    "fieldname": "platform",
                    "label": "Platform",
                    "fieldtype": "Select",
                    "options": "ios\nandroid\nexpo",
                    "default": "expo"
                },
                {
                    "fieldname": "device_name",
                    "label": "Device Name",
                    "fieldtype": "Data"
                },
                {
                    "fieldname": "os",
                    "label": "OS",
                    "fieldtype": "Data"
                },
                {
                    "fieldname": "os_version",
                    "label": "OS Version",
                    "fieldtype": "Data"
                },
                {
                    "fieldname": "app_version",
                    "label": "App Version",
                    "fieldtype": "Data"
                },
                {
                    "fieldname": "language",
                    "label": "Language",
                    "fieldtype": "Data",
                    "default": "vi"
                },
                {
                    "fieldname": "timezone",
                    "label": "Timezone",
                    "fieldtype": "Data",
                    "default": "UTC"
                },
                {
                    "fieldname": "is_active",
                    "label": "Is Active",
                    "fieldtype": "Check",
                    "default": 1
                },
                {
                    "fieldname": "last_seen",
                    "label": "Last Seen",
                    "fieldtype": "Datetime",
                    "default": "Now"
                },
                {
                    "fieldname": "app_type",
                    "label": "App Type",
                    "fieldtype": "Select",
                    "options": "standalone\nexpo-go",
                    "default": "standalone",
                    "description": "standalone = TestFlight/App Store, expo-go = Expo Go development app"
                },
                {
                    "fieldname": "device_id",
                    "label": "Device ID",
                    "fieldtype": "Data",
                    "description": "Unique device identifier to track same physical device across app types"
                },
                {
                    "fieldname": "bundle_id",
                    "label": "Bundle ID",
                    "fieldtype": "Data",
                    "description": "iOS Bundle Identifier"
                }
            ],
            "permissions": [
                {
                    "role": "System Manager",
                    "read": 1,
                    "write": 1,
                    "create": 1,
                    "delete": 1
                },
                {
                    "role": "Desk User",
                    "read": 1,
                    "write": 1,
                    "create": 1
                }
            ]
        })
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
        frappe.logger().info("Created Mobile Device Token DocType")
    else:
        # Add new fields if they don't exist
        try:
            meta = frappe.get_meta("Mobile Device Token")
            existing_fields = [f.fieldname for f in meta.fields]
            
            new_fields = []
            if "app_type" not in existing_fields:
                new_fields.append({
                    "fieldname": "app_type",
                    "label": "App Type",
                    "fieldtype": "Select",
                    "options": "standalone\nexpo-go",
                    "default": "standalone"
                })
            if "device_id" not in existing_fields:
                new_fields.append({
                    "fieldname": "device_id",
                    "label": "Device ID",
                    "fieldtype": "Data"
                })
            if "bundle_id" not in existing_fields:
                new_fields.append({
                    "fieldname": "bundle_id",
                    "label": "Bundle ID",
                    "fieldtype": "Data"
                })
            
            if new_fields:
                for field in new_fields:
                    frappe.db.sql(f"""
                        ALTER TABLE `tabMobile Device Token`
                        ADD COLUMN IF NOT EXISTS `{field['fieldname']}` VARCHAR(140)
                    """)
                frappe.db.commit()
                frappe.logger().info(f"Added new fields to Mobile Device Token: {[f['fieldname'] for f in new_fields]}")
        except Exception as e:
            frappe.logger().warning(f"Could not add new fields to Mobile Device Token: {str(e)}")

# Initialize on module load
ensure_mobile_device_token_doctype()


@frappe.whitelist(allow_guest=True)
def register_device_token():
    """
    Đăng ký Expo push token cho mobile devices (iOS/Android)
    Thay thế cho Web Push VAPID system
    Allow guest để có thể validate JWT manually
    """
    """
    Đăng ký Expo push token cho mobile devices (iOS/Android)
    Thay thế cho Web Push VAPID system

    Request body:
    {
        "deviceToken": "ExponentPushToken[...]",
        "platform": "ios|android|expo",
        "deviceName": "iPhone 15 Pro",
        "os": "ios",
        "osVersion": "17.0",
        "appVersion": "1.0.0",
        "language": "vi",
        "timezone": "Asia/Ho_Chi_Minh"
    }
    """
    try:
        user = frappe.session.user
        frappe.logger().info(f"Mobile push registration - Session user: {user}")
        frappe.logger().info(f"Mobile push registration - Request headers: {dict(frappe.request.headers) if hasattr(frappe.request, 'headers') else 'No headers'}")

        if not user or user == "Guest":
            # Try to extract user from Authorization header for JWT tokens
            auth_header = frappe.request.headers.get('Authorization', '')
            frappe.logger().info(f"Mobile push registration - Auth header: {auth_header[:50] if auth_header else 'None'}")

            # Also check if JWT token is passed in the payload for mobile apps
            if not auth_header or not auth_header.startswith('Bearer '):
                # Try to get token from request payload
                token_in_payload = frappe.form_dict.get('jwt_token') or frappe.local.form_dict.get('jwt_token')
                if token_in_payload:
                    frappe.logger().info(f"Mobile push registration - JWT token found in payload")
                    auth_header = f"Bearer {token_in_payload}"

            if auth_header.startswith('Bearer '):
                token = auth_header[7:]  # Remove 'Bearer ' prefix
                try:
                    import jwt
                    # Try to decode JWT token to get user (skip signature verification for now)
                    decoded = jwt.decode(token, options={"verify_signature": False})
                    potential_user = decoded.get('email') or decoded.get('sub') or decoded.get('username')
                    frappe.logger().info(f"Mobile push registration - Extracted user from JWT: {potential_user}")

                    # Validate that this user exists in Frappe
                    if potential_user and frappe.db.exists("User", potential_user):
                        user = potential_user
                        frappe.logger().info(f"Mobile push registration - User validated: {user}")
                        # Set session user for this request
                        frappe.session.user = user
                    else:
                        frappe.logger().warning(f"Mobile push registration - User from JWT does not exist: {potential_user}")

                except Exception as jwt_error:
                    frappe.logger().warning(f"Mobile push registration - JWT decode failed: {str(jwt_error)}")

            if not user or user == "Guest":
                return error_response("Authentication required", code="NOT_AUTHENTICATED")

        # Parse request data - PHẢI parse từ raw body trước vì axios gửi JSON
        if frappe.request.method == "POST":
            import json
            data = {}
            
            # Method 1: Try to get from raw request body (axios sends JSON)
            try:
                raw_data = frappe.request.get_data(as_text=True)
                frappe.logger().info(f"📥 Raw request data: {raw_data[:200] if raw_data else 'None'}...")
                if raw_data:
                    data = json.loads(raw_data)
                    frappe.logger().info(f"📥 Parsed JSON data keys: {list(data.keys())}")
            except Exception as json_err:
                frappe.logger().warning(f"📥 JSON parse failed: {str(json_err)}")
            
            # Method 2: Fallback to form_dict if JSON parse failed
            if not data.get('deviceToken'):
                frappe.logger().info(f"📥 Trying form_dict: {dict(frappe.local.form_dict) if hasattr(frappe.local, 'form_dict') else 'None'}")
                if hasattr(frappe.local, 'form_dict') and frappe.local.form_dict:
                    data = dict(frappe.local.form_dict)
            
            # Method 3: Try frappe.form_dict
            if not data.get('deviceToken'):
                frappe.logger().info(f"📥 Trying frappe.form_dict: {dict(frappe.form_dict) if frappe.form_dict else 'None'}")
                if frappe.form_dict:
                    data = dict(frappe.form_dict)
                    
            frappe.logger().info(f"📥 Final data keys: {list(data.keys()) if data else 'None'}")
            frappe.logger().info(f"📥 deviceToken present: {bool(data.get('deviceToken'))}")
        else:
            return error_response("POST method required", code="METHOD_NOT_ALLOWED")

        # Validate required fields
        device_token = data.get('deviceToken')
        platform = data.get('platform', 'expo')
        app_type = data.get('appType', 'standalone')  # 'standalone' cho TestFlight/App Store, 'expo-go' cho Expo Go
        device_id = data.get('deviceId', '')  # Unique device identifier
        bundle_id = data.get('bundleId', 'com.wellspring.workspace')

        if not device_token:
            return error_response("deviceToken is required", code="MISSING_DEVICE_TOKEN")

        frappe.logger().info(f"📱 Registering device token for {user}")
        frappe.logger().info(f"📱 App type: {app_type}, Device ID: {device_id}, Bundle ID: {bundle_id}")
        frappe.logger().info(f"📱 Token: {device_token[:50]}...")

        # QUAN TRỌNG: Khi user đăng ký từ standalone app (TestFlight/App Store),
        # cần deactivate token cũ từ expo-go để notification chỉ gửi đến standalone app
        # và ngược lại
        if device_id:
            # Tìm và deactivate token cũ cùng device_id nhưng khác app_type
            old_tokens = frappe.get_all("Mobile Device Token",
                filters={
                    "user": user,
                    "device_id": device_id,
                    "app_type": ["!=", app_type],
                    "is_active": 1
                },
                fields=["name", "app_type", "device_token"]
            )
            
            for old_token in old_tokens:
                frappe.db.set_value("Mobile Device Token", old_token.name, "is_active", 0)
                frappe.logger().info(f"📱 Deactivated old {old_token.app_type} token for {user}: {old_token.device_token[:30]}...")
            
            if old_tokens:
                frappe.db.commit()
                frappe.logger().info(f"📱 Deactivated {len(old_tokens)} old tokens for same device, different app type")

        # Check if user already has this exact token
        existing = frappe.db.exists("Mobile Device Token", {
            "user": user,
            "device_token": device_token
        })

        device_data = {
            "device_token": device_token,
            "platform": platform,
            "device_name": data.get('deviceName', f'{platform.title()} Device'),
            "os": data.get('os', platform),
            "os_version": data.get('osVersion', 'Unknown'),
            "app_version": data.get('appVersion', '1.0.0'),
            "language": data.get('language', 'vi'),
            "timezone": data.get('timezone', 'UTC'),
            "is_active": 1,
            "last_seen": frappe.utils.now(),
            "app_type": app_type,
            "device_id": device_id,
            "bundle_id": bundle_id,
        }

        # Use direct database operations to avoid module loading issues
        try:
            if existing:
                # Update existing token using SQL
                frappe.db.set_value("Mobile Device Token", existing, device_data)
                frappe.db.commit()
                message = f"Device token updated successfully ({app_type})"
            else:
                # Create new token using SQL
                device_data["user"] = user
                device_data["doctype"] = "Mobile Device Token"
                doc = frappe.get_doc(device_data)
                doc.insert(ignore_permissions=True)
                frappe.db.commit()
                message = f"Device token registered successfully ({app_type})"
        except Exception as db_error:
            frappe.logger().error(f"Database operation failed: {str(db_error)}")
            # Try fallback method
            try:
                if existing:
                    frappe.db.sql("""
                        UPDATE `tabMobile Device Token`
                        SET device_token=%s, platform=%s, device_name=%s, os=%s, os_version=%s,
                            app_version=%s, language=%s, timezone=%s, last_seen=%s,
                            app_type=%s, device_id=%s, bundle_id=%s, is_active=1
                        WHERE name=%s
                    """, (
                        device_data.get('device_token'),
                        device_data.get('platform'),
                        device_data.get('device_name'),
                        device_data.get('os'),
                        device_data.get('os_version'),
                        device_data.get('app_version'),
                        device_data.get('language'),
                        device_data.get('timezone'),
                        frappe.utils.now(),
                        device_data.get('app_type'),
                        device_data.get('device_id'),
                        device_data.get('bundle_id'),
                        existing
                    ))
                else:
                    frappe.db.sql("""
                        INSERT INTO `tabMobile Device Token`
                        (name, user, device_token, platform, device_name, os, os_version, app_version,
                         language, timezone, is_active, last_seen, app_type, device_id, bundle_id,
                         creation, modified, owner, modified_by)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        frappe.generate_hash(length=10),
                        user,
                        device_data.get('device_token'),
                        device_data.get('platform'),
                        device_data.get('device_name'),
                        device_data.get('os'),
                        device_data.get('os_version'),
                        device_data.get('app_version'),
                        device_data.get('language'),
                        device_data.get('timezone'),
                        1,
                        frappe.utils.now(),
                        device_data.get('app_type'),
                        device_data.get('device_id'),
                        device_data.get('bundle_id'),
                        frappe.utils.now(),
                        frappe.utils.now(),
                        user,
                        user
                    ))
                frappe.db.commit()
                message = f"Device token registered successfully ({app_type}, SQL fallback)"
            except Exception as sql_error:
                frappe.logger().error(f"SQL fallback also failed: {str(sql_error)}")
                raise sql_error

        frappe.db.commit()
        frappe.logger().info(f"✅ {message} for user {user}")

        # Sync sang notification-service (Phase 3) — đảm bảo microservice luôn có token mới nhất
        # kể cả khi app PH device thật chưa register trực tiếp tới notification-service.
        try:
            _sync_register_to_notification_service(user, device_data)
        except Exception as sync_err:
            frappe.logger().warning(f"[NotiSync] register sync exception: {str(sync_err)}")

        return success_response({
            "device_token": device_token,
            "platform": platform,
            "app_type": app_type,
            "device_id": device_id,
            "bundle_id": bundle_id,
            "registered_at": frappe.utils.now()
        }, message)

    except Exception as e:
        frappe.log_error(f"Error registering device token: {str(e)}", "Mobile Device Registration Error")
        return error_response(f"Error registering device: {str(e)}", code="REGISTRATION_ERROR")


@frappe.whitelist(allow_guest=False)
def unregister_device_token():
    """
    Hủy đăng ký device token
    """
    try:
        user = frappe.session.user
        if not user or user == "Guest":
            return error_response("Authentication required", code="NOT_AUTHENTICATED")

        # Get device token from request
        device_token = frappe.form_dict.get('deviceToken') or frappe.request.args.get('deviceToken')

        if not device_token:
            # Unregister all tokens for this user
            deleted_count = frappe.db.count("Mobile Device Token", {"user": user})
            frappe.db.delete("Mobile Device Token", {"user": user})
            frappe.db.commit()
            try:
                _sync_unregister_to_notification_service(user, None)
            except Exception as sync_err:
                frappe.logger().warning(f"[NotiSync] unregister sync exception: {str(sync_err)}")
            return success_response({"deleted_count": deleted_count}, "All device tokens unregistered")
        else:
            # Unregister specific token
            deleted = frappe.db.delete("Mobile Device Token", {
                "user": user,
                "device_token": device_token
            })
            frappe.db.commit()
            try:
                _sync_unregister_to_notification_service(user, device_token)
            except Exception as sync_err:
                frappe.logger().warning(f"[NotiSync] unregister sync exception: {str(sync_err)}")
            return success_response({"deleted": bool(deleted)}, "Device token unregistered")

    except Exception as e:
        frappe.log_error(f"Error unregistering device token: {str(e)}")
        return error_response(f"Error unregistering device: {str(e)}", code="UNREGISTRATION_ERROR")


@frappe.whitelist(allow_guest=True)
def test_device_registration():
    """
    Test API để verify mobile app có thể gọi được
    """
    try:
        import json
        user = frappe.session.user
        headers = dict(frappe.request.headers) if hasattr(frappe.request, 'headers') else {}
        auth_header = headers.get('Authorization', 'None')

        frappe.logger().info(f"Test device registration called by user: {user}")
        frappe.logger().info(f"Auth header: {auth_header[:50] if auth_header != 'None' else 'None'}")

        return success_response({
            "user": user,
            "message": "Device registration API is working",
            "timestamp": frappe.utils.now(),
            "auth_header_present": auth_header != 'None',
            "auth_type": auth_header.split(' ')[0] if auth_header != 'None' and ' ' in auth_header else 'None'
        }, "Test successful")
    except Exception as e:
        frappe.logger().error(f"Test device registration error: {str(e)}")
        return error_response(f"Test failed: {str(e)}")

@frappe.whitelist(allow_guest=True)
def test_mobile_api():
    """
    Test API để kiểm tra authentication
    """
    try:
        user = frappe.session.user
        frappe.logger().info(f"Test mobile API called by user: {user}")
        frappe.logger().info(f"Request headers: {dict(frappe.request.headers)}")

        return success_response({
            "user": user,
            "message": "API is working",
            "timestamp": frappe.utils.now()
        }, "Test successful")
    except Exception as e:
        frappe.logger().error(f"Test mobile API error: {str(e)}")
        return error_response(f"Test failed: {str(e)}")


@frappe.whitelist(allow_guest=True)
def debug_push_tokens(user_email=None, include_inactive=True):
    """
    Debug API để kiểm tra push tokens đã đăng ký
    """
    try:
        filters = {}
        if user_email:
            filters["user"] = user_email
        if not include_inactive:
            filters["is_active"] = 1
            
        tokens = frappe.get_all("Mobile Device Token",
            filters=filters,
            fields=["name", "user", "device_token", "platform", "app_type", "device_id", "device_name", "app_version", "last_seen", "is_active", "creation"],
            order_by="creation desc",
            limit=50
        )
        
        # Mask tokens for security
        for t in tokens:
            if t.get("device_token"):
                t["device_token"] = t["device_token"][:40] + "..." if len(t["device_token"]) > 40 else t["device_token"]
        
        active_count = len([t for t in tokens if t.get("is_active")])
        inactive_count = len([t for t in tokens if not t.get("is_active")])
        
        return success_response({
            "total_tokens": len(tokens),
            "active_count": active_count,
            "inactive_count": inactive_count,
            "tokens": tokens
        }, f"Found {len(tokens)} tokens ({active_count} active, {inactive_count} inactive)")
    except Exception as e:
        return error_response(f"Error: {str(e)}")


@frappe.whitelist()
def test_send_push(user_email, title="Test Notification", body="This is a test push notification"):
    """
    Test gửi push notification đến user
    """
    try:
        result = send_mobile_notification(
            user_email=user_email,
            title=title,
            body=body,
            data={"type": "test", "timestamp": frappe.utils.now()}
        )
        return success_response(result, "Push notification sent")
    except Exception as e:
        return error_response(f"Error: {str(e)}")

def send_mobile_notification_persisted(
    user_email,
    title,
    body,
    data=None,
    *,
    erp_notification_type="system",
    priority="medium",
    reference_doctype=None,
    reference_name=None,
):
    """
    Tạo bản ghi ERP Notification (trung tâm thông báo in-app / notification_center) rồi gửi Expo push.
    Hook after_insert của ERP Notification chỉ bắn realtime + unread, không gửi push trùng.
    """
    from frappe import get_doc

    data = data if data is not None else {}
    try:
        doc_dict = {
            "doctype": "ERP Notification",
            "title": title,
            "message": body,
            "recipient_user": user_email,
            "recipients": json.dumps([user_email]),
            "notification_type": erp_notification_type,
            "priority": priority,
            "data": json.dumps(data),
            "channel": "push",
            "status": "sent",
            "delivery_status": "pending",
            "sent_at": frappe.utils.now(),
            "event_timestamp": frappe.utils.now(),
        }
        if reference_doctype:
            doc_dict["reference_doctype"] = reference_doctype
        if reference_name:
            doc_dict["reference_name"] = reference_name
        notif_doc = get_doc(doc_dict)
        notif_doc.insert(ignore_permissions=True)
        frappe.db.commit()
    except Exception as e:
        frappe.logger().error(
            f"[send_mobile_notification_persisted] ERP Notification failed for {user_email}: {e}"
        )

    return send_mobile_notification(user_email, title, body, data)


@frappe.whitelist()
def send_mobile_notification(user_email, title, body, data=None):
    """
    Gửi push notification đến mobile device của user qua Expo

    Args:
        user_email: Email của user
        title: Tiêu đề notification
        body: Nội dung
        data: Additional data (optional)

    Returns:
        dict: {"success": true/false, "message": "..."}
    """
    try:
        if _mobile_notify_via_redis_stream_only():
            ch = frappe.conf.get("NOTIFICATION_STREAM_CHANNEL") or "frappe_notifications"
            ndata = data if isinstance(data, dict) else {}
            ntype = str(ndata.get("type") or "general")
            ok = emit_notify(ch, [user_email], title, body, data=ndata, notification_type=ntype)
            return {
                "success": bool(ok),
                "message": "redis_stream" if ok else "redis_stream_failed",
            }

        # Get active device tokens for user
        tokens = frappe.get_all("Mobile Device Token",
            filters={
                "user": user_email,
                "is_active": 1
            },
            fields=["device_token", "platform", "app_type", "device_id", "bundle_id"]
        )

        if not tokens:
            frappe.logger().warning(f"📱 No active device tokens found for user: {user_email}")
            return {
                "success": False,
                "message": f"No active device tokens found for user: {user_email}"
            }
        
        # Log all active tokens for debugging
        frappe.logger().info(f"📱 Found {len(tokens)} active device token(s) for {user_email}:")
        for t in tokens:
            frappe.logger().info(f"   - Token: {t.device_token[:40]}... | Platform: {t.platform} | App Type: {t.get('app_type', 'unknown')}")

        # Build messages cho từng token (dùng helper _build_expo_message)
        messages = [_build_expo_message(token_doc, title, body, data) for token_doc in tokens]

        # Phase C.2: Gửi BATCH thay vì loop từng message
        # Trước: N POST × 10s timeout = worst case 30-60s cho 1 user nhiều device
        # Sau:   1 POST × 5s = nhanh hơn 10x
        return _post_expo_batch(messages)

    except Exception as e:
        frappe.log_error(f"Error sending mobile notification: {str(e)}", "Mobile Notification Error")
        return {
            "success": False,
            "message": f"Error sending notification: {str(e)}"
        }


def _build_expo_message(token_doc, title, body, data):
    """
    Build 1 Expo message payload cho 1 device token.
    Tách ra để tái dùng trong send_mobile_notification và send_mobile_notifications_bulk.
    """
    bundle_id = (
        token_doc.get("bundle_id")
        if isinstance(token_doc, dict)
        else getattr(token_doc, "bundle_id", None)
    )
    notification_type = data.get("type") if data else None
    # Wislife / journal: tiêu đề theo app (Parent Portal vs workspace-mobile)
    nt_str = str(notification_type or "")
    if nt_str == "journal" or nt_str.startswith("wislife_"):
        title = _wislife_push_title_for_bundle(bundle_id, title)

    action = data.get("action") if data else None
    
    if notification_type == "attendance":
        channel_id = "attendance"
        sound_name = "default"
    elif notification_type == "ticket":
        channel_id = "ticket"
        if action in ["new_ticket_admin", "ticket_assigned"]:
            sound_name = "ticket_create.wav"
        else:
            sound_name = "default"
    elif notification_type == "feedback":
        channel_id = "feedback"
        sound_name = "default"
    elif notification_type == "leave_request" or notification_type == "leave":
        channel_id = "leave_request"
        sound_name = "default"
    elif notification_type in (
        "daily_health", "health_visit_created", "health_visit_received",
        "health_visit_completed", "health_visit_escalation",
        "health_visit_cancelled", "health_visit_rejected"
    ):
        channel_id = "daily_health"
        sound_name = "default"
    elif notification_type and str(notification_type).startswith("crm_issue"):
        channel_id = "crm_issue"
        sound_name = "default"
    # Wave 3: kênh Trao đổi chat + Nhật ký (Wislife) trên Android
    elif notification_type in ("chat", "chat_message", "chat_message_reaction", "chat_message_recalled"):
        channel_id = "chat"
        sound_name = "default"
    elif notification_type and (
        str(notification_type) == "journal"
        or str(notification_type).startswith("wislife_")
    ):
        channel_id = "journal"
        sound_name = "default"
    else:
        channel_id = "default"
        sound_name = "default"

    push_to = (
        token_doc.get("device_token")
        if isinstance(token_doc, dict)
        else getattr(token_doc, "device_token", None)
    )
    message = {
        "to": push_to,
        "title": title,
        "body": body,
        "data": data or {},
        "priority": "high",
        "channelId": channel_id,
    }

    platform = (
        token_doc.get("platform")
        if isinstance(token_doc, dict)
        else getattr(token_doc, "platform", None)
    )
    if platform == "ios":
        message["badge"] = 1
        message["sound"] = sound_name
    elif platform == "android":
        if sound_name != "default":
            android_sound_name = sound_name.replace(".wav", "").replace(".mp3", "")
            message["sound"] = android_sound_name
        else:
            message["sound"] = "default"
        message["android"] = {
            "channelId": channel_id,
            "priority": "high",
            "notification": {
                "channelId": channel_id,
                "sound": sound_name.replace(".wav", "").replace(".mp3", "") if sound_name != "default" else "default"
            }
        }
    else:
        message["sound"] = sound_name

    return message


# Expo Push API giới hạn 100 messages/POST
EXPO_BATCH_SIZE = 100
EXPO_POST_TIMEOUT = 5  # giây — giảm từ 10s


def _post_expo_batch(messages):
    """
    POST danh sách messages tới Expo theo BATCH (max 100/POST).
    Expo trả per-message status → parse và đếm success/failed riêng.
    """
    if not messages:
        return {
            "success": False,
            "message": "No messages to send",
            "results": [],
            "total_messages": 0,
            "success_count": 0,
            "failed_count": 0,
        }
    
    import requests
    
    success_count = 0
    failed_count = 0
    results = []
    
    for chunk_start in range(0, len(messages), EXPO_BATCH_SIZE):
        chunk = messages[chunk_start:chunk_start + EXPO_BATCH_SIZE]
        try:
            response = requests.post(
                "https://exp.host/--/api/v2/push/send",
                json=chunk,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                timeout=EXPO_POST_TIMEOUT,
            )
            
            if response.status_code == 200:
                resp_json = response.json()
                # Expo trả {"data": [...]} với mỗi item là kết quả của 1 message
                tickets = resp_json.get("data", [])
                if not isinstance(tickets, list):
                    tickets = [tickets]
                
                for idx, ticket in enumerate(tickets):
                    if idx >= len(chunk):
                        break
                    target_token = chunk[idx].get("to")
                    if isinstance(ticket, dict) and ticket.get("status") == "ok":
                        success_count += 1
                        results.append({"token": target_token, "status": "success"})
                    else:
                        failed_count += 1
                        results.append({
                            "token": target_token,
                            "status": "failed",
                            "error": ticket if isinstance(ticket, dict) else str(ticket),
                        })
                
                # Trường hợp số ticket < số messages → đánh dấu các message còn lại là failed
                for idx in range(len(tickets), len(chunk)):
                    failed_count += 1
                    results.append({
                        "token": chunk[idx].get("to"),
                        "status": "failed",
                        "error": "No ticket returned",
                    })
            else:
                # HTTP fail → đánh dấu cả batch là failed
                for msg in chunk:
                    failed_count += 1
                    results.append({
                        "token": msg.get("to"),
                        "status": "failed",
                        "http_code": response.status_code,
                    })
        except Exception as e:
            for msg in chunk:
                failed_count += 1
                results.append({
                    "token": msg.get("to"),
                    "status": "error",
                    "error": str(e),
                })
    
    msg_summary = f"Sent to {success_count}/{len(messages)} devices successfully"
    if failed_count > 0:
        msg_summary += f" ({failed_count} failed)"
    
    return {
        "success": success_count > 0,
        "message": msg_summary,
        "results": results,
        "total_messages": len(messages),
        "success_count": success_count,
        "failed_count": failed_count,
    }


def send_mobile_notifications_bulk(targets, title, body):
    """
    Gửi Expo push BATCH cho nhiều user (multiple parents) trong 1 POST.
    
    Args:
        targets: List of dicts [{"email": str, "data": dict}]
        title: Tiêu đề (string đã resolve, không phải dict bilingual)
        body: Nội dung
    
    Returns:
        dict: {"success", "success_count", "failed_count", "total_messages", ...}
    
    Performance:
    - Trước (gọi send_mobile_notification N lần): N user × M device × 10s = O(N×M)
    - Sau (1 POST batch):                          1 POST × 5s = O(1)
    
    Lý do cần function này:
    - send_bulk_parent_notifications gửi cùng nội dung cho 5-50 phụ huynh
    - Mỗi phụ huynh có 1-3 mobile device
    - Loop tuần tự = 30-150s; batch = < 5s
    """
    if not targets:
        return {
            "success": False,
            "message": "No targets",
            "success_count": 0,
            "failed_count": 0,
            "total_messages": 0,
        }
    
    try:
        if _mobile_notify_via_redis_stream_only():
            ch = frappe.conf.get("NOTIFICATION_STREAM_CHANNEL") or "frappe_notifications"
            return emit_notify_bulk(ch, targets, title, body, notification_type="general")

        # Lấy tất cả tokens cho danh sách emails (1 query)
        emails = list({t.get("email") for t in targets if t.get("email")})
        if not emails:
            return {"success": False, "message": "No valid emails", "success_count": 0, "failed_count": 0, "total_messages": 0}
        
        all_tokens = frappe.get_all(
            "Mobile Device Token",
            filters={"user": ["in", emails], "is_active": 1},
            fields=["device_token", "platform", "user", "bundle_id"],
        )
        
        if not all_tokens:
            frappe.logger().info(f"📱 [Bulk Expo] No active device tokens for {len(emails)} users")
            return {"success": False, "message": "No active device tokens", "success_count": 0, "failed_count": 0, "total_messages": 0}
        
        # Map email → data (mỗi user có data riêng với student_id riêng)
        email_to_data = {t.get("email"): t.get("data", {}) for t in targets}
        
        # Build messages cho tất cả token
        messages = []
        for token in all_tokens:
            user_data = email_to_data.get(token.get("user"), {})
            messages.append(_build_expo_message(token, title, body, user_data))
        
        frappe.logger().info(f"📱 [Bulk Expo] Sending BATCH: {len(messages)} messages cho {len(emails)} users")
        return _post_expo_batch(messages)
        
    except Exception as e:
        frappe.log_error(f"Error in send_mobile_notifications_bulk: {str(e)}", "Bulk Mobile Notification Error")
        return {
            "success": False,
            "message": f"Error: {str(e)}",
            "success_count": 0,
            "failed_count": 0,
            "total_messages": 0,
        }


# --- Broadcast: thông báo bản cập nhật app workspace-mobile (Wis) ---

# Số thiết bị trở lên thì mặc định enqueue (tránh timeout HTTP / worker web).
_WORKSPACE_UPDATE_AUTO_ENQUEUE_MIN_DEVICES = 80


def _get_workspace_mobile_push_tokens():
    """Token Expo đang hoạt động, bundle thuộc workspace-mobile (iOS + Android)."""
    bundle_list = list(BUNDLE_WORKSPACE_IDS)
    return frappe.get_all(
        "Mobile Device Token",
        filters={
            "is_active": 1,
            "bundle_id": ["in", bundle_list],
        },
        fields=["device_token", "platform", "user", "bundle_id", "device_id"],
    )


def _run_workspace_app_update_broadcast(title, body, data_json=None):
    """
    Thực thi gửi push (gọi từ enqueue hoặc sync).
    data_json: JSON string để serialize an toàn qua background job.
    """
    data = {}
    if data_json:
        try:
            data = json.loads(data_json) if isinstance(data_json, str) else data_json
        except Exception:
            data = {}
    if not isinstance(data, dict):
        data = {}

    tokens = _get_workspace_mobile_push_tokens()
    unique_users = {t.get("user") for t in tokens if t.get("user")}
    if not tokens:
        frappe.logger().info("[workspace app update] Không có Mobile Device Token workspace nào.")
        return {
            "success": False,
            "message": "Không có thiết bị workspace đang đăng ký push",
            "token_count": 0,
            "unique_users": 0,
            "total_messages": 0,
            "success_count": 0,
            "failed_count": 0,
        }

    messages = [_build_expo_message(t, title, body, data) for t in tokens]
    result = _post_expo_batch(messages)
    result["token_count"] = len(tokens)
    result["unique_users"] = len(unique_users)
    frappe.logger().info(
        f"[workspace app update] Đã gửi batch: {result.get('success_count')}/{result.get('total_messages')} — users: {len(unique_users)}"
    )
    return result


@frappe.whitelist()
def broadcast_workspace_app_update(
    title=None,
    body=None,
    new_version=None,
    store_url_ios=None,
    store_url_android=None,
    extra_data=None,
    dry_run=0,
    sync=0,
):
    """
    Gửi push Expo đến **mọi thiết bị** đang đăng ký workspace-mobile (bundle trong BUNDLE_WORKSPACE_IDS).

    Quyền: **System Manager** (hoặc Administrator).

    Tham số:
    - title / body: tuỳ chỉnh (mặc định tiếng Việt về bản cập nhật).
    - new_version: ví dụ 1.5.27 — nhét vào data để app xử lý sau.
    - store_url_ios / store_url_android: link store (tuỳ chọn).
    - extra_data: JSON object/string, merge vào payload data.
    - dry_run=1: chỉ đếm token/users, không gửi.
    - sync=1: gửi ngay trong request (dev / ít máy). Mặc định sync=0: enqueue queue ``long``
      khi số thiết bị >= {_WORKSPACE_UPDATE_AUTO_ENQUEUE_MIN_DEVICES}, ngược lại gửi sync.

    API: POST ``/api/method/erp.api.erp_sis.mobile_push_notification.broadcast_workspace_app_update``
    """
    if frappe.session.user == "Guest":
        return error_response("Authentication required", code="NOT_AUTHENTICATED")

    if frappe.session.user != "Administrator" and "System Manager" not in frappe.get_roles():
        return error_response("Chỉ System Manager được gọi endpoint này", code="FORBIDDEN")

    # Chuẩn hoá từ form / JSON
    if isinstance(extra_data, str) and extra_data.strip():
        try:
            extra_data = json.loads(extra_data)
        except Exception:
            extra_data = {}
    if extra_data is None or not isinstance(extra_data, dict):
        extra_data = {}

    nv = (new_version or "").strip()
    default_body = (
        f"Đã có phiên bản mới ({nv}). Mở App Store / CH Play hoặc mở app để cập nhật."
        if nv
        else "Đã có phiên bản mới. Vui lòng cập nhật ứng dụng Wis để có trải nghiệm tốt nhất."
    )
    title = (title or "Ứng dụng Wis có bản cập nhật mới").strip()
    body = (body or default_body).strip()

    data = {
        "type": "app_update",
        "new_version": nv,
        "timestamp": str(frappe.utils.now()),
    }
    if store_url_ios:
        data["store_url_ios"] = store_url_ios.strip()
    if store_url_android:
        data["store_url_android"] = store_url_android.strip()
    data.update(extra_data)

    tokens = _get_workspace_mobile_push_tokens()
    token_count = len(tokens)
    unique_users = len({t.get("user") for t in tokens if t.get("user")})

    if frappe.utils.cint(dry_run):
        return success_response(
            {
                "dry_run": True,
                "token_count": token_count,
                "unique_users": unique_users,
                "title": title,
                "body": body,
                "data": data,
            },
            "Dry run — chưa gửi push",
        )

    if not tokens:
        return success_response(
            {
                "success": False,
                "message": "Không có thiết bị workspace đăng ký push",
                "token_count": 0,
                "unique_users": 0,
            },
            "Không có token",
        )

    data_json = json.dumps(data)
    force_sync = frappe.utils.cint(sync) == 1
    use_enqueue = (not force_sync) and token_count >= _WORKSPACE_UPDATE_AUTO_ENQUEUE_MIN_DEVICES

    if use_enqueue:
        frappe.enqueue(
            "erp.api.erp_sis.mobile_push_notification._run_workspace_app_update_broadcast",
            queue="long",
            job_name=f"workspace_app_update_{frappe.utils.now_datetime()}",
            title=title,
            body=body,
            data_json=data_json,
            timeout=600,
        )
        return success_response(
            {
                "enqueued": True,
                "token_count": token_count,
                "unique_users": unique_users,
                "title": title,
                "body": body,
                "data": data,
            },
            f"Đã xếp hàng gửi push tới {token_count} thiết bị ({unique_users} user)",
        )

    result = _run_workspace_app_update_broadcast(title, body, data_json=data_json)
    ok = result.get("success")
    return success_response(result, "Đã gửi push" if ok else (result.get("message") or "Gửi push thất bại"))


# ===== INTEGRATION WITH EXISTING ATTENDANCE SYSTEM =====

def send_attendance_mobile_notification(user_email, employee_code, check_in_time=None, check_out_time=None, device_name=None):
    """
    Gửi mobile notification khi có attendance event
    Được gọi từ attendance hooks hoặc manual triggers
    """
    try:
        title = "Cập nhật chấm công"
        timestamp = frappe.utils.now()

        if check_in_time and not check_out_time:
            body = f"Đã check-in lúc {frappe.utils.format_time(check_in_time, 'HH:mm')} tại {device_name or 'Unknown Device'}"
        elif check_out_time:
            body = f"Đã check-out lúc {frappe.utils.format_time(check_out_time, 'HH:mm')} tại {device_name or 'Unknown Device'}"
        else:
            body = f"Cập nhật chấm công tại {device_name or 'Unknown Device'}"

        data = {
            "type": "attendance",
            "employeeCode": employee_code,
            "timestamp": timestamp,
            "deviceName": device_name
        }

        result = send_mobile_notification(user_email, title, body, data)

        frappe.logger().info(f"Mobile attendance notification sent to {user_email}: {result}")
        return result

    except Exception as e:
        frappe.log_error(f"Error sending attendance mobile notification: {str(e)}")
        return {"success": False, "error": str(e)}
