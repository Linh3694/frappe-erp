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

        # Parse request data
        if frappe.request.method == "POST":
            if hasattr(frappe.local, 'form_dict') and frappe.local.form_dict:
                data = frappe.local.form_dict
            else:
                # Try to get from raw request body for JSON requests
                import json
                try:
                    request_data = json.loads(frappe.request.get_data(as_text=True))
                    data = request_data
                except:
                    return error_response("Invalid request format", code="INVALID_REQUEST")
        else:
            return error_response("POST method required", code="METHOD_NOT_ALLOWED")

        # Validate required fields
        device_token = data.get('deviceToken')
        platform = data.get('platform', 'expo')

        if not device_token:
            return error_response("deviceToken is required", code="MISSING_DEVICE_TOKEN")

        # Check if user already has this token
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
        }

        if existing:
            # Update existing token
            doc = frappe.get_doc("Mobile Device Token", existing)
            doc.update(device_data)
            doc.save(ignore_permissions=True)
            message = "Device token updated successfully"
        else:
            # Create new token
            device_data["user"] = user
            doc = frappe.get_doc({
                "doctype": "Mobile Device Token",
                **device_data
            })
            doc.insert(ignore_permissions=True)
            message = "Device token registered successfully"

        frappe.db.commit()

        return success_response({
            "device_token": device_token,
            "platform": platform,
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
            fields=["device_token", "platform"]
        )

        if not tokens:
            return {
                "success": False,
                "message": f"No active device tokens found for user: {user_email}"
            }

        # Prepare Expo notification payload
        messages = []
        for token_doc in tokens:
            message = {
                "to": token_doc.device_token,
                "title": title,
                "body": body,
                "data": data or {},
                "priority": "high",
                "sound": "default",
                "channelId": "attendance" if data and data.get("type") == "attendance" else "default"
            }

            # Add platform-specific settings
            if token_doc.platform == "ios":
                message["badge"] = 1
            elif token_doc.platform == "android":
                message["android"] = {
                    "channelId": "attendance" if data and data.get("type") == "attendance" else "default",
                    "priority": "high"
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
        title = "⏰ Cập nhật chấm công"
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
