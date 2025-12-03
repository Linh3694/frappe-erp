"""
Push Notification API for Parent Portal PWA
Xử lý push subscriptions và gửi notifications đến phụ huynh
"""

import frappe
import json
from frappe import _

# Try to import pywebpush, fallback to our simple implementation
try:
    from pywebpush import webpush, WebPushException
    USE_PYWEBPUSH = True
except ImportError:
    print("⚠️  pywebpush not installed, using simplified sender")
    from erp.api.parent_portal.webpush_sender import send_web_push, send_simple_notification
    USE_PYWEBPUSH = False
    
    # Create a simple WebPushException for fallback
    class WebPushException(Exception):
        def __init__(self, message, response=None):
            super().__init__(message)
            self.response = response


def get_device_name_from_user_agent():
    """
    Trích xuất tên thiết bị từ User-Agent header
    """
    try:
        user_agent = frappe.request.headers.get('User-Agent', 'Unknown Device')
        
        # Parse common patterns
        if 'iPhone' in user_agent:
            return 'iPhone'
        elif 'iPad' in user_agent:
            return 'iPad'
        elif 'Android' in user_agent:
            if 'Mobile' in user_agent:
                return 'Android Phone'
            return 'Android Tablet'
        elif 'Mac OS' in user_agent or 'Macintosh' in user_agent:
            if 'Chrome' in user_agent:
                return 'Mac - Chrome'
            elif 'Safari' in user_agent:
                return 'Mac - Safari'
            elif 'Firefox' in user_agent:
                return 'Mac - Firefox'
            return 'Mac'
        elif 'Windows' in user_agent:
            if 'Chrome' in user_agent:
                return 'Windows - Chrome'
            elif 'Edge' in user_agent:
                return 'Windows - Edge'
            elif 'Firefox' in user_agent:
                return 'Windows - Firefox'
            return 'Windows'
        elif 'Linux' in user_agent:
            return 'Linux'
        else:
            return 'Unknown Device'
    except:
        return 'Unknown Device'


