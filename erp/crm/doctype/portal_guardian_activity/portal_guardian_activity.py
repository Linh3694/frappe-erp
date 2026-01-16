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
    Mỗi guardian có thể có nhiều records trong 1 ngày (1 record cho mỗi activity_type).
    
    Args:
        guardian_name: Tên document CRM Guardian (e.g., "CRM-GUARDIAN-00001")
        activity_type: Loại activity ("otp_login", "app_session", hoặc tên module)
    """
    try:
        frappe.errprint(f"🔵 [Activity] Recording activity for {guardian_name}, type={activity_type}")
        current_date = today()
        
        # Tìm record hiện có cho guardian + ngày + activity_type
        existing = frappe.db.sql("""
            SELECT name FROM `tabPortal Guardian Activity`
            WHERE guardian = %s AND activity_date = %s AND activity_type = %s
            LIMIT 1
        """, (guardian_name, current_date, activity_type))
        
        if existing:
            # Cập nhật record hiện có
            frappe.db.sql("""
                UPDATE `tabPortal Guardian Activity`
                SET activity_count = activity_count + 1,
                    last_activity_at = %s
                WHERE name = %s
            """, (now_datetime(), existing[0][0]))
            frappe.errprint(f"✅ [Activity] Updated existing record: {existing[0][0]}")
        else:
            # Tạo record mới
            doc = frappe.new_doc("Portal Guardian Activity")
            doc.guardian = guardian_name
            doc.activity_date = current_date
            doc.activity_type = activity_type
            doc.activity_count = 1
            doc.last_activity_at = now_datetime()
            doc.insert(ignore_permissions=True, ignore_if_duplicate=True)
            frappe.errprint(f"✅ [Activity] Created new record: {doc.name}")
        
        frappe.db.commit()
        return True
        
    except Exception as e:
        import traceback
        frappe.errprint(f"❌ [Activity] Error: {str(e)}")
        frappe.errprint(traceback.format_exc())
        return False
