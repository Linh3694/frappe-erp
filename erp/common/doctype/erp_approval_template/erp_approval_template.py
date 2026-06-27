# Copyright (c) 2026, ERP and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class ERPApprovalTemplate(Document):
    def validate(self):
        self._validate_single_active()

    def _validate_single_active(self):
        """Bất biến: tối đa 1 luồng is_active cho mỗi target_doctype."""
        if not self.is_active:
            return
        existing = frappe.db.get_value(
            "ERP Approval Template",
            {
                "target_doctype": self.target_doctype,
                "is_active": 1,
                "name": ("!=", self.name or ""),
            },
            "name",
        )
        if existing:
            frappe.throw(
                _("Đã có luồng đang bật cho {0}: {1}. Hãy tắt nó trước.").format(
                    self.target_doctype, existing
                )
            )
