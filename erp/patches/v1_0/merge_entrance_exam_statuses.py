# -*- coding: utf-8 -*-
"""KSNL: gop trang thai hoc sinh trong ky khao sat con 3 (Chua thi / Da thi / Khong thi).

- schedule_notified (Thong bao lich thi) -> new (Chua thi)
- completed (Hoan thanh)                 -> exam_taken (Da thi)

Idempotent. Chay [post_model_sync].
"""

import frappe


def execute():
    if not frappe.db.exists("DocType", "CRM Admission Entrance Exam Student"):
        return
    frappe.db.sql(
        "UPDATE `tabCRM Admission Entrance Exam Student` SET `status` = 'new' WHERE `status` = 'schedule_notified'"
    )
    frappe.db.sql(
        "UPDATE `tabCRM Admission Entrance Exam Student` SET `status` = 'exam_taken' WHERE `status` = 'completed'"
    )
    frappe.db.commit()
