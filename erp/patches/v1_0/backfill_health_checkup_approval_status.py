"""
Gán approval_status = published cho bản ghi khám SK cũ (trước khi có workflow phê duyệt).
"""

import frappe


def execute():
    if not frappe.db.table_exists("tabSIS Student Health Checkup"):
        return
    if not frappe.db.has_column("tabSIS Student Health Checkup", "approval_status"):
        return
    frappe.db.sql(
        """
        UPDATE `tabSIS Student Health Checkup`
        SET `approval_status` = 'published'
        WHERE `approval_status` IS NULL OR `approval_status` = ''
        """
    )
    frappe.db.commit()
