# -*- coding: utf-8 -*-
# Copyright (c) 2026, Linh Nguyen and contributors
# For license information, please see license.txt

"""
Portal Guardian Activity
Tracks daily activity of guardians on Parent Portal
"""

from __future__ import unicode_literals
import frappe
from frappe.model.document import Document
from frappe.utils import today, now_datetime


class PortalGuardianActivity(Document):
    pass


def record_guardian_activity(guardian_name, activity_type='api_call'):
    """
    Ghi nhận activity của guardian.
    Nếu đã có record cho ngày hôm nay, tăng activity_count.
    Nếu chưa có, tạo record mới.
    
    Args:
        guardian_name: Tên document CRM Guardian (e.g., "CRM-GUARDIAN-00001")
        activity_type: Loại activity ("otp_login", "app_session", "api_call")
    """
    try:
        frappe.errprint(f"🔵 [Activity] Recording activity for {guardian_name}, type={activity_type}")
        current_date = today()
        frappe.errprint(f"🔵 [Activity] Current date: {current_date}")
        
        # Tìm record hiện có cho guardian + ngày hôm nay
        existing = frappe.db.exists("Portal Guardian Activity", {
            "guardian": guardian_name,
            "activity_date": current_date
        })
        frappe.errprint(f"🔵 [Activity] Existing record: {existing}")
        
        if existing:
            # Cập nhật record hiện có
            doc = frappe.get_doc("Portal Guardian Activity", existing)
            doc.activity_count = (doc.activity_count or 0) + 1
            doc.last_activity_at = now_datetime()
            # Ưu tiên loại activity: otp_login > app_session > api_call
            if activity_type == 'otp_login' or (activity_type == 'app_session' and doc.activity_type != 'otp_login'):
                doc.activity_type = activity_type
            doc.save(ignore_permissions=True)
            frappe.errprint(f"✅ [Activity] Updated existing record: {doc.name}, count={doc.activity_count}")
        else:
            # Tạo record mới
            doc = frappe.new_doc("Portal Guardian Activity")
            doc.guardian = guardian_name
            doc.activity_date = current_date
            doc.activity_type = activity_type
            doc.activity_count = 1
            doc.last_activity_at = now_datetime()
            doc.insert(ignore_permissions=True)
            frappe.errprint(f"✅ [Activity] Created new record: {doc.name}")
        
        frappe.db.commit()
        return True
        
    except Exception as e:
        import traceback
        frappe.errprint(f"❌ [Activity] Error: {str(e)}")
        frappe.errprint(traceback.format_exc())
        frappe.log_error(f"Error recording guardian activity: {str(e)}\n{traceback.format_exc()}", "Portal Guardian Activity")
        return False
