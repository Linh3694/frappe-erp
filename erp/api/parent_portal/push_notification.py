"""
Push Notification API for Parent Portal PWA
Xử lý push subscriptions và gửi notifications đến phụ huynh
"""

import frappe
import json
from frappe import _
from pywebpush import webpush, WebPushException


@frappe.whitelist(allow_guest=False)
def save_push_subscription(subscription_json):
    """
    Lưu push subscription của user
    
    Args:
        subscription_json: JSON string của push subscription từ frontend
        
    Returns:
        dict: {"success": True, "message": "..."}
    """
    try:
        user = frappe.session.user
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


@frappe.whitelist(allow_guest=False)
def get_vapid_public_key():
    """
    Lấy VAPID public key để frontend subscribe
    
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


def send_push_notification(user_email, title, body, icon=None, data=None, tag=None, actions=None):
    """
    Gửi push notification đến một user cụ thể
    
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
        response = webpush(
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
        error_message = f"WebPush error for {user_email}: {str(e)}"
        frappe.log_error(error_message, "Push Notification Error")
        
        # Nếu subscription expired hoặc invalid, xóa nó
        if e.response and e.response.status_code in [404, 410]:
            try:
                frappe.db.delete("Push Subscription", {"user": user_email})
                frappe.db.commit()
                error_message += " (Subscription removed as it's invalid)"
            except:
                pass
        
        return {
            "success": False,
            "message": f"Failed to send push notification: {str(e)}",
            "log": error_message
        }
        
    except Exception as e:
        error_message = f"Error sending push notification to {user_email}: {str(e)}"
        frappe.log_error(error_message, "Push Notification Error")
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

