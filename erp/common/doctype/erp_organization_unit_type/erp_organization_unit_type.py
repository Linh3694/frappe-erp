# Copyright (c) 2026, Wellspring International School and contributors
# Loại đơn vị tổ chức (Division/Department/Section/Unit...) — danh mục linh hoạt

import frappe
from frappe import _
from frappe.model.document import Document


class ERPOrganizationUnitType(Document):
    def validate(self):
        # Thứ tự cấp bắt buộc là số dương để luật top-down hoạt động đúng
        if self.type_order is None or int(self.type_order) <= 0:
            frappe.throw(_("Thứ tự cấp phải là số nguyên dương"))
