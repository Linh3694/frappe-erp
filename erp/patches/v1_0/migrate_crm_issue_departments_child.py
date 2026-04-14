# -*- coding: utf-8 -*-
"""CRM Issue: copy department (legacy) sang bang con issue_departments."""

import frappe


def execute():
    """Moi ban ghi co department nhung chua co dong child -> them mot dong."""
    rows = frappe.db.sql(
        """
        SELECT i.name, i.department
        FROM `tabCRM Issue` i
        WHERE IFNULL(i.department, '') != ''
          AND NOT EXISTS (
            SELECT 1 FROM `tabCRM Issue Related Department` r
            WHERE r.parent = i.name AND r.parenttype = 'CRM Issue'
          )
        """,
        as_dict=True,
    )
    for row in rows or []:
        doc = frappe.get_doc("CRM Issue", row.name)
        doc.append("issue_departments", {"department": row.department})
        doc.save(ignore_permissions=True)
    frappe.db.commit()
