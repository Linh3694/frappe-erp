# -*- coding: utf-8 -*-
"""Bo buoc Re-Enroll khoi pipeline CRM: dua ho so ve Enrolled + Dang hoc."""

import frappe


def execute():
    """Cap nhat lead dang o Re-Enroll -> Enrolled, status Dang hoc."""
    frappe.db.sql(
        """
        UPDATE `tabCRM Lead`
        SET `step` = 'Enrolled', `status` = 'Dang hoc'
        WHERE `step` = 'Re-Enroll'
        """
    )
    frappe.db.commit()
