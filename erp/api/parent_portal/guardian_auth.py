# -*- coding: utf-8 -*-
# Copyright (c) 2026, Linh Nguyen and contributors
# For license information, please see license.txt

"""
Guardian Authentication Utilities
Xử lý JWT token cho Parent Portal với hỗ trợ force logout
"""

import frappe
from frappe import _
import jwt
from datetime import datetime, timedelta


def generate_guardian_jwt_token(user_email, guardian_name):
    """
    Generate JWT token cho Guardian với token_version.
    
    Args:
        user_email: Email của user (format: guardian_id@parent.wellspring.edu.vn)
        guardian_name: Document name của CRM Guardian
        
    Returns:
        str: JWT token
    """
    try:
        # Lấy token_version từ CRM Guardian
        token_version = frappe.db.get_value("CRM Guardian", guardian_name, "jwt_token_version") or 1
        
        # Lấy roles
        try:
            roles = frappe.get_roles(user_email) or []
        except Exception:
            roles = []
        
        now = datetime.utcnow()
        payload = {
            "sub": user_email,
            "email": user_email,
            "guardian": guardian_name,
            "token_version": token_version,  # Quan trọng: dùng để force logout
            "roles": roles,
            "iss": frappe.utils.get_url(),
            "ver": 1,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(days=365)).timestamp()),
        }
        
        secret = (
            frappe.conf.get("jwt_secret")
            or frappe.get_site_config().get("jwt_secret")
            or "default_jwt_secret_change_in_production"
        )
        
        token = jwt.encode(payload, secret, algorithm="HS256")
        return token
        
    except Exception as e:
        frappe.log_error(f"Guardian JWT token generation error: {str(e)}", "Guardian Auth")
        return None


def verify_guardian_jwt_token(token):
    """
    Verify JWT token của Guardian, bao gồm kiểm tra token_version.
    
    Args:
        token: JWT token string
        
    Returns:
        dict: Payload nếu valid, None nếu invalid
    """
    try:
        secret = (
            frappe.conf.get("jwt_secret")
            or frappe.get_site_config().get("jwt_secret")
            or "default_jwt_secret_change_in_production"
        )
        
        payload = jwt.decode(token, secret, algorithms=["HS256"])
        
        # Kiểm tra token_version (chỉ cho Parent Portal users)
        user_email = payload.get("email") or payload.get("sub")
        if user_email and '@parent.wellspring.edu.vn' in user_email:
            guardian_name = payload.get("guardian")
            token_version = payload.get("token_version")
            
            if guardian_name and token_version:
                # Lấy current token_version từ database
                current_version = frappe.db.get_value(
                    "CRM Guardian", guardian_name, "jwt_token_version"
                ) or 1
                
                # Nếu token_version không match, token đã bị revoke
                if token_version != current_version:
                    frappe.logger().warning(
                        f"Token version mismatch for {guardian_name}: "
                        f"token={token_version}, current={current_version}"
                    )
                    return None
        
        return payload
        
    except jwt.ExpiredSignatureError:
        frappe.logger().warning("Guardian JWT token expired")
        return None
    except jwt.InvalidTokenError as e:
        frappe.logger().warning(f"Invalid Guardian JWT token: {str(e)}")
        return None
    except Exception as e:
        frappe.logger().warning(f"Error verifying Guardian JWT token: {str(e)}")
        return None