@frappe.whitelist(allow_guest=True)  # Allow guest to handle JWT auth manually
def save_push_subscription(subscription_json=None, device_name=None):
    """
    Lưu push subscription của user
    Hỗ trợ multi-device: mỗi thiết bị có endpoint riêng biệt
    Also removes any expired subscription notifications

    Args:
        subscription_json: JSON string của push subscription từ frontend
        device_name: Tên thiết bị (optional, tự động detect nếu không có)

    Returns:
        dict: {"success": True, "message": "..."}
    """
    try:
        user = frappe.session.user
        
        # Handle JWT authentication for PWA (similar to register_device_token)
        if not user or user == "Guest":
            auth_header = frappe.request.headers.get('Authorization', '')
            
            if auth_header.startswith('Bearer '):
                token = auth_header[7:]  # Remove 'Bearer ' prefix
                try:
                    import jwt
                    # Decode JWT token to get user (skip signature verification)
                    decoded = jwt.decode(token, options={"verify_signature": False})
                    potential_user = decoded.get('email') or decoded.get('sub') or decoded.get('username')
                    
                    # Validate that this user exists in Frappe
                    if potential_user and frappe.db.exists("User", potential_user):
                        user = potential_user
                        frappe.session.user = user
                        frappe.logger().info(f"📱 [Push Subscription] Authenticated via JWT: {user}")
                    else:
                        frappe.logger().warning(f"📱 [Push Subscription] User from JWT not found: {potential_user}")
                except Exception as jwt_error:
                    frappe.logger().warning(f"📱 [Push Subscription] JWT decode failed: {str(jwt_error)}")
        
        if not user or user == "Guest":
            return {
                "success": False,
                "message": "Authentication required"
            }

        # Nếu subscription_json không được truyền như argument, thử lấy từ request body
        if subscription_json is None:
            if frappe.form_dict.get('subscription_json'):
                subscription_json = frappe.form_dict.get('subscription_json')
            else:
                # Try to get from raw request body for JSON requests
                import json
                try:
                    request_data = json.loads(frappe.request.get_data(as_text=True))
                    subscription_json = request_data.get('subscription_json')
                    device_name = request_data.get('device_name') or device_name
                except:
                    pass

        if subscription_json is None:
            return {
                "success": False,
                "message": "Missing subscription_json parameter"
            }

        subscription = json.loads(subscription_json) if isinstance(subscription_json, str) else subscription_json

        # Validate subscription data
        endpoint = subscription.get("endpoint")
        if not endpoint:
            return {
                "success": False,
                "message": "Invalid subscription data - missing endpoint"
            }

        # Auto-detect device name if not provided
        if not device_name:
            device_name = get_device_name_from_user_agent()

        # Kiểm tra xem endpoint này đã tồn tại chưa (multi-device support)
        # Dùng endpoint để identify vì mỗi browser/device có endpoint unique
        existing = frappe.db.exists("Push Subscription", {"endpoint": endpoint})

        if existing:
            # Update existing subscription (same endpoint = same device)
            doc = frappe.get_doc("Push Subscription", existing)
            doc.subscription_json = json.dumps(subscription)
            doc.user = user  # Update user in case re-login with different account
            doc.device_name = device_name
            doc.save(ignore_permissions=True)
            message = "Push subscription updated successfully"
            frappe.logger().info(f"📱 [Push Subscription] Updated for {user} on {device_name}")
        else:
            # Create new subscription for this device
            doc = frappe.get_doc({
                "doctype": "Push Subscription",
                "user": user,
                "endpoint": endpoint,
                "device_name": device_name,
                "subscription_json": json.dumps(subscription)
            })
            doc.insert(ignore_permissions=True)
            message = "Push subscription created successfully"
            frappe.logger().info(f"📱 [Push Subscription] Created for {user} on {device_name}")

        # Count total subscriptions for this user (for logging)
        total_devices = frappe.db.count("Push Subscription", {"user": user})

        # Remove any "expired subscription" notifications for this user
        try:
            expired_notifications = frappe.db.sql("""
                SELECT name FROM `tabERP Notification`
                WHERE recipient_user = %s
                AND notification_type = 'system'
                AND data LIKE '%%"push_subscription_expired"%%'
            """, (user,), pluck="name")

            if expired_notifications:
                for notif_name in expired_notifications:
                    try:
                        frappe.delete_doc("ERP Notification", notif_name, ignore_permissions=True)
                    except:
                        pass
                frappe.db.commit()
                frappe.logger().info(f"Removed {len(expired_notifications)} expired subscription notifications for {user}")

        except Exception as cleanup_error:
            frappe.logger().warning(f"Failed to cleanup expired notifications: {str(cleanup_error)}")

        frappe.db.commit()

        return {
            "success": True,
            "message": message,
            "log": f"Saved push subscription for user: {user} on {device_name}. Total devices: {total_devices}",
            "device_name": device_name,
            "total_devices": total_devices
        }

    except Exception as e:
        frappe.log_error(f"Error saving push subscription: {str(e)}", "Push Notification Error")
        return {
            "success": False,
            "message": f"Error saving subscription: {str(e)}",
            "log": f"Error: {str(e)}"
        }


