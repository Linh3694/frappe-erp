# Copyright (c) 2026, ERP and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import add_days, getdate


class ERPPurchaseRequest(Document):
    def validate(self):
        self._compute_leadtime()
        self._compute_lines()
        self._compute_budget_flags()

    def _compute_leadtime(self):
        if self.request_date and self.lead_time_days:
            self.leadtime_date = add_days(getdate(self.request_date), int(self.lead_time_days or 0))

    def _compute_lines(self):
        total = 0
        for l in self.lines or []:
            l.amount = (l.qty_to_buy or 0) * (l.unit_price or 0)
            total += l.amount or 0
        self.total_estimated = total

    def _compute_budget_flags(self):
        """budget_in_out = rollup từ lines.in_budget (OUT nếu có dòng ngoài NS)."""
        any_out = False
        has_line = False
        for l in self.lines or []:
            has_line = True
            in_b = _line_in_budget(self.routing_unit, l.line_budget_code)
            l.in_budget = 1 if in_b else 0
            if not in_b:
                any_out = True
        self.budget_in_out = ("Out" if any_out else "In") if has_line else None


def _line_in_budget(routing_unit, budget_code):
    """Dòng có thuộc ngân sách đã duyệt (Approved/Active, is_current) của routing_unit không."""
    if not (routing_unit and budget_code):
        return False
    try:
        plans = frappe.get_all(
            "ERP Budget Plan",
            filters={
                "department": routing_unit,
                "is_current": 1,
                "workflow_state": ("in", ("Approved", "Active")),
            },
            pluck="name",
        )
        if not plans:
            return False
        rows = frappe.get_all(
            "ERP Budget Plan Line",
            filters={"parent": ("in", plans), "budget_code": budget_code},
            limit=1,
        )
        return bool(rows)
    except Exception:
        return False