@frappe.whitelist()
def force_logout_guardian(guardian_id=None, guardian_name=None):
    """
    Force logout một guardian bằng cách tăng token_version.
    Tất cả token cũ sẽ tự động invalid.
    
    Args:
        guardian_id: ID của guardian (e.g., "G12345")
        guardian_name: Document name của CRM Guardian (e.g., "CRM-GUARDIAN-00001")
        
    Returns:
        dict: {success, message}
    """
    try:
        # Tìm guardian
        if guardian_name:
            if not frappe.db.exists("CRM Guardian", guardian_name):
                return {"success": False, "message": f"Guardian không tồn tại: {guardian_name}"}
        elif guardian_id:
            guardian_name = frappe.db.get_value("CRM Guardian", {"guardian_id": guardian_id}, "name")
            if not guardian_name:
                return {"success": False, "message": f"Guardian không tồn tại: {guardian_id}"}
        else:
            return {"success": False, "message": "Cần cung cấp guardian_id hoặc guardian_name"}
        
        # Tăng token_version
        guardian = frappe.get_doc("CRM Guardian", guardian_name)
        current_version = guardian.jwt_token_version or 1
        guardian.jwt_token_version = current_version + 1
        guardian.force_logout_at = frappe.utils.now_datetime()
        guardian.save(ignore_permissions=True)
        frappe.db.commit()
        
        frappe.logger().info(
            f"Force logout guardian {guardian_name}: version {current_version} -> {current_version + 1}"
        )
        
        return {
            "success": True,
            "message": f"Đã force logout {guardian.guardian_name}. Token version: {current_version + 1}",
            "data": {
                "guardian_name": guardian_name,
                "guardian_id": guardian.guardian_id,
                "new_token_version": current_version + 1,
                "force_logout_at": str(guardian.force_logout_at)
            }
        }
        
    except Exception as e:
        frappe.log_error(f"Force logout error: {str(e)}", "Guardian Auth")
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def force_logout_all_guardians():
    """
    Force logout TẤT CẢ guardians.
    Chỉ dùng trong trường hợp khẩn cấp.
    
    Returns:
        dict: {success, message, count}
    """
    try:
        # Tăng token_version cho tất cả guardians
        frappe.db.sql("""
            UPDATE `tabCRM Guardian`
            SET jwt_token_version = COALESCE(jwt_token_version, 1) + 1,
                force_logout_at = NOW()
        """)
        frappe.db.commit()
        
        count = frappe.db.count("CRM Guardian")
        
        frappe.logger().warning(f"Force logout ALL guardians: {count} affected")
        
        return {
            "success": True,
            "message": f"Đã force logout tất cả {count} guardians",
            "count": count
        }
        
    except Exception as e:
        frappe.log_error(f"Force logout all error: {str(e)}", "Guardian Auth")
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def check_guardian_token_status(guardian_id=None, guardian_name=None):
    """
    Kiểm tra trạng thái token của guardian.
    
    Returns:
        dict: {success, data: {token_version, force_logout_at, ...}}
    """
    try:
        # Tìm guardian
        if guardian_name:
            if not frappe.db.exists("CRM Guardian", guardian_name):
                return {"success": False, "message": f"Guardian không tồn tại: {guardian_name}"}
        elif guardian_id:
            guardian_name = frappe.db.get_value("CRM Guardian", {"guardian_id": guardian_id}, "name")
            if not guardian_name:
                return {"success": False, "message": f"Guardian không tồn tại: {guardian_id}"}
        else:
            return {"success": False, "message": "Cần cung cấp guardian_id hoặc guardian_name"}
        
        guardian = frappe.get_doc("CRM Guardian", guardian_name)
        
        return {
            "success": True,
            "data": {
                "guardian_name": guardian_name,
                "guardian_id": guardian.guardian_id,
                "guardian_display_name": guardian.guardian_name,
                "token_version": guardian.jwt_token_version or 1,
                "force_logout_at": str(guardian.force_logout_at) if guardian.force_logout_at else None,
                "portal_activated": guardian.portal_activated,
                "first_login_at": str(guardian.first_login_at) if guardian.first_login_at else None,
                "last_login_at": str(guardian.last_login_at) if guardian.last_login_at else None
            }
        }
        
    except Exception as e:
        frappe.log_error(f"Check token status error: {str(e)}", "Guardian Auth")
        return {"success": False, "message": str(e)}