@frappe.whitelist(allow_guest=True)  # Allow guest to handle JWT auth manually
def delete_push_subscription(endpoint=None, delete_all=False):
    """
    Xóa push subscription của user hiện tại
    Hỗ trợ multi-device: xóa theo endpoint cụ thể hoặc xóa tất cả
    
    Args:
        endpoint: Endpoint của subscription cần xóa (optional)
                 Nếu không truyền, sẽ xóa subscription của thiết bị hiện tại
        delete_all: Nếu True, xóa TẤT CẢ subscriptions của user (dùng khi logout)
    
    Returns:
        dict: {"success": True, "message": "..."}
    """
    try:
        user = frappe.session.user
        
        # Handle JWT authentication for PWA
        if not user or user == "Guest":
            auth_header = frappe.request.headers.get('Authorization', '')
            
            if auth_header.startswith('Bearer '):
                token = auth_header[7:]
                try:
                    import jwt
                    decoded = jwt.decode(token, options={"verify_signature": False})
                    potential_user = decoded.get('email') or decoded.get('sub') or decoded.get('username')
                    
                    if potential_user and frappe.db.exists("User", potential_user):
                        user = potential_user
                        frappe.session.user = user
                except Exception as jwt_error:
                    frappe.logger().warning(f"JWT decode failed: {str(jwt_error)}")
        
        if not user or user == "Guest":
            return {
                "success": False,
                "message": "Authentication required"
            }

        # Lấy endpoint từ request body nếu không truyền qua argument
        if endpoint is None and not delete_all:
            try:
                request_data = json.loads(frappe.request.get_data(as_text=True))
                endpoint = request_data.get('endpoint')
                delete_all = request_data.get('delete_all', False)
            except:
                pass
        
        deleted_count = 0
        
        if delete_all:
            # Xóa TẤT CẢ subscriptions của user (logout scenario)
            subscriptions = frappe.db.get_all(
                "Push Subscription",
                filters={"user": user},
                pluck="name"
            )
            
            for sub_name in subscriptions:
                frappe.delete_doc("Push Subscription", sub_name, ignore_permissions=True)
                deleted_count += 1
            
            message = f"Deleted all {deleted_count} push subscription(s)" if deleted_count > 0 else "No subscriptions found"
            frappe.logger().info(f"📱 [Push Subscription] Deleted all {deleted_count} subscriptions for {user}")
            
        elif endpoint:
            # Xóa subscription theo endpoint cụ thể
            existing = frappe.db.exists("Push Subscription", {"endpoint": endpoint, "user": user})
            
            if existing:
                frappe.delete_doc("Push Subscription", existing, ignore_permissions=True)
                deleted_count = 1
                message = "Push subscription deleted successfully"
                frappe.logger().info(f"📱 [Push Subscription] Deleted subscription for {user} (endpoint matched)")
            else:
                message = "No subscription found for this endpoint"
        else:
            # Fallback: Xóa subscription đầu tiên tìm được (cho backward compatibility)
            existing = frappe.db.exists("Push Subscription", {"user": user})
            
            if existing:
                frappe.delete_doc("Push Subscription", existing, ignore_permissions=True)
                deleted_count = 1
                message = "Push subscription deleted successfully"
                frappe.logger().info(f"📱 [Push Subscription] Deleted subscription for {user} (fallback)")
            else:
                message = "No subscription found"
        
        if deleted_count > 0:
            frappe.db.commit()
        
        # Count remaining subscriptions
        remaining = frappe.db.count("Push Subscription", {"user": user})
        
        return {
            "success": True,
            "message": message,
            "log": f"Deleted {deleted_count} push subscription(s) for user: {user}. Remaining: {remaining}",
            "deleted_count": deleted_count,
            "remaining_devices": remaining
        }
        
    except Exception as e:
        frappe.log_error(f"Error deleting push subscription: {str(e)}", "Push Notification Error")
        return {
            "success": False,
            "message": f"Error deleting subscription: {str(e)}",
            "log": f"Error: {str(e)}"
        }


@frappe.whitelist(allow_guest=True)
def get_vapid_public_key():
    """
    Lấy VAPID public key để frontend subscribe
    Public endpoint - không cần authentication vì VAPID public key là public data
    
    Returns:
        dict: {"success": True, "vapid_public_key": "..."}
    """
    try:
        vapid_public_key = frappe.conf.get("vapid_public_key")
        
        if not vapid_public_key:
            return {
                "success": False,
                "message": "VAPID public key not configured",
                "log": "Please configure VAPID keys in site_config.json"
            }
        
        return {
            "success": True,
            "vapid_public_key": vapid_public_key
        }
        
    except Exception as e:
        frappe.log_error(f"Error getting VAPID key: {str(e)}", "Push Notification Error")
        return {
            "success": False,
            "message": f"Error getting VAPID key: {str(e)}"
        }


