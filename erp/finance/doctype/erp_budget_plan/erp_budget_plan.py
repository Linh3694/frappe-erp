# Copyright (c) 2026, ERP and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

# 12 tháng ngân sách theo năm tài chính: T7 năm nay -> T6 năm sau
MONTH_FIELDS = ["m7", "m8", "m9", "m10", "m11", "m12", "m1", "m2", "m3", "m4", "m5", "m6"]


class ERPBudgetPlan(Document):
    def validate(self):
        self._compute_totals()
        self._validate_unique_current()

    def _compute_totals(self):
        # Mỗi dòng: planned_amount = tổng 12 tháng
        for l in self.lines or []:
            l.planned_amount = sum((l.get(m) or 0) for m in MONTH_FIELDS)
        # Header: tổng kế hoạch / đã duyệt từ các dòng
        self.total_planned = sum((l.planned_amount or 0) for l in (self.lines or []))
        self.total_approved = sum((l.approved_amount or 0) for l in (self.lines or []))

    def _validate_unique_current(self):
        # Mỗi phòng chỉ có 1 plan hiện hành (is_current=1) trong 1 kì
        if not self.is_current:
            return
        if not (self.period and self.department):
            return
        existing = frappe.db.get_value(
            "ERP Budget Plan",
            {
                "period": self.period,
                "department": self.department,
                "is_current": 1,
                "name": ("!=", self.name or ""),
            },
            "name",
        )
        if existing:
            frappe.throw(
                _("Phòng ban này đã có bản ngân sách hiện hành trong kì ({0})").format(existing)
            )
