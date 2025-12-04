"""
Mobile Push Notification API for React Native Apps
Handles Expo push notifications for iOS/Android devices
"""

import frappe
import json
from frappe import _
from erp.utils.api_response import success_response, error_response


# ===== MOBILE NOTIFICATION SERVICE =====

def ensure_mobile_device_token_doctype():
    """Create Mobile Device Token DocType if it doesn't exist"""
    if not frappe.db.exists("DocType", "Mobile Device Token"):
        doc = frappe.get_doc({
            "doctype": "DocType",
            "name": "Mobile Device Token",
            "module": "erp",
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
            return success_response({"deleted_count": deleted_count}, "All device tokens unregistered")
        else:
            # Unregister specific token
            deleted = frappe.db.delete("Mobile Device Token", {
                "user": user,
                "device_token": device_token
            })
            frappe.db.commit()
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
        # Get active device tokens for user
        tokens = frappe.get_all("Mobile Device Token",
            filters={
                "user": user_email,
                "is_active": 1
            },
            fields=["device_token", "platform", "app_type", "device_id"]
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

        # Prepare Expo notification payload
        messages = []
        for token_doc in tokens:
            # Determine channelId and sound based on notification type
            notification_type = data.get("type") if data else None
            action = data.get("action") if data else None
            
            if notification_type == "attendance":
                channel_id = "attendance"
                sound_name = "default"
            elif notification_type == "ticket":
                channel_id = "ticket"
                # Use custom sound for new ticket notifications
                if action in ["new_ticket_admin", "ticket_assigned"]:
                    sound_name = "ticket_create.wav"  # Custom sound file
                else:
                    sound_name = "default"
            elif notification_type == "feedback":
                channel_id = "feedback"
                sound_name = "ticket_create.wav"  # Same sound for new feedback
            else:
                channel_id = "default"
                sound_name = "default"
            
            message = {
                "to": token_doc.device_token,
                "title": title,
                "body": body,
                "data": data or {},
                "priority": "high",
                "sound": sound_name,
                "channelId": channel_id
            }

            # Add platform-specific settings
            if token_doc.platform == "ios":
                message["badge"] = 1
                # iOS uses sound name without path for custom sounds bundled in app
                if sound_name != "default":
                    message["sound"] = sound_name
            elif token_doc.platform == "android":
                message["android"] = {
                    "channelId": channel_id,
                    "priority": "high",
                    "sound": sound_name if sound_name != "default" else None
                }

            messages.append(message)

        # Send to Expo Push API
        success_count = 0
        failed_count = 0
        results = []

        for message in messages:
            try:
                import requests
                response = requests.post(
                    "https://exp.host/--/api/v2/push/send",
                    json=message,
                    headers={
                        "Accept": "application/json",
                        "Content-Type": "application/json"
                    },
                    timeout=10
                )

                if response.status_code == 200:
                    result = response.json()
                    if result.get("data", {}).get("status") == "ok":
                        success_count += 1
                        results.append({"token": message["to"], "status": "success"})
                    else:
                        failed_count += 1
                        results.append({"token": message["to"], "status": "failed", "error": result})
                else:
                    failed_count += 1
                    results.append({"token": message["to"], "status": "failed", "http_code": response.status_code})

            except Exception as e:
                failed_count += 1
                results.append({"token": message["to"], "status": "error", "error": str(e)})

        message = f"Sent to {success_count}/{len(messages)} devices successfully"
        if failed_count > 0:
            message += f" ({failed_count} failed)"

        return {
            "success": success_count > 0,
            "message": message,
            "results": results,
            "total_sent": len(messages),
            "success_count": success_count,
            "failed_count": failed_count
        }

    except Exception as e:
        frappe.log_error(f"Error sending mobile notification: {str(e)}", "Mobile Notification Error")
        return {
            "success": False,
            "message": f"Error sending notification: {str(e)}"
        }


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
