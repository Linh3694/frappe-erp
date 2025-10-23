# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
import secrets
import requests
import json
from datetime import datetime, timedelta

# VIVAS SMS Configuration
VIVAS_SMS_CONFIG = {
    "url": "https://sms.vivas.vn/SMSBNAPINEW/sendsms",
    "username": frappe.conf.get("vivas_sms_username", "wellspring"),
    "password": frappe.conf.get("vivas_sms_password", "2805@Smsbn"),
    "brandname": frappe.conf.get("vivas_sms_brandname", "WELLSPRING"),
    # IMPORTANT: Set to False in production to prevent accidental SMS sending
    "enabled": frappe.conf.get("vivas_sms_enabled", False),  # Default False for safety
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
        logs.append(f"🔑 Username: {VIVAS_SMS_CONFIG['username']}")
        logs.append(f"🔑 Password: {VIVAS_SMS_CONFIG['password']}")
        logs.append(f"🏷️ Brandname: {VIVAS_SMS_CONFIG['brandname']}")
        logs.append(f"📱 Phone: {phone_number}")
        logs.append(f"📝 Message: {message}")

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
        frappe.log_error(f"VIVAS SMS Error: {str(e)}", "Bus Application SMS")

        return {
            "success": False,
            "message": f"SMS service error: {str(e)}",
            "logs": logs,
            "error": str(e)
        }


@frappe.whitelist(allow_guest=True)
@rate_limit(limit=5, seconds=3600)  # 5 attempts per hour
def request_otp(phone_number):
    """
    Request OTP for bus monitor phone number authentication

    Args:
        phone_number: Bus monitor's phone number

    Returns:
        dict: Response with monitor info and OTP status
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

        # Find bus monitor by phone number
        monitors = frappe.get_all(
            "SIS Bus Monitor",
            filters={"phone_number": normalized_phone, "status": "Active"},
            fields=["name", "monitor_code", "full_name", "phone_number", "campus_id", "school_year_id"]
        )

        if not monitors:
            logs.append(f"❌ No active bus monitor found with phone: {normalized_phone}")
            return {
                "success": False,
                "message": "Không tìm thấy giám sát viên với số điện thoại này",
                "logs": logs
            }

        monitor = monitors[0]
        logs.append(f"✅ Found monitor: {monitor['full_name']} ({monitor['monitor_code']})")

        # Generate OTP
        otp_code = generate_otp(6)
        logs.append(f"🔐 Generated OTP: {otp_code}")

        # Store OTP in cache (expires in 5 minutes)
        cache_key = f"bus_monitor_otp:{normalized_phone}"
        frappe.cache().set_value(
            cache_key,
            {
                "otp": otp_code,
                "monitor_name": monitor["full_name"],
                "monitor_code": monitor["monitor_code"],
                "phone_number": normalized_phone,
                "created_at": datetime.now().isoformat()
            },
            expires_in_sec=300  # 5 minutes
        )
        logs.append(f"💾 Stored OTP in cache with key: {cache_key}")

        # Prepare SMS message
        sms_message = f"Ma xac thuc Bus App cua ban la: {otp_code}. Ma co hieu luc trong 5 phut."

        # Send SMS
        sms_result = send_sms_via_vivas(normalized_phone, sms_message)
        logs.extend(sms_result.get("logs", []))

        # Return response
        return {
            "success": True,
            "message": "Mã OTP đã được gửi đến số điện thoại của bạn",
            "data": {
                "monitor_name": monitor["full_name"],
                "monitor_code": monitor["monitor_code"],
                "phone_number": normalized_phone,
                "otp_sent": sms_result.get("success", False),
                "sms_mock": sms_result.get("mock", False)
            },
            "logs": logs
        }

    except Exception as e:
        logs.append(f"❌ Error: {str(e)}")
        frappe.log_error(f"Request OTP Error: {str(e)}\nLogs: {json.dumps(logs)}", "Bus Application OTP")
        return {
            "success": False,
            "message": f"Lỗi hệ thống: {str(e)}",
            "logs": logs
        }


@frappe.whitelist(allow_guest=True)
def verify_otp_and_login(phone_number, otp):
    """
    Verify OTP and login bus monitor

    Args:
        phone_number: Bus monitor's phone number
        otp: OTP code to verify

    Returns:
        dict: Response with JWT token and monitor info
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
        cache_key = f"bus_monitor_otp:{normalized_phone}"
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

        # Get monitor details
        monitors = frappe.get_all(
            "SIS Bus Monitor",
            filters={"phone_number": normalized_phone, "status": "Active"},
            fields=["name", "monitor_code", "full_name", "phone_number", "campus_id", "school_year_id", "contractor", "address"]
        )

        if not monitors:
            logs.append(f"❌ Monitor not found after OTP verification")
            return {
                "success": False,
                "message": "Không tìm thấy thông tin giám sát viên",
                "logs": logs
            }

        monitor = monitors[0]
        logs.append(f"✅ Monitor found: {monitor['full_name']}")

        # Get or create User for this monitor
        user_email = f"{monitor['monitor_code']}@busmonitor.wellspring.edu.vn"

        if not frappe.db.exists("User", user_email):
            logs.append(f"📝 Creating new User for monitor: {user_email}")

            # Create user
            user_doc = frappe.get_doc({
                "doctype": "User",
                "email": user_email,
                "first_name": monitor["full_name"],
                "enabled": 1,
                "user_type": "Website User",
                "send_welcome_email": 0
            })
            user_doc.flags.ignore_permissions = True
            user_doc.insert(ignore_permissions=True)

            # Add Bus Monitor role
            user_doc.add_roles("Bus Monitor")

            logs.append(f"✅ User created: {user_email}")
        else:
            logs.append(f"✅ User already exists: {user_email}")

        # Generate JWT token (30 days expiry as per Context.md)
        from erp.api.erp_common_user.auth import generate_jwt_token
        token = generate_jwt_token(user_email, expires_in_days=30)
        logs.append("JWT token generated")

        # Clear OTP from cache
        frappe.cache().delete_value(cache_key)
        logs.append("Cleared OTP from cache")

        # Get campus and school year details
        campus_info = {}
        school_year_info = {}

        if monitor.get("campus_id"):
            try:
                campus = frappe.get_doc("SIS Campus", monitor["campus_id"])
                campus_info = {
                    "name": campus.name,
                    "title_vn": campus.title_vn,
                    "title_en": campus.title_en,
                    "short_title": campus.short_title
                }
            except:
                pass

        if monitor.get("school_year_id"):
            try:
                school_year = frappe.get_doc("SIS School Year", monitor["school_year_id"])
                school_year_info = {
                    "name": school_year.name,
                    "title_vn": school_year.title_vn,
                    "title_en": school_year.title_en
                }
            except:
                pass

        # Return success response
        return {
            "success": True,
            "message": "Đăng nhập thành công",
            "data": {
                "monitor": {
                    "name": monitor["name"],
                    "monitor_code": monitor["monitor_code"],
                    "full_name": monitor["full_name"],
                    "phone_number": monitor["phone_number"],
                    "campus_id": monitor["campus_id"],
                    "school_year_id": monitor["school_year_id"],
                    "contractor": monitor.get("contractor", ""),
                    "address": monitor.get("address", "")
                },
                "user": {
                    "email": user_email,
                    "full_name": monitor["full_name"]
                },
                "campus": campus_info,
                "school_year": school_year_info,
                "token": token,
                "expires_in": 30 * 24 * 60 * 60  # 30 days in seconds
            },
            "logs": logs
        }

    except Exception as e:
        logs.append(f"❌ Error: {str(e)}")
        frappe.log_error(f"Verify OTP Error: {str(e)}\nLogs: {json.dumps(logs)}", "Bus Application OTP")
        return {
            "success": False,
            "message": f"Lỗi hệ thống: {str(e)}",
            "logs": logs
        }


@frappe.whitelist()
def get_monitor_profile():
    """
    Get current logged-in bus monitor information
    Requires authentication

    Returns:
        dict: Monitor information
    """
    try:
        user_email = frappe.session.user

        if user_email == "Guest":
            return {
                "success": False,
                "message": "Vui lòng đăng nhập"
            }

        # Extract monitor_code from email (format: monitor_code@busmonitor.wellspring.edu.vn)
        if "@busmonitor.wellspring.edu.vn" not in user_email:
            return {
                "success": False,
                "message": "Tài khoản không hợp lệ"
            }

        monitor_code = user_email.split("@")[0]

        # Get monitor (ignore permissions as user can only access their own data)
        monitors = frappe.get_all(
            "SIS Bus Monitor",
            filters={"monitor_code": monitor_code, "status": "Active"},
            fields=["name", "monitor_code", "full_name", "phone_number", "campus_id", "school_year_id", "contractor", "address"]
        )

        if not monitors:
            return {
                "success": False,
                "message": "Không tìm thấy thông tin giám sát viên"
            }

        monitor = monitors[0]

        # Get campus and school year details
        campus_info = {}
        school_year_info = {}

        if monitor.get("campus_id"):
            try:
                campus = frappe.get_doc("SIS Campus", monitor["campus_id"])
                campus_info = {
                    "name": campus.name,
                    "title_vn": campus.title_vn,
                    "title_en": campus.title_en,
                    "short_title": campus.short_title
                }
            except:
                pass

        if monitor.get("school_year_id"):
            try:
                school_year = frappe.get_doc("SIS School Year", monitor["school_year_id"])
                school_year_info = {
                    "name": school_year.name,
                    "title_vn": school_year.title_vn,
                    "title_en": school_year.title_en
                }
            except:
                pass

        return {
            "success": True,
            "data": {
                "monitor": monitor,
                "campus": campus_info,
                "school_year": school_year_info,
                "user": {
                    "email": user_email,
                    "full_name": monitor["full_name"]
                }
            }
        }

    except Exception as e:
        frappe.log_error(f"Get Monitor Profile Error: {str(e)}", "Bus Application")
        return {
            "success": False,
            "message": f"Lỗi hệ thống: {str(e)}"
        }


@frappe.whitelist()
def refresh_token():
    """
    Refresh JWT token for bus monitor
    Requires authentication

    Returns:
        dict: New JWT token
    """
    try:
        user_email = frappe.session.user

        if user_email == "Guest":
            return {
                "success": False,
                "message": "Vui lòng đăng nhập"
            }

        # Extract monitor_code from email (format: monitor_code@busmonitor.wellspring.edu.vn)
        if "@busmonitor.wellspring.edu.vn" not in user_email:
            return {
                "success": False,
                "message": "Tài khoản không hợp lệ"
            }

        monitor_code = user_email.split("@")[0]

        # Verify monitor exists and is active
        monitors = frappe.get_all(
            "SIS Bus Monitor",
            filters={"monitor_code": monitor_code, "status": "Active"},
            fields=["full_name"]
        )

        if not monitors:
            return {
                "success": False,
                "message": "Giám sát viên không tồn tại hoặc không hoạt động"
            }

        # Generate new JWT token
        from erp.api.erp_common_user.auth import generate_jwt_token
        token = generate_jwt_token(user_email, expires_in_days=30)

        return {
            "success": True,
            "message": "Token đã được làm mới",
            "data": {
                "token": token,
                "expires_in": 30 * 24 * 60 * 60  # 30 days in seconds
            }
        }

    except Exception as e:
        frappe.log_error(f"Refresh Token Error: {str(e)}", "Bus Application")
        return {
            "success": False,
            "message": f"Lỗi hệ thống: {str(e)}"
        }
