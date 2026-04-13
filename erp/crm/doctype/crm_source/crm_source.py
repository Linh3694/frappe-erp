# Copyright (c) 2024, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class CRMSource(Document):
    def validate(self):
        # Không trùng tên nguồn con trong cùng một nguồn cha
        seen = set()
        for row in self.sub_sources or []:
            key = (row.sub_source_name or "").strip().lower()
            if not key:
                continue
            if key in seen:
                frappe.throw(_("Tên nguồn con \"{0}\" bị trùng trong danh sách.").format(row.sub_source_name))
            seen.add(key)
