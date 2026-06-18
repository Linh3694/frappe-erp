# Copyright (c) 2026, ERP and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class SISBudgetAdjustment(Document):
    def validate(self):
        self.total_delta = sum((l.delta_amount or 0) for l in (self.lines or []))
        # Transfer phải cân bằng: tổng các delta = 0
        if self.type == "Transfer" and self.lines:
            if round(self.total_delta, 2) != 0:
                frappe.throw(_("Điều chuyển (Transfer) phải cân bằng: tổng các delta = 0"))
