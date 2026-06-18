# Copyright (c) 2026, ERP and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class ERPBudgetPeriod(Document):
    def validate(self):
        # Mỗi năm học chỉ có đúng 1 kì ngân sách
        if self.school_year_id:
            existing = frappe.db.exists(
                "ERP Budget Period",
                {"school_year_id": self.school_year_id, "name": ("!=", self.name)},
            )
            if existing:
                frappe.throw(_("Năm học này đã có kì ngân sách: {0}").format(existing))