def send_push_to_single_subscription(subscription_doc, payload, vapid_private_key, vapid_claims_email, user_email):
    """
    Helper: Gửi push notification đến một subscription cụ thể
    
    Returns:
        dict: {"success": bool, "subscription_name": str, "device_name": str, "error": str|None, "expired": bool}
    """
    try:
        subscription = json.loads(subscription_doc.get("subscription_json"))
        device_name = subscription_doc.get("device_name", "Unknown Device")
        subscription_name = subscription_doc.get("name")
        
        # Gửi push notification
        if USE_PYWEBPUSH:
            response = webpush(
                subscription_info=subscription,
                data=json.dumps(payload),
                vapid_private_key=vapid_private_key,
                vapid_claims={
                    "sub": f"mailto:{vapid_claims_email}"
                }
            )
        else:
            response = send_web_push(
                subscription_info=subscription,
                data=json.dumps(payload),
                vapid_private_key=vapid_private_key,
                vapid_claims={
                    "sub": f"mailto:{vapid_claims_email}"
                }
            )
        
        return {
            "success": True,
            "subscription_name": subscription_name,
            "device_name": device_name,
            "error": None,
            "expired": False
        }
        
    except WebPushException as e:
        error_code = getattr(e.response, 'status_code', None) if hasattr(e, 'response') else None
        
        if error_code == 410:
            # Subscription expired - mark for deletion
            return {
                "success": False,
                "subscription_name": subscription_doc.get("name"),
                "device_name": subscription_doc.get("device_name", "Unknown"),
                "error": "Subscription expired",
                "expired": True
            }
        
        return {
            "success": False,
            "subscription_name": subscription_doc.get("name"),
            "device_name": subscription_doc.get("device_name", "Unknown"),
            "error": str(e),
            "expired": False
        }
        
    except Exception as e:
        return {
            "success": False,
            "subscription_name": subscription_doc.get("name"),
            "device_name": subscription_doc.get("device_name", "Unknown"),
            "error": str(e),
            "expired": False
        }


