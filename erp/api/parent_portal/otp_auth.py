"""
Parent Portal OTP Authentication API
Handles phone-based OTP authentication for guardians
"""

import frappe
from frappe import _
import secrets
import requests
import json
from datetime import datetime, timedelta


# VIVAS SMS Configuration
VIVAS_SMS_CONFIG = {
    "url": "https://sms.vivas.vn/SMSBNAPINEW/sendsms",
    "username": "wellspring",
    "password": "2805@Smsbn",
    "brandname": "WELLSPRING",
    # IMPORTANT: Set to False in production to prevent accidental SMS sending
    "enabled": False,  # Set to True only when ready to send real SMS
}


def generate_otp(length=6):
    """Generate random OTP code"""
    return ''.join([str(secrets.randbelow(10)) for _ in range(length)])


def normalize_phone_number(phone):
    """
    Normalize phone number to 84XXXXXXXXX format
    Accepts: 0XXXXXXXXX, 84XXXXXXXXX, +84XXXXXXXXX
    Returns: 84XXXXXXXXX
    """
    if not phone:
        return None
    
    # Remove all spaces and special characters except +
    phone = phone.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
    
    # Remove + if present
    if phone.startswith('+'):
        phone = phone[1:]
    
    # Convert 0XXXXXXXXX to 84XXXXXXXXX
    if phone.startswith('0'):
        phone = '84' + phone[1:]
    
    # If doesn't start with 84, add it
    if not phone.startswith('84'):
        phone = '84' + phone
    
    return phone


def send_sms_via_vivas(phone_number, message):
    """
    Send SMS via VIVAS service
    
    Args:
        phone_number: Phone number in 84XXXXXXXXX format
        message: Text message to send
        
    Returns:
        dict: Response with status and details
    """
    logs = []
    
    try:
        # Check if SMS sending is enabled
        if not VIVAS_SMS_CONFIG.get("enabled", False):
            logs.append("⚠️ SMS sending is DISABLED in configuration")
            logs.append(f"📱 Would send to: {phone_number}")
            logs.append(f"📝 Message: {message}")
            
            # Return mock success response
            return {
                "success": True,
                "message": "SMS mocked (sending disabled for safety)",
                "logs": logs,
                "mock": True
            }
        
        # Prepare request payload
        payload = {
            "username": VIVAS_SMS_CONFIG["username"],
            "password": VIVAS_SMS_CONFIG["password"],
            "brandname": VIVAS_SMS_CONFIG["brandname"],
            "textmsg": message,
            "sendtime": datetime.now().strftime("%Y%m%d%H%M%S"),
            "isunicode": 0,  # 0 for non-Unicode, 8 for Unicode
            "listmsisdn": phone_number
        }
        
        logs.append(f"📤 Sending SMS to VIVAS API: {VIVAS_SMS_CONFIG['url']}")
        logs.append(f"📱 Phone: {phone_number}")
        
        # Send request to VIVAS
        response = requests.post(
            VIVAS_SMS_CONFIG["url"],
            json=payload,
            headers={"Content-Type": "application/json;charset=UTF-8"},
            timeout=10
        )
        
        logs.append(f"📥 Response status: {response.status_code}")
        logs.append(f"📥 Response body: {response.text}")
        
        if response.status_code == 200:
            return {
                "success": True,
                "message": "SMS sent successfully",
                "logs": logs,
                "response": response.json() if response.text else {}
            }
        else:
            return {
                "success": False,
                "message": f"SMS sending failed: {response.status_code}",
                "logs": logs,
                "error": response.text
            }
            
    except Exception as e:
        logs.append(f"❌ Error sending SMS: {str(e)}")
        frappe.log_error(f"VIVAS SMS Error: {str(e)}", "SMS Service")
        
        return {
            "success": False,
            "message": f"SMS service error: {str(e)}",
            "logs": logs,
            "error": str(e)
        }


