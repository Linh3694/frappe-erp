# Copyright (c) 2025, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class SISDisciplineViolation(Document):
    """Vi phạm kỷ luật - title, classification, mức độ (1, 2, 3)"""

    def on_trash(self):
        # Xóa các phiên bản điểm gắn vi phạm (tránh bản ghi mồ côi)
        if not frappe.db.table_exists("SIS Discipline Violation Point Version"):
            return
        for row in frappe.get_all(
            "SIS Discipline Violation Point Version",
            filters={"violation": self.name},
            pluck="name",
        ):
            frappe.delete_doc("SIS Discipline Violation Point Version", row, force=True)
