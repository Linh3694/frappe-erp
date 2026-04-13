# -*- coding: utf-8 -*-
"""Gop buoc Withdraw va Graduated thanh Nghi hoc (Tot nghiep / Bao luu / Chuyen truong)."""

import frappe


def execute():
    """Doi step Withdraw, Graduated -> Nghi hoc; giu nguyen status (da hop le)."""
    frappe.db.sql(
        """
        UPDATE `tabCRM Lead`
        SET `step` = 'Nghi hoc'
        WHERE `step` IN ('Withdraw', 'Graduated')
        """
    )
    frappe.db.commit()
