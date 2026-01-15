# -*- coding: utf-8 -*-
# Copyright (c) 2026, Linh Nguyen and contributors
# For license information, please see license.txt

"""
Migration Script: Populate Guardian First Login Data
Đọc từ logging.log và các file rotated để populate first_login_at 
cho các guardians đã login trước đây.

Chạy script này một lần sau khi deploy để migrate dữ liệu lịch sử.

Sử dụng:
    bench execute erp.api.analytics.migration_guardian_login.migrate_guardian_login_data
"""

from __future__ import unicode_literals
import frappe
from frappe.utils import today, now_datetime
import json
import os
from datetime import datetime, timedelta


def get_all_log_files(base_log_file):
    """
    Lấy tất cả log files bao gồm các file rotated.
    Returns list of log files sorted by number (newest first).
    """
    log_files = []
    log_dir = os.path.dirname(base_log_file)
    base_name = os.path.basename(base_log_file)
    
    if not os.path.exists(log_dir):
        return []
    
    for filename in os.listdir(log_dir):
        if filename == base_name or filename.startswith(base_name + '.'):
            full_path = os.path.join(log_dir, filename)
            if os.path.isfile(full_path):
                log_files.append(full_path)
    
    def sort_key(path):
        filename = os.path.basename(path)
        if filename == base_name:
            return -1
        try:
            num = int(filename.split('.')[-1])
            return num
        except ValueError:
            return 999
    
    log_files.sort(key=sort_key)
    return log_files


def parse_login_data_from_logs():
    """
    Parse tất cả log files để lấy thông tin login của guardians.
    
    Returns:
        dict: {guardian_id: {"first_login": datetime, "last_login": datetime, "login_dates": set()}}
    """
    site_path = frappe.get_site_path()
    base_log_file = os.path.join(site_path, 'logs', 'logging.log')
    
    log_files = get_all_log_files(base_log_file)
    
    if not log_files:
        frappe.errprint(f"⚠️ Không tìm thấy log files trong: {os.path.dirname(base_log_file)}")
        return {}
    
    frappe.errprint(f"📂 Tìm thấy {len(log_files)} log files")
    
    # Dict để track login data per guardian
    # Key: guardian_id, Value: {first_login, last_login, login_dates}
    guardian_logins = {}
    
    for log_file in log_files:
        try:
            frappe.errprint(f"📖 Đang đọc: {os.path.basename(log_file)}")
            
            with open(log_file, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        log_entry = json.loads(line.strip())
                        
                        action = log_entry.get('action', '')
                        
                        # Chỉ xử lý OTP login events
                        if action != 'otp_login':
                            continue
                        
                        user = log_entry.get('user', '')
                        timestamp_str = log_entry.get('timestamp', '')
                        
                        # Chỉ xử lý Parent Portal users
                        if '@parent.wellspring.edu.vn' not in user:
                            continue
                        
                        # Parse timestamp
                        try:
                            log_datetime = datetime.strptime(timestamp_str, "%d/%m/%Y %H:%M:%S")
                        except ValueError:
                            continue
                        
                        # Extract guardian_id từ email
                        guardian_id = user.split('@')[0]
                        
                        # Update guardian login data
                        if guardian_id not in guardian_logins:
                            guardian_logins[guardian_id] = {
                                'first_login': log_datetime,
                                'last_login': log_datetime,
                                'login_dates': {log_datetime.date()}
                            }
                        else:
                            # Update first/last login
                            if log_datetime < guardian_logins[guardian_id]['first_login']:
                                guardian_logins[guardian_id]['first_login'] = log_datetime
                            if log_datetime > guardian_logins[guardian_id]['last_login']:
                                guardian_logins[guardian_id]['last_login'] = log_datetime
                            guardian_logins[guardian_id]['login_dates'].add(log_datetime.date())
                            
                    except json.JSONDecodeError:
                        continue
                    except Exception:
                        continue
                        
        except Exception as e:
            frappe.errprint(f"⚠️ Lỗi khi đọc {log_file}: {str(e)}")
            continue
    
    frappe.errprint(f"✅ Tìm thấy {len(guardian_logins)} guardians đã login")
    return guardian_logins


def migrate_guardian_login_data():
    """
    Main migration function.
    Đọc logs và cập nhật first_login_at, last_login_at, portal_activated 
    cho các CRM Guardian đã login.
    
    Sử dụng:
        bench execute erp.api.analytics.migration_guardian_login.migrate_guardian_login_data
    """
    frappe.errprint("🚀 Bắt đầu migration guardian login data...")
    
    # Parse login data từ logs
    guardian_logins = parse_login_data_from_logs()
    
    if not guardian_logins:
        frappe.errprint("⚠️ Không có data để migrate")
        return {"success": False, "message": "No data to migrate"}
    
    updated_count = 0
    activity_count = 0
    errors = []
    
    for guardian_id, login_data in guardian_logins.items():
        try:
            # Tìm CRM Guardian document
            guardian_name = frappe.db.get_value(
                "CRM Guardian",
                {"guardian_id": guardian_id},
                "name"
            )
            
            if not guardian_name:
                errors.append(f"Guardian {guardian_id} không tồn tại trong CRM")
                continue
            
            # Cập nhật CRM Guardian
            guardian = frappe.get_doc("CRM Guardian", guardian_name)
            
            # Chỉ update nếu chưa có first_login_at hoặc data mới sớm hơn
            if not guardian.first_login_at or login_data['first_login'] < guardian.first_login_at:
                guardian.first_login_at = login_data['first_login']
            
            if not guardian.last_login_at or login_data['last_login'] > guardian.last_login_at:
                guardian.last_login_at = login_data['last_login']
            
            guardian.portal_activated = 1
            guardian.save(ignore_permissions=True)
            updated_count += 1
            
            # Tạo Portal Guardian Activity records cho 30 ngày gần nhất
            today_date = datetime.now().date()
            date_30d_ago = today_date - timedelta(days=30)
            
            for login_date in login_data['login_dates']:
                if login_date >= date_30d_ago:
                    # Kiểm tra xem đã có record chưa
                    existing = frappe.db.exists("Portal Guardian Activity", {
                        "guardian": guardian_name,
                        "activity_date": login_date
                    })
                    
                    if not existing:
                        activity_doc = frappe.new_doc("Portal Guardian Activity")
                        activity_doc.guardian = guardian_name
                        activity_doc.activity_date = login_date
                        activity_doc.activity_type = 'otp_login'
                        activity_doc.activity_count = 1
                        activity_doc.last_activity_at = datetime.combine(login_date, datetime.min.time())
                        activity_doc.insert(ignore_permissions=True)
                        activity_count += 1
            
        except Exception as e:
            errors.append(f"Error updating {guardian_id}: {str(e)}")
            continue
    
    frappe.db.commit()
    
    result = {
        "success": True,
        "updated_guardians": updated_count,
        "created_activities": activity_count,
        "errors": errors[:10] if errors else []  # Chỉ trả về 10 errors đầu
    }
    
    frappe.errprint(f"✅ Migration hoàn tất:")
    frappe.errprint(f"   - Cập nhật {updated_count} guardians")
    frappe.errprint(f"   - Tạo {activity_count} activity records")
    if errors:
        frappe.errprint(f"   - {len(errors)} errors")
    
    return result


@frappe.whitelist()
def run_migration():
    """
    API endpoint để chạy migration.
    Có thể gọi từ console hoặc API.
    """
    return migrate_guardian_login_data()
