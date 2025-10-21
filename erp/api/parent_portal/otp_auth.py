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
    "enabled": True,  # Set to True only when ready to send real SMS
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
        sms_message = f"Ma xac thuc Parent Portal cua ban la: {otp_code}. Ma co hieu luc trong 5 phut."
        
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
        logs.append("JWT token generated")
        
        # Clear OTP from cache
        frappe.cache().delete_value(cache_key)
        logs.append("Cleared OTP from cache")

        # Get comprehensive guardian data
        comprehensive_data = get_guardian_comprehensive_data(guardian["name"])

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
                "family": comprehensive_data.get("data", {}).get("family", {}),
                "families": comprehensive_data.get("data", {}).get("families", []),  # ✅ Add families array
                "students": comprehensive_data.get("data", {}).get("students", []),
                "campus": comprehensive_data.get("data", {}).get("campus", {}),
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


@frappe.whitelist()
def get_current_guardian_comprehensive_data():
    """
    Get comprehensive data for current logged-in guardian
    Requires authentication

    Returns:
        dict: Comprehensive guardian data including family, students, and campus
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
            fields=["name", "guardian_id", "guardian_name", "phone_number", "email", "family_code"],
            ignore_permissions=True
        )

        if not guardian_list:
            return {
                "success": False,
                "message": "Không tìm thấy thông tin phụ huynh"
            }

        guardian = guardian_list[0]

        # Get comprehensive data using existing function
        comprehensive_result = get_guardian_comprehensive_data(guardian["name"])

        if not comprehensive_result.get("success", False):
            return {
                "success": False,
                "message": comprehensive_result.get("error", "Không thể lấy dữ liệu guardian")
            }

        return {
            "success": True,
            "data": comprehensive_result["data"],
            "logs": comprehensive_result.get("logs", [])
        }

    except Exception as e:
        frappe.log_error(f"Get Guardian Comprehensive Data Error: {str(e)}", "Parent Portal")
        return {
            "success": False,
            "message": f"Lỗi hệ thống: {str(e)}"
        }




def get_guardian_comprehensive_data(guardian_name):
    """
    Get comprehensive data for a guardian including ALL family and student information
    Now supports multiple families - returns ALL families where guardian is a member

    Args:
        guardian_name: Guardian document name

    Returns:
        dict: Comprehensive data including families array, students, and campus info
    """
    logs = []

    try:
        # Get guardian details
        guardian = frappe.get_doc("CRM Guardian", guardian_name)
        logs.append(f"✅ Retrieved guardian: {guardian.guardian_name}")

        comprehensive_data = {
            "families": [],  # Array of families - supports multiple families
            "students": [],  # Flat list of all students across all families
            "campus": {}     # Primary campus (from first student)
        }

        # NEW APPROACH: Find ALL families where this guardian appears in relationships
        logs.append(f"🔍 Finding all families where guardian {guardian_name} is a member...")

        # Get all relationships where this guardian is involved
        all_guardian_relationships = frappe.get_all(
            "CRM Family Relationship",
            filters={"guardian": guardian_name},
            fields=["parent", "name", "student", "guardian", "relationship_type", "key_person", "access"],
            ignore_permissions=True
        )

        if not all_guardian_relationships:
            logs.append("⚠️ No relationships found for this guardian")
            # Return empty structure
            return {
                "success": True,
                "data": comprehensive_data,
                "logs": logs
            }

        logs.append(f"✅ Found {len(all_guardian_relationships)} relationships for this guardian")

        # Group relationships by family (parent field is the family name)
        families_dict = {}
        for rel in all_guardian_relationships:
            family_name = rel["parent"]
            if family_name not in families_dict:
                families_dict[family_name] = []
            families_dict[family_name].append(rel)

        logs.append(f"✅ Guardian belongs to {len(families_dict)} families")

        # Track processed students to avoid duplicates in the flat students list
        processed_students = set()

        # Process each family
        for family_name, family_rels in families_dict.items():
            try:
                # Get family document
                family_doc = frappe.get_doc("CRM Family", family_name)
                logs.append(f"✅ Processing family: {family_doc.family_code}")

                # Get ALL relationships for this family (includes all members, not just this guardian)
                all_family_relationships = frappe.get_all(
                    "CRM Family Relationship",
                    filters={"parent": family_name},
                    fields=["name", "student", "guardian", "relationship_type", "key_person", "access"],
                    ignore_permissions=True
                )

                family_data = {
                    "name": family_doc.name,
                    "family_code": family_doc.family_code,
                    "relationships": []
                }

                # Process each relationship in this family
                for rel in all_family_relationships:
                    rel_data = {
                        "name": rel["name"],
                        "student_name": rel["student"],
                        "guardian_name": rel["guardian"],
                        "relationship_type": rel["relationship_type"],
                        "key_person": rel["key_person"],
                        "access": rel["access"],
                        "student_details": {},
                        "guardian_details": {}
                    }

                    # Get student details
                    if rel["student"]:
                        try:
                            student = frappe.get_doc("CRM Student", rel["student"])
                            
                            student_details = {
                                "name": student.name,
                                "student_name": student.student_name,
                                "student_code": student.student_code,
                                "dob": student.dob.strftime("%Y-%m-%d") if student.dob else None,
                                "gender": student.gender,
                                "campus_id": student.campus_id,
                                "family_code": student.family_code
                            }

                            # Get SIS Photo
                            sis_photos = frappe.get_all("SIS Photo",
                                filters={
                                    "student_id": student.name,
                                    "type": "student",
                                    "status": "Active"
                                },
                                fields=["photo", "title", "upload_date"],
                                order_by="upload_date desc",
                                limit_page_length=1
                            )

                            if sis_photos:
                                student_details["sis_photo"] = sis_photos[0]["photo"]
                                student_details["photo_title"] = sis_photos[0]["title"]
                            else:
                                student_details["sis_photo"] = None

                            # Get current class (only regular type)
                            class_students = frappe.get_all("SIS Class Student",
                                filters={"student_id": student.name},
                                fields=["class_id", "school_year_id"],
                                order_by="modified desc"
                            )

                            # Find the latest regular class
                            current_class = None
                            for cs in class_students:
                                if cs["class_id"]:
                                    try:
                                        class_doc = frappe.get_doc("SIS Class", cs["class_id"])
                                        if getattr(class_doc, 'class_type', '') == 'regular':
                                            current_class = {
                                                'class_id': cs["class_id"],
                                                'school_year_id': cs["school_year_id"],
                                                'class_doc': class_doc
                                            }
                                            break  # Take the most recent regular class
                                    except:
                                        continue

                            if current_class:
                                student_details["current_class_id"] = current_class["class_id"]
                                student_details["school_year_id"] = current_class["school_year_id"]
                                student_details["class_name"] = getattr(current_class["class_doc"], 'title', '')
                                student_details["grade"] = getattr(current_class["class_doc"], 'education_grade', None)

                                # Get homeroom teachers information
                                class_doc = current_class["class_doc"]
                                teachers_info = {}

                                # Get homeroom teacher
                                if getattr(class_doc, 'homeroom_teacher', None):
                                    try:
                                        homeroom_teacher = frappe.get_doc("SIS Teacher", class_doc.homeroom_teacher)
                                        user_info = None
                                        if getattr(homeroom_teacher, 'user_id', None):
                                            try:
                                                user = frappe.get_doc("User", homeroom_teacher.user_id)
                                                user_info = {
                                                    "full_name": getattr(user, 'full_name', ''),
                                                    "email": getattr(user, 'email', ''),
                                                    "user_image": getattr(user, 'user_image', None),
                                                    "mobile_no": getattr(user, 'mobile_no', ''),
                                                    "phone": getattr(user, 'phone', '')
                                                }
                                            except Exception as e:
                                                logs.append(f"⚠️ Could not get user info for homeroom teacher: {str(e)}")

                                        teachers_info["homeroom_teacher"] = {
                                            "name": homeroom_teacher.name,
                                            "teacher_name": getattr(homeroom_teacher, 'teacher_name', ''),
                                            "teacher_code": getattr(homeroom_teacher, 'teacher_code', ''),
                                            "email": user_info.get('email') if user_info else getattr(homeroom_teacher, 'email', ''),
                                            "phone": user_info.get('mobile_no') or user_info.get('phone') if user_info else getattr(homeroom_teacher, 'phone', ''),
                                            "avatar": user_info.get('user_image') if user_info and user_info.get('user_image') else None,
                                            "full_name": user_info.get('full_name') if user_info else getattr(homeroom_teacher, 'teacher_name', '')
                                        }
                                    except Exception as e:
                                        logs.append(f"⚠️ Could not get homeroom teacher: {str(e)}")

                                # Get vice homeroom teacher
                                if getattr(class_doc, 'vice_homeroom_teacher', None):
                                    try:
                                        vice_homeroom_teacher = frappe.get_doc("SIS Teacher", class_doc.vice_homeroom_teacher)
                                        user_info = None
                                        if getattr(vice_homeroom_teacher, 'user_id', None):
                                            try:
                                                user = frappe.get_doc("User", vice_homeroom_teacher.user_id)
                                                user_info = {
                                                    "full_name": getattr(user, 'full_name', ''),
                                                    "email": getattr(user, 'email', ''),
                                                    "user_image": getattr(user, 'user_image', None),
                                                    "mobile_no": getattr(user, 'mobile_no', ''),
                                                    "phone": getattr(user, 'phone', '')
                                                }
                                            except Exception as e:
                                                logs.append(f"⚠️ Could not get user info for vice homeroom teacher: {str(e)}")

                                        teachers_info["vice_homeroom_teacher"] = {
                                            "name": vice_homeroom_teacher.name,
                                            "teacher_name": getattr(vice_homeroom_teacher, 'teacher_name', ''),
                                            "teacher_code": getattr(vice_homeroom_teacher, 'teacher_code', ''),
                                            "email": user_info.get('email') if user_info else getattr(vice_homeroom_teacher, 'email', ''),
                                            "phone": user_info.get('mobile_no') or user_info.get('phone') if user_info else getattr(vice_homeroom_teacher, 'phone', ''),
                                            "avatar": user_info.get('user_image') if user_info and user_info.get('user_image') else None,
                                            "full_name": user_info.get('full_name') if user_info else getattr(vice_homeroom_teacher, 'teacher_name', '')
                                        }
                                    except Exception as e:
                                        logs.append(f"⚠️ Could not get vice homeroom teacher: {str(e)}")

                                if teachers_info:
                                    student_details["teachers"] = teachers_info

                            # Get campus details (set once from first student)
                            if student.campus_id and not comprehensive_data["campus"]:
                                try:
                                    campus = frappe.get_doc("SIS Campus", student.campus_id)
                                    comprehensive_data["campus"] = {
                                        "name": campus.name,
                                        "title_vn": campus.title_vn,
                                        "title_en": campus.title_en,
                                        "short_title": campus.short_title
                                    }
                                    logs.append(f"✅ Retrieved campus: {campus.title_vn}")
                                except Exception as e:
                                    logs.append(f"⚠️ Could not get campus details: {str(e)}")

                            rel_data["student_details"] = student_details

                            # Add to flat students list (avoid duplicates)
                            if student.name not in processed_students:
                                comprehensive_data["students"].append(student_details)
                                processed_students.add(student.name)

                            logs.append(f"✅ Retrieved student: {student.student_name}")

                        except Exception as e:
                            logs.append(f"⚠️ Could not get student details for {rel['student']}: {str(e)}")

                    # Get guardian details (if different from current guardian)
                    if rel["guardian"] and rel["guardian"] != guardian_name:
                        try:
                            other_guardian = frappe.get_doc("CRM Guardian", rel["guardian"])
                            rel_data["guardian_details"] = {
                                "name": other_guardian.name,
                                "guardian_id": other_guardian.guardian_id,
                                "guardian_name": other_guardian.guardian_name,
                                "phone_number": other_guardian.phone_number,
                                "email": other_guardian.email
                            }
                            logs.append(f"✅ Retrieved related guardian: {other_guardian.guardian_name}")
                        except Exception as e:
                            logs.append(f"⚠️ Could not get guardian details: {str(e)}")

                    # Add relationship to this family
                    family_data["relationships"].append(rel_data)

                # Add this family to families array
                comprehensive_data["families"].append(family_data)
                logs.append(f"✅ Added family {family_doc.family_code} with {len(family_data['relationships'])} relationships")

            except Exception as e:
                logs.append(f"⚠️ Could not process family {family_name}: {str(e)}")

        logs.append(f"📊 Comprehensive data retrieved: {len(comprehensive_data['families'])} families, {len(comprehensive_data['students'])} students")

        # For backward compatibility, add a "family" field with the first family
        # This ensures existing frontend code doesn't break
        if comprehensive_data["families"]:
            comprehensive_data["family"] = comprehensive_data["families"][0]
        else:
            comprehensive_data["family"] = {}

        return {
            "success": True,
            "data": comprehensive_data,
            "logs": logs
        }

    except Exception as e:
        logs.append(f"❌ Error getting comprehensive data: {str(e)}")
        frappe.log_error(f"Get Comprehensive Data Error: {str(e)}\nLogs: {json.dumps(logs)}", "Parent Portal")

        return {
            "success": False,
            "data": {"families": [], "family": {}, "students": [], "campus": {}},
            "logs": logs,
            "error": str(e)
        }

