# -*- coding: utf-8 -*-
"""Gop buoc Test va Deal vao QLead: cap nhat du lieu CRM Lead cu."""

import frappe


def execute():
    """Chuyen step Test/Deal sang QLead, map status cu sang test_status/deal_status."""
    _migrate_test_step()
    _migrate_deal_step()
    _normalize_qlead_status()
    frappe.db.commit()


def _migrate_test_step():
    """Test -> QLead: map status -> test_status."""
    mapping = {
        "Pre-test": "Dat lich",
        "Test": "Tham gia",
        "Offered": "De xuat",
        "Failed": "Tu choi",
        "Retake": "Thi lai",
        "Lost": "Tu choi",
    }
    for old_status, test_status in mapping.items():
        names = frappe.get_all(
            "CRM Lead",
            filters={"step": "Test", "status": old_status},
            pluck="name",
        )
        for name in names:
            doc = frappe.get_doc("CRM Lead", name)
            doc.step = "QLead"
            doc.test_status = test_status
            if old_status == "Lost":
                doc.status = "Lost"
            elif doc.status == old_status:
                doc.status = "Dang cham soc"
            doc.save(ignore_permissions=True)

    # Con lai o Test (khong map) -> QLead + giu status tam thoi
    rest = frappe.get_all("CRM Lead", filters={"step": "Test"}, pluck="name")
    for name in rest:
        doc = frappe.get_doc("CRM Lead", name)
        doc.step = "QLead"
        if not doc.test_status:
            doc.test_status = "Tham gia"
        doc.save(ignore_permissions=True)


def _migrate_deal_step():
    """Deal -> QLead: map status -> deal_status."""
    mapping = {
        "Booked": "Dat cho",
        "Deposit": "Dat coc",
        "Lost": "Tu choi",
        "Refund": "Hoan phi",
        "Reserved": "Bao luu/Chuyen",
        "Paid": "Dong phi",
    }
    for old_status, deal_status in mapping.items():
        names = frappe.get_all(
            "CRM Lead",
            filters={"step": "Deal", "status": old_status},
            pluck="name",
        )
        for name in names:
            doc = frappe.get_doc("CRM Lead", name)
            doc.step = "QLead"
            doc.deal_status = deal_status
            if old_status == "Lost":
                doc.status = "Lost"
            elif doc.status == old_status:
                doc.status = "Thoa thuan"
            doc.save(ignore_permissions=True)

    rest = frappe.get_all("CRM Lead", filters={"step": "Deal"}, pluck="name")
    for name in rest:
        doc = frappe.get_doc("CRM Lead", name)
        doc.step = "QLead"
        if not doc.deal_status:
            doc.deal_status = "Dat cho"
        if doc.status not in ("Lost", "Dang cham soc", "Dat lich hen", "Thoa thuan"):
            doc.status = "Thoa thuan"
        doc.save(ignore_permissions=True)


def _normalize_qlead_status():
    """Doi status QLead cu (Follow Up / Event...) sang bo status moi."""
    old_to_new = {
        "Follow Up": "Dang cham soc",
        "Pre-Event": "Dat lich hen",
        "Event": "Dat lich hen",
        "Pre-school Tour/ School Tour": "Dat lich hen",
    }
    for old, new in old_to_new.items():
        frappe.db.sql(
            """
            UPDATE `tabCRM Lead`
            SET status = %(new)s
            WHERE step = 'QLead' AND status = %(old)s
            """,
            {"new": new, "old": old},
        )
