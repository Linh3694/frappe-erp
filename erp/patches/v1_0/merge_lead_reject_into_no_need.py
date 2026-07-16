# -*- coding: utf-8 -*-
"""Buoc Lead: gop 'Tu choi' (va 'Lost' cu) vao 'Khong co nhu cau'.

Sau khi bo 'Tu choi' khoi allow-list buoc Lead, ho so Lead dang 'Tu choi'/'Lost'
se khong hop le -> doi sang 'Khong co nhu cau'. Cac buoc khac giu nguyen.

Idempotent. Chay [post_model_sync], sau merge_deal_status_into_status.
"""

import frappe


def execute():
    frappe.db.sql(
        """
        UPDATE `tabCRM Lead`
        SET `status` = 'Khong co nhu cau'
        WHERE `step` = 'Lead' AND IFNULL(`status`, '') IN ('Tu choi', 'Lost')
        """
    )
    frappe.db.commit()
