# Copyright (c) 2025, Wellspring International School and contributors
# For license information, please see license.txt

"""
Ghi nhận lỗi kỷ luật - Bản ghi vi phạm hàng ngày
"""

import frappe
from frappe.model.document import Document


class SISDisciplineRecord(Document):
    def validate(self):
        """Validate và set severity_level từ violation"""
        if self.violation:
            severity = frappe.db.get_value(
                "SIS Discipline Violation",
                self.violation,
                "severity_level",
            )
            if severity:
                self.severity_level = str(severity)
