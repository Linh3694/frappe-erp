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


@frappe.whitelist(allow_guest=False)
def save_push_subscription(subscription_json=None):
    """
    Lưu push subscription của user
    Also removes any expired subscription notifications

    Args:
        subscription_json: JSON string của push subscription từ frontend

    Returns:
        dict: {"success": True, "message": "..."}
    """
    try:
        user = frappe.session.user

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
                except:
                    pass

        if subscription_json is None:
            return {
                "success": False,
                "message": "Missing subscription_json parameter"
            }

        subscription = json.loads(subscription_json) if isinstance(subscription_json, str) else subscription_json

        # Validate subscription data
        if not subscription.get("endpoint"):
            return {
                "success": False,
                "message": "Invalid subscription data - missing endpoint"
            }

        # Kiểm tra xem user đã có subscription chưa
        existing = frappe.db.exists("Push Subscription", {"user": user})

        if existing:
            # Update existing subscription
            doc = frappe.get_doc("Push Subscription", existing)
            doc.subscription_json = json.dumps(subscription)
            doc.endpoint = subscription.get("endpoint")
            doc.save(ignore_permissions=True)
            message = "Push subscription updated successfully"
        else:
            # Create new subscription
            doc = frappe.get_doc({
                "doctype": "Push Subscription",
                "user": user,
                "endpoint": subscription.get("endpoint"),
                "subscription_json": json.dumps(subscription)
            })
            doc.insert(ignore_permissions=True)
            message = "Push subscription created successfully"

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
            "log": f"Saved push subscription for user: {user}"
        }

    except Exception as e:
        frappe.log_error(f"Error saving push subscription: {str(e)}", "Push Notification Error")
        return {
            "success": False,
            "message": f"Error saving subscription: {str(e)}",
            "log": f"Error: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def delete_push_subscription():
    """
    Xóa push subscription của user hiện tại
    
    Returns:
        dict: {"success": True, "message": "..."}
    """
    try:
        user = frappe.session.user
        
        existing = frappe.db.exists("Push Subscription", {"user": user})
        
        if existing:
            frappe.delete_doc("Push Subscription", existing, ignore_permissions=True)
            frappe.db.commit()
            message = "Push subscription deleted successfully"
        else:
            message = "No subscription found"
        
        return {
            "success": True,
            "message": message,
            "log": f"Deleted push subscription for user: {user}"
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


@frappe.whitelist()
def send_push_notification(user_email, title, body, icon=None, data=None, tag=None, actions=None):
    """
    Gửi push notification đến một user cụ thể (exposed as API for testing)
    
    Args:
        user_email: Email của user cần gửi notification
        title: Tiêu đề notification
        body: Nội dung notification
        icon: URL icon (optional)
        data: Additional data (optional)
        tag: Notification tag (optional)
        actions: Array of action buttons (optional)
        
    Returns:
        dict: {"success": True/False, "message": "...", "log": "..."}
    """
    try:
        # Lấy subscription của user
        subscription_doc = frappe.db.get_value(
            "Push Subscription",
            {"user": user_email},
            ["name", "subscription_json"],
            as_dict=True
        )
        
        if not subscription_doc:
            return {
                "success": False,
                "message": f"No push subscription found for user: {user_email}",
                "log": f"User {user_email} has not subscribed to push notifications"
            }
        
        subscription = json.loads(subscription_doc.subscription_json)
        
        # VAPID keys từ site config
        vapid_private_key = frappe.conf.get("vapid_private_key")
        vapid_public_key = frappe.conf.get("vapid_public_key")
        vapid_claims_email = frappe.conf.get("vapid_claims_email", "admin@example.com")
        
        if not vapid_private_key or not vapid_public_key:
            return {
                "success": False,
                "message": "VAPID keys not configured",
                "log": "Please configure VAPID keys in site_config.json"
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
        
        # Gửi push notification
        if USE_PYWEBPUSH:
            # Sử dụng pywebpush nếu có
            response = webpush(
                subscription_info=subscription,
                data=json.dumps(payload),
                vapid_private_key=vapid_private_key,
                vapid_claims={
                    "sub": f"mailto:{vapid_claims_email}"
                }
            )
        else:
            # Fallback sang implementation đơn giản
            response = send_web_push(
                subscription_info=subscription,
                data=json.dumps(payload),
                vapid_private_key=vapid_private_key,
                vapid_claims={
                    "sub": f"mailto:{vapid_claims_email}"
                }
            )
        
        # Log success
        log_message = f"Push notification sent to {user_email}: {title}"
        
        return {
            "success": True,
            "message": "Push notification sent successfully",
            "log": log_message,
            "response": str(response)
        }
        
    except WebPushException as e:
        # Handle specific error codes
        error_code = getattr(e.response, 'status_code', None) if hasattr(e, 'response') else None
        
        # 410 Gone = subscription expired, should delete and notify user
        if error_code == 410:
            frappe.logger().warning(f"Push subscription expired for {user_email}, deleting and creating notification...")

            # Delete expired subscription
            try:
                frappe.db.delete("Push Subscription", {"user": user_email})
                frappe.db.commit()
            except Exception as del_error:
                frappe.logger().error(f"Failed to delete expired subscription: {str(del_error)}")

            # Create notification to inform user to re-enable push notifications
            try:
                from erp.common.doctype.erp_notification.erp_notification import create_notification

                create_notification(
                    title="Cần bật lại thông báo đẩy",
                    message="Thông báo đẩy của bạn đã hết hạn. Vui lòng truy cập trang Hồ sơ để bật lại thông báo đẩy.",
                    recipient_user=user_email,
                    recipients=[user_email],
                    notification_type="system",
                    priority="medium",
                    data={
                        "type": "push_subscription_expired",
                        "action_required": "reenable_push",
                        "url": "/profile"
                    },
                    channel="database",  # Only show in notification list, no push
                    event_timestamp=frappe.utils.now()
                )

                frappe.db.commit()
                frappe.logger().info(f"Created re-enable notification for {user_email}")

            except Exception as notif_error:
                frappe.logger().error(f"Failed to create re-enable notification: {str(notif_error)}")

            return {
                "success": False,
                "message": "Push subscription expired and has been removed. User notified to re-enable.",
                "log": f"Subscription for {user_email} was expired (410 Gone) - user notified",
                "subscription_expired": True
            }
        
        # Other errors
        return {
            "success": False,
            "message": f"Failed to send push notification: {str(e)}",
            "log": f"WebPushException for {user_email}: {str(e)}"
        }
        
    except Exception as e:
        error_message = f"Error sending push notification to {user_email}: {str(e)}"
        frappe.log_error(error_message, "Push Notification Error")
        
        # Try to clean up expired subscription if possible
        try:
            if hasattr(e, 'response') and hasattr(e.response, 'status_code') and e.response.status_code in [404, 410]:
                frappe.db.delete("Push Subscription", {"user": user_email})
                frappe.db.commit()
                error_message += " (Subscription removed as invalid)"
        except:
            pass
        
        return {
            "success": False,
            "message": f"Error: {str(e)}",
            "log": error_message
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


# Hook function để gửi notification khi có sự kiện
def send_notification_on_event(doc, method=None):
    """
    Example hook function để gửi notification khi có sự kiện
    Có thể hook vào các DocType khác nhau
    
    Usage in hooks.py:
        doc_events = {
            "Communication": {
                "after_insert": "erp.api.parent_portal.push_notification.send_notification_on_communication"
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

