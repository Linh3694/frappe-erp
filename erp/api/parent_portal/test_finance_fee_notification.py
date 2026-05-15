# Copyright (c) 2026, Wellspring and contributors
"""Điều kiện hiển thị Order Student sau khi gửi thông báo phí (SIS Announcement sent)."""

import unittest
from unittest.mock import patch

import frappe


class TestFeeNotificationGate(unittest.TestCase):
    """Có/không có bản ghi Announcement sent cho order_student_id."""

    def test_has_sent_false_when_no_row(self):
        with patch.object(frappe.db, "sql", return_value=[]):
            from erp.api.parent_portal.finance import (
                _has_sent_fee_notification_for_order_student,
            )

            self.assertFalse(
                _has_sent_fee_notification_for_order_student("SIS-FIN-OSTD-00001")
            )

    def test_has_sent_false_when_empty_name(self):
        from erp.api.parent_portal.finance import (
            _has_sent_fee_notification_for_order_student,
        )

        self.assertFalse(_has_sent_fee_notification_for_order_student(None))
        self.assertFalse(_has_sent_fee_notification_for_order_student(""))

    def test_has_sent_true_when_exists(self):
        with patch.object(frappe.db, "sql", return_value=[(1,)]):
            from erp.api.parent_portal.finance import (
                _has_sent_fee_notification_for_order_student,
            )

            self.assertTrue(
                _has_sent_fee_notification_for_order_student("SIS-FIN-OSTD-00001")
            )

    def test_sql_fragment_references_announcement_and_fos(self):
        """Cùng một mẫu EXISTS cho tổng + chi tiết (tránh lệch điều kiện)."""
        from erp.api.parent_portal.finance import (
            _SQL_ORDER_STUDENT_HAS_SENT_FEE_ANNOUNCEMENT,
        )

        s = _SQL_ORDER_STUDENT_HAS_SENT_FEE_ANNOUNCEMENT
        self.assertIn("tabSIS Announcement", s)
        self.assertIn("fee_notification", s)
        self.assertIn("fos.name", s)
