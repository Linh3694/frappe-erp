"""
Push Notifications API for mobile app
Stores push tokens and forwards to notification service
"""

import frappe
import json
import requests
from frappe import _
from frappe.utils import now


@frappe.whitelist()
def register_device():
    """Register device token for push notifications"""
    try:
        data = frappe.get_request_data()
        device_token = data.get('deviceToken')
        
        if not device_token:
            frappe.throw(_("Device token is required"))
        
        user = frappe.get_doc("User", frappe.session.user)
        
        # Store token in User doctype (custom field needed)
        if not hasattr(user, 'push_token'):
            # Create custom field if not exists
            create_push_token_field()
        
        # Update user's push token
        user.push_token = device_token
        user.push_token_updated = now()
        user.save(ignore_permissions=True)
        
        # Try to forward to notification service
        try:
            forward_to_notification_service('register', device_token, frappe.session.user)
        except Exception as e:
            frappe.log_error(f"Failed to forward to notification service: {str(e)}", "Push Token Registration")
        
        return {
            "success": True,
            "message": "Device token registered successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error registering device token: {str(e)}", "Push Token Registration")
        return {
            "success": False,
            "message": str(e)
        }


@frappe.whitelist()
def unregister_device():
    """Unregister device token"""
    try:
        data = frappe.get_request_data()
        device_token = data.get('deviceToken')
        
        user = frappe.get_doc("User", frappe.session.user)
        
        # Clear token from User
        if hasattr(user, 'push_token'):
            user.push_token = None
            user.push_token_updated = now()
            user.save(ignore_permissions=True)
        
        # Try to forward to notification service
        try:
            forward_to_notification_service('unregister', device_token, frappe.session.user)
        except Exception as e:
            frappe.log_error(f"Failed to forward to notification service: {str(e)}", "Push Token Unregistration")
        
        return {
            "success": True,
            "message": "Device token unregistered successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error unregistering device token: {str(e)}", "Push Token Unregistration")
        return {
            "success": False,
            "message": str(e)
        }


def forward_to_notification_service(action, device_token, user_id):
    """Forward push token to notification service"""
    try:
        # Get notification service URL from settings
        notification_service_url = frappe.conf.get('notification_service_url', 'http://172.16.20.115:5001')
        
        endpoint = f"{notification_service_url}/api/notification/register-device" if action == 'register' else f"{notification_service_url}/api/notification/unregister-device"
        
        # Create internal JWT token for service-to-service communication
        from frappe.utils.password import get_decrypted_password
        jwt_secret = frappe.conf.get('jwt_secret_key', 'breakpoint')
        
        import jwt as pyjwt
        import time
        
        # Create token for notification service
        token_payload = {
            'userId': user_id,
            'name': user_id,
            'exp': int(time.time()) + 3600  # 1 hour expiry
        }
        
        token = pyjwt.encode(token_payload, jwt_secret, algorithm='HS256')
        
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {token}'
        }
        
        payload = {
            'deviceToken': device_token
        }
        
        response = requests.post(endpoint, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        
        frappe.logger().info(f"Successfully forwarded {action} to notification service for user {user_id}")
        
    except Exception as e:
        frappe.logger().error(f"Failed to forward {action} to notification service: {str(e)}")
        raise


def create_push_token_field():
    """Create custom fields for push tokens in User doctype"""
    try:
        # Check if custom fields already exist
        if frappe.db.exists("Custom Field", {"fieldname": "push_token", "dt": "User"}):
            return
            
        # Create push token field
        push_token_field = frappe.get_doc({
            "doctype": "Custom Field",
            "dt": "User",
            "fieldname": "push_token",
            "label": "Push Token",
            "fieldtype": "Data",
            "read_only": 1,
            "no_copy": 1,
            "insert_after": "mobile_no"
        })
        push_token_field.insert(ignore_permissions=True)
        
        # Create push token updated field
        push_token_updated_field = frappe.get_doc({
            "doctype": "Custom Field", 
            "dt": "User",
            "fieldname": "push_token_updated",
            "label": "Push Token Updated",
            "fieldtype": "Datetime",
            "read_only": 1,
            "no_copy": 1,
            "insert_after": "push_token"
        })
        push_token_updated_field.insert(ignore_permissions=True)
        
        frappe.logger().info("Created push token custom fields in User doctype")
        
    except Exception as e:
        frappe.logger().error(f"Error creating push token custom fields: {str(e)}")


@frappe.whitelist()
def get_user_tokens(user_id=None):
    """Get all push tokens for users (admin only)"""
    if not frappe.has_permission("User", "read"):
        frappe.throw(_("Not permitted"))
    
    filters = {}
    if user_id:
        filters['name'] = user_id
        
    users = frappe.get_all("User", 
                          filters=filters,
                          fields=["name", "email", "full_name", "push_token", "push_token_updated"],
                          order_by="push_token_updated desc")
    
    # Filter out users without tokens
    users_with_tokens = [user for user in users if user.get('push_token')]
    
    return {
        "success": True,
        "data": users_with_tokens,
        "count": len(users_with_tokens)
    }


@frappe.whitelist()
def test_notification(user_id, title="Test", message="This is a test notification"):
    """Send test notification (admin only)"""
    if not frappe.has_permission("User", "write"):
        frappe.throw(_("Not permitted"))
        
    try:
        # Forward to notification service for sending
        forward_test_notification(user_id, title, message)
        
        return {
            "success": True,
            "message": f"Test notification sent to {user_id}"
        }
        
    except Exception as e:
        frappe.log_error(f"Error sending test notification: {str(e)}", "Test Notification")
        return {
            "success": False,
            "message": str(e)
        }


def forward_test_notification(user_id, title, message):
    """Forward test notification to notification service"""
    try:
        notification_service_url = frappe.conf.get('notification_service_url', 'http://localhost:5003')
        
        endpoint = f"{notification_service_url}/api/notification"
        
        # Create JWT token
        jwt_secret = frappe.conf.get('jwt_secret_key', 'breakpoint')
        import jwt as pyjwt
        import time
        
        token_payload = {
            'userId': 'Administrator',
            'name': 'Administrator',
            'exp': int(time.time()) + 3600
        }
        
        token = pyjwt.encode(token_payload, jwt_secret, algorithm='HS256')
        
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {token}'
        }
        
        payload = {
            'title': title,
            'message': message,
            'recipients': [user_id],
            'notification_type': 'test',
            'priority': 'medium',
            'channel': 'push',
            'data': {
                'type': 'test_notification',
                'sent_from': 'frappe_backend'
            }
        }
        
        response = requests.post(endpoint, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        
        frappe.logger().info(f"Test notification sent successfully to {user_id}")
        
    except Exception as e:
        frappe.logger().error(f"Failed to send test notification: {str(e)}")
        raise