@frappe.whitelist()
def send_push_notification(user_email, title, body, icon=None, data=None, tag=None, actions=None):
    """
    Gửi push notification đến TẤT CẢ thiết bị của một user (multi-device support)
    
    Args:
        user_email: Email của user cần gửi notification
        title: Tiêu đề notification
        body: Nội dung notification
        icon: URL icon (optional)
        data: Additional data (optional)
        tag: Notification tag (optional)
        actions: Array of action buttons (optional)
        
    Returns:
        dict: {"success": True/False, "message": "...", "log": "...", "devices_sent": int, "devices_failed": int}
    """
    try:
        # Lấy TẤT CẢ subscriptions của user (multi-device)
        subscription_docs = frappe.db.get_all(
            "Push Subscription",
            filters={"user": user_email},
            fields=["name", "subscription_json", "device_name", "endpoint"]
        )
        
        if not subscription_docs:
            return {
                "success": False,
                "message": f"No push subscription found for user: {user_email}",
                "log": f"User {user_email} has not subscribed to push notifications",
                "devices_sent": 0,
                "devices_failed": 0
            }
        
        # VAPID keys từ site config
        vapid_private_key = frappe.conf.get("vapid_private_key")
        vapid_public_key = frappe.conf.get("vapid_public_key")
        vapid_claims_email = frappe.conf.get("vapid_claims_email", "admin@example.com")
        
        if not vapid_private_key or not vapid_public_key:
            return {
                "success": False,
                "message": "VAPID keys not configured",
                "log": "Please configure VAPID keys in site_config.json",
                "devices_sent": 0,
                "devices_failed": 0
            }
        
        # Tạo payload
        payload = {
            "title": title,
            "body": body,
            "icon": icon or "/icon.png",
            "badge": icon or "/icon.png",
            "data": data or {},
            "tag": tag or "default-notification",
            "timestamp": frappe.utils.now_datetime().isoformat(),
        }
        
        if actions:
            payload["actions"] = actions
        
        # Gửi đến TẤT CẢ devices
        devices_sent = 0
        devices_failed = 0
        expired_subscriptions = []
        device_results = []
        
        for sub_doc in subscription_docs:
            result = send_push_to_single_subscription(
                sub_doc, payload, vapid_private_key, vapid_claims_email, user_email
            )
            
            device_results.append({
                "device": result["device_name"],
                "success": result["success"],
                "error": result["error"]
            })
            
            if result["success"]:
                devices_sent += 1
            else:
                devices_failed += 1
                if result["expired"]:
                    expired_subscriptions.append(result["subscription_name"])
        
        # Xóa các subscriptions đã expired
        if expired_subscriptions:
            for sub_name in expired_subscriptions:
                try:
                    frappe.delete_doc("Push Subscription", sub_name, ignore_permissions=True)
                except:
                    pass
            
            frappe.logger().info(f"📱 [Push Notification] Deleted {len(expired_subscriptions)} expired subscriptions for {user_email}")
            
            # Nếu TẤT CẢ subscriptions đều expired, tạo notification yêu cầu re-enable
            remaining = frappe.db.count("Push Subscription", {"user": user_email})
            if remaining == 0:
                try:
                    from erp.common.doctype.erp_notification.erp_notification import create_notification
                    
                    create_notification(
                        title="Cần bật lại thông báo đẩy",
                        message="Thông báo đẩy của bạn đã hết hạn trên tất cả thiết bị. Vui lòng truy cập trang Hồ sơ để bật lại.",
                        recipient_user=user_email,
                        recipients=[user_email],
                        notification_type="system",
                        priority="medium",
                        data={
                            "type": "push_subscription_expired",
                            "action_required": "reenable_push",
                            "url": "/profile"
                        },
                        channel="database",
                        event_timestamp=frappe.utils.now()
                    )
                except Exception as notif_error:
                    frappe.logger().error(f"Failed to create re-enable notification: {str(notif_error)}")
        
        frappe.db.commit()
        
        # Log result
        total_devices = len(subscription_docs)
        log_message = f"Push notification sent to {devices_sent}/{total_devices} devices for {user_email}: {title}"
        
        # Determine overall success
        overall_success = devices_sent > 0
        
        return {
            "success": overall_success,
            "message": f"Sent to {devices_sent}/{total_devices} device(s)" if overall_success else "Failed to send to all devices",
            "log": log_message,
            "devices_sent": devices_sent,
            "devices_failed": devices_failed,
            "total_devices": total_devices,
            "expired_removed": len(expired_subscriptions),
            "device_results": device_results
        }
        
    except Exception as e:
        error_message = f"Error sending push notification to {user_email}: {str(e)}"
        frappe.log_error(error_message, "Push Notification Error")
        
        return {
            "success": False,
            "message": f"Error: {str(e)}",
            "log": error_message,
            "devices_sent": 0,
            "devices_failed": 0
        }


@frappe.whitelist(allow_guest=False)
def send_notification_to_user(user_email, title, body, icon=None, data=None, tag=None):
    """
    API endpoint để gửi push notification (có thể gọi từ frontend hoặc backend)
    
    Args:
        user_email: Email của user
        title: Tiêu đề
        body: Nội dung
        icon: Icon URL (optional)
        data: Additional data JSON string (optional)
        tag: Notification tag (optional)
    """
    # Parse data nếu là string
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except:
            data = {}
    
    result = send_push_notification(user_email, title, body, icon, data, tag)
    return result


def send_bulk_push_notifications(user_emails, title, body, icon=None, data=None, tag=None):
    """
    Gửi push notification đến nhiều users
    
    Args:
        user_emails: List of user emails
        title, body, icon, data, tag: Notification data
        
    Returns:
        dict: {"success_count": int, "failed_count": int, "results": [...]}
    """
    results = []
    success_count = 0
    failed_count = 0
    
    for user_email in user_emails:
        result = send_push_notification(user_email, title, body, icon, data, tag)
        results.append({
            "user": user_email,
            "success": result["success"],
            "message": result["message"]
        })
        
        if result["success"]:
            success_count += 1
        else:
            failed_count += 1
    
    return {
        "success_count": success_count,
        "failed_count": failed_count,
        "total": len(user_emails),
        "results": results,
        "log": f"Sent to {success_count}/{len(user_emails)} users successfully"
    }