@frappe.whitelist(allow_guest=True)
def request_otp(phone_number):
    """
    Request OTP for phone number authentication
    
    Args:
        phone_number: Guardian's phone number
        
    Returns:
        dict: Response with guardian info and OTP status
    """
    logs = []
    
    try:
        logs.append(f"📞 Received phone number: {phone_number}")
        
        # Validate phone number
        if not phone_number or not phone_number.strip():
            return {
                "success": False,
                "message": "Số điện thoại không được để trống",
                "logs": logs
            }
        
        # Normalize phone number
        normalized_phone = normalize_phone_number(phone_number)
        logs.append(f"📱 Normalized phone: {normalized_phone}")
        
        # Find guardian by phone number (try both formats: with and without +)
        # Database might store as +84XXXXXXXXX or 84XXXXXXXXX
        guardian_list = frappe.db.get_list(
            "CRM Guardian",
            filters={"phone_number": ["in", [normalized_phone, f"+{normalized_phone}"]]},
            fields=["name", "guardian_name", "phone_number", "email"],
            ignore_permissions=True
        )
        
        if not guardian_list:
            logs.append(f"❌ No guardian found with phone: {normalized_phone} or +{normalized_phone}")
            return {
                "success": False,
                "message": "Không tìm thấy phụ huynh với số điện thoại này",
                "logs": logs
            }
        
        guardian = guardian_list[0]
        logs.append(f"✅ Found guardian: {guardian['guardian_name']} ({guardian['name']})")
        
        # Generate OTP
        otp_code = generate_otp(6)
        logs.append(f"🔐 Generated OTP: {otp_code}")
        
        # Store OTP in cache (expires in 5 minutes)
        cache_key = f"parent_portal_otp:{normalized_phone}"
        frappe.cache().set_value(
            cache_key,
            {
                "otp": otp_code,
                "guardian_name": guardian["name"],
                "phone_number": normalized_phone,
                "created_at": datetime.now().isoformat()
            },
            expires_in_sec=300  # 5 minutes
        )
        logs.append(f"💾 Stored OTP in cache with key: {cache_key}")
        
        # Prepare SMS message
        sms_message = f"Ma xac thuc Wellspring cua ban la: {otp_code}. Ma co hieu luc trong 5 phut."
        
        # Send SMS
        sms_result = send_sms_via_vivas(normalized_phone, sms_message)
        logs.extend(sms_result.get("logs", []))
        
        # Return response
        return {
            "success": True,
            "message": "Mã OTP đã được gửi đến số điện thoại của bạn",
            "data": {
                "guardian_name": guardian["guardian_name"],
                "phone_number": normalized_phone,
                "otp_sent": sms_result.get("success", False),
                "sms_mock": sms_result.get("mock", False)
            },
            "logs": logs
        }
        
    except Exception as e:
        logs.append(f"❌ Error: {str(e)}")
        frappe.log_error(f"Request OTP Error: {str(e)}\nLogs: {json.dumps(logs)}", "Parent Portal OTP")
        return {
            "success": False,
            "message": f"Lỗi hệ thống: {str(e)}",
            "logs": logs
        }


