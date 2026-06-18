# Copyright (c) 2026, ERP and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class ERPBudgetCode(Document):
    def validate(self):
        # Mã ngân sách phải duy nhất trong cùng campus
        if self.budget_code and self.campus_id:
            existing = frappe.db.get_value(
                "ERP Budget Code",
                {
                    "budget_code": self.budget_code,
                    "campus_id": self.campus_id,
                    "name": ("!=", self.name or ""),
                },
                "name",
            )
            if existing:
                frappe.throw(
                    _("Mã ngân sách '{0}' đã tồn tại trong campus này").format(self.budget_code)
                )
