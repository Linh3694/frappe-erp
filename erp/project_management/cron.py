# Copyright (c) 2024, Wellspring and contributors
# For license information, please see license.txt

"""
Cron jobs cho Project Management module
"""

import frappe
from datetime import datetime


def expire_pending_invitations():
    """
    Tự động chuyển trạng thái các invitation quá hạn thành 'expired'
    Chạy hàng ngày lúc 00:00
    
    Kiểm tra các invitation có:
    - status = 'pending'
    - expires_at < now
    
    Và set status = 'expired'
    """
    try:
        expired_count = frappe.db.sql("""
            UPDATE `tabPM Project Invitation`
            SET status = 'expired', modified = NOW()
            WHERE status = 'pending'
            AND expires_at < NOW()
        """)
        
        frappe.db.commit()
        
        # Log số lượng invitation đã expire
        affected_rows = frappe.db.sql("""
            SELECT ROW_COUNT() as count
        """, as_dict=True)
        
        if affected_rows and affected_rows[0].get('count', 0) > 0:
            frappe.logger().info(
                f"Project Management: Expired {affected_rows[0].count} pending invitations"
            )
            
    except Exception as e:
        frappe.log_error(
            f"Error expiring pending invitations: {str(e)}",
            "PM Cron: expire_pending_invitations"
        )