@frappe.whitelist(allow_guest=False)
def test_push_notification():
    """
    Test push notification cho user hiện tại
    """
    user = frappe.session.user

    result = send_push_notification(
        user_email=user,
        title="🎉 Test Notification",
        body=f"Xin chào! Đây là test notification từ Wellspring Parents Portal. Thời gian: {frappe.utils.now()}",
        icon="/icon.png",
        data={
            "type": "test",
            "url": "/",
            "timestamp": frappe.utils.now()
        },
        tag="test-notification"
    )

    return result

@frappe.whitelist(allow_guest=False)
def test_push_subscription():
    """
    Test push subscription validity without showing notification
    Returns: {"success": true/false, "message": "..."}
    """
    user = frappe.session.user

    try:
        # Get subscription data from request
        subscription_json = frappe.form_dict.get('subscription_json')
        if not subscription_json:
            return {"success": False, "message": "No subscription data provided"}

        # Parse subscription
        subscription = json.loads(subscription_json) if isinstance(subscription_json, str) else subscription_json

        # Test with minimal payload (no actual notification sent)
        response = webpush(
            subscription_info=subscription,
            data=json.dumps({
                "test": True,
                "timestamp": frappe.utils.now_datetime().isoformat()
            }),
            vapid_private_key=frappe.conf.get("vapid_private_key"),
            vapid_claims={
                "sub": f"mailto:{frappe.conf.get('vapid_claims_email', 'admin@example.com')}"
            }
        )

        # If no exception thrown, subscription is valid
        return {
            "success": True,
            "message": "Push subscription is valid",
            "log": f"Subscription test successful for {user}"
        }

    except WebPushException as e:
        error_code = getattr(e.response, 'status_code', None) if hasattr(e, 'response') else None

        if error_code == 410:
            return {
                "success": False,
                "message": "Push subscription has expired",
                "expired": True,
                "log": f"Subscription expired for {user}"
            }
        elif error_code == 400:
            return {
                "success": False,
                "message": "Push subscription is invalid",
                "invalid": True,
                "log": f"Subscription invalid for {user}"
            }
        else:
            return {
                "success": False,
                "message": f"Push subscription test failed (HTTP {error_code})",
                "error_code": error_code,
                "log": f"Subscription test failed for {user}: {str(e)}"
            }

    except Exception as e:
        return {
            "success": False,
            "message": f"Error testing push subscription: {str(e)}",
            "log": f"Subscription test error for {user}: {str(e)}"
        }


# Hook function để gửi notification khi có sự kiện
def send_notification_on_event(doc, method=None):
    """
    Example hook function để gửi notification khi có sự kiện
    Có thể hook vào các DocType khác nhau

    Usage in hooks.py:
        doc_events = {
            "Communication": {
                "after_insert": "erp.api.erp_sis.push_notification.send_notification_on_communication"
            }
        }
    """
    pass


def send_notification_on_communication(doc, method=None):
    """
    Gửi notification khi có Communication mới (tin nhắn từ giáo viên)
    """
    try:
        if doc.communication_type == "Communication" and doc.sent_or_received == "Received":
            # Lấy parent liên quan (nếu có)
            # TODO: Implement logic để tìm parent từ Communication
            
            # Send notification
            # send_push_notification(
            #     user_email=parent_email,
            #     title="📬 Tin nhắn mới từ giáo viên",
            #     body=doc.content[:100] + "..." if len(doc.content) > 100 else doc.content,
            #     data={"type": "communication", "name": doc.name}
            # )
            pass
    except Exception as e:
        frappe.log_error(f"Error sending notification on communication: {str(e)}")