@frappe.whitelist(allow_guest=True)
def verify_otp_and_login(phone_number, otp):
    """
    Verify OTP and login guardian
    
    Args:
        phone_number: Guardian's phone number
        otp: OTP code to verify
        
    Returns:
        dict: Response with JWT token and guardian info
    """
    logs = []
    
    try:
        logs.append(f"📞 Verifying OTP for phone: {phone_number}")
        
        # Validate inputs
        if not phone_number or not otp:
            return {
                "success": False,
                "message": "Số điện thoại và mã OTP không được để trống",
                "logs": logs
            }
        
        # Normalize phone number
        normalized_phone = normalize_phone_number(phone_number)
        logs.append(f"📱 Normalized phone: {normalized_phone}")
        
        # Get OTP from cache
        cache_key = f"parent_portal_otp:{normalized_phone}"
        cached_data = frappe.cache().get_value(cache_key)
        
        if not cached_data:
            logs.append(f"❌ No OTP found in cache for: {normalized_phone}")
            return {
                "success": False,
                "message": "Mã OTP đã hết hạn hoặc không tồn tại. Vui lòng yêu cầu mã mới.",
                "logs": logs
            }
        
        logs.append(f"💾 Found cached OTP data")
        
        # Verify OTP
        if cached_data["otp"] != otp.strip():
            logs.append(f"❌ OTP mismatch: expected {cached_data['otp']}, got {otp}")
            return {
                "success": False,
                "message": "Mã OTP không đúng. Vui lòng thử lại.",
                "logs": logs
            }
        
        logs.append(f"✅ OTP verified successfully")
        
        # Get guardian details (try both formats: with and without +)
        guardian_list = frappe.db.get_list(
            "CRM Guardian",
            filters={"phone_number": ["in", [normalized_phone, f"+{normalized_phone}"]]},
            fields=["name", "guardian_name", "phone_number", "email", "guardian_id"],
            ignore_permissions=True
        )
        
        if not guardian_list:
            logs.append(f"❌ Guardian not found after OTP verification")
            return {
                "success": False,
                "message": "Không tìm thấy thông tin phụ huynh",
                "logs": logs
            }
        
        guardian = guardian_list[0]
        logs.append(f"✅ Guardian found: {guardian['guardian_name']}")
        
        # Get or create User for this guardian
        user_email = f"{guardian['guardian_id']}@parent.wellspring.edu.vn"
        
        if not frappe.db.exists("User", user_email):
            logs.append(f"📝 Creating new User for guardian: {user_email}")
            
            # Create user
            user_doc = frappe.get_doc({
                "doctype": "User",
                "email": user_email,
                "first_name": guardian["guardian_name"],
                "enabled": 1,
                "user_type": "Website User",
                "send_welcome_email": 0
            })
            user_doc.flags.ignore_permissions = True
            user_doc.insert(ignore_permissions=True)
            
            # Add Parent role
            user_doc.add_roles("Parent")
            
            logs.append(f"✅ User created: {user_email}")
        else:
            logs.append(f"✅ User already exists: {user_email}")
        
        # Generate JWT token
        from erp.api.erp_common_user.auth import generate_jwt_token
        token = generate_jwt_token(user_email)
        logs.append(f"🔑 JWT token generated")
        
        # Clear OTP from cache
        frappe.cache().delete_value(cache_key)
        logs.append(f"🗑️ Cleared OTP from cache")
        
        # Return success response
        return {
            "success": True,
            "message": "Đăng nhập thành công",
            "data": {
                "guardian": {
                    "name": guardian["name"],
                    "guardian_id": guardian["guardian_id"],
                    "guardian_name": guardian["guardian_name"],
                    "phone_number": guardian["phone_number"],
                    "email": guardian.get("email", "")
                },
                "user": {
                    "email": user_email,
                    "full_name": guardian["guardian_name"]
                },
                "token": token,
                "expires_in": 365 * 24 * 60 * 60  # 365 days
            },
            "logs": logs
        }
        
    except Exception as e:
        logs.append(f"❌ Error: {str(e)}")
        frappe.log_error(f"Verify OTP Error: {str(e)}\nLogs: {json.dumps(logs)}", "Parent Portal OTP")
        return {
            "success": False,
            "message": f"Lỗi hệ thống: {str(e)}",
            "logs": logs
        }


@frappe.whitelist()
def get_guardian_info():
    """
    Get current logged-in guardian information
    Requires authentication
    
    Returns:
        dict: Guardian information
    """
    try:
        user_email = frappe.session.user
        
        if user_email == "Guest":
            return {
                "success": False,
                "message": "Vui lòng đăng nhập"
            }
        
        # Extract guardian_id from email (format: guardian_id@parent.wellspring.edu.vn)
        if "@parent.wellspring.edu.vn" not in user_email:
            return {
                "success": False,
                "message": "Tài khoản không hợp lệ"
            }
        
        guardian_id = user_email.split("@")[0]
        
        # Get guardian (ignore permissions as user can only access their own data)
        guardian_list = frappe.db.get_list(
            "CRM Guardian",
            filters={"guardian_id": guardian_id},
            fields=["name", "guardian_id", "guardian_name", "phone_number", "email"],
            ignore_permissions=True
        )
        
        if not guardian_list:
            return {
                "success": False,
                "message": "Không tìm thấy thông tin phụ huynh"
            }
        
        guardian = guardian_list[0]
        
        return {
            "success": True,
            "data": {
                "guardian": guardian,
                "user": {
                    "email": user_email,
                    "full_name": guardian["guardian_name"]
                }
            }
        }
        
    except Exception as e:
        frappe.log_error(f"Get Guardian Info Error: {str(e)}", "Parent Portal")
        return {
            "success": False,
            "message": f"Lỗi hệ thống: {str(e)}"
        }

