# Copyright (c) 2026, ERP and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class ERPPurchaseOrder(Document):
    def validate(self):
        self._compute_quote_amounts()
        self._compute_selected_prices()
        self._compute_lines_and_totals()
        self._compute_supplier_totals()
        self._compute_has_substitution()

    def _selected_supplier_name(self):
        idx = self.selected_supplier_idx
        if not idx:
            return None
        for s in self.suppliers or []:
            if s.idx == idx:
                return s.supplier_name
        return None

    def _compute_quote_amounts(self):
        qty_by_item = {l.item: (l.qty or 0) for l in (self.lines or []) if l.item}
        for q in self.quotes or []:
            q.amount = (qty_by_item.get(q.item) or 0) * (q.unit_price_vat or 0)

    def _compute_selected_prices(self):
        sup = self._selected_supplier_name()
        if not sup:
            return
        price_map = {}
        for q in self.quotes or []:
            if q.supplier == sup and q.item:
                price_map[q.item] = q.unit_price_vat
        for l in self.lines or []:
            if l.item in price_map:
                l.selected_unit_price = price_map[l.item]

    def _compute_lines_and_totals(self):
        total = 0
        saving = 0
        for l in self.lines or []:
            l.amount = (l.qty or 0) * (l.selected_unit_price or 0)
            total += l.amount or 0
            pr_unit = self._pr_line_unit_price(l.pr_line)
            if pr_unit is not None:
                saving += (pr_unit - (l.selected_unit_price or 0)) * (l.qty or 0)
        self.total_estimated = total
        self.saving_vs_pr = saving

    def _pr_line_unit_price(self, pr_line):
        if not pr_line:
            return None
        try:
            return frappe.db.get_value("ERP Purchase Request Line", pr_line, "unit_price")
        except Exception:
            return None

    def _compute_supplier_totals(self):
        totals = {}
        for q in self.quotes or []:
            if q.supplier:
                totals[q.supplier] = (totals.get(q.supplier) or 0) + (q.amount or 0)
        for s in self.suppliers or []:
            s.total_amount = totals.get(s.supplier_name) or 0

    def _compute_has_substitution(self):
        self.has_substitution = (
            1 if any((l.line_action == "substitute") for l in (self.lines or [])) else 0
        )
