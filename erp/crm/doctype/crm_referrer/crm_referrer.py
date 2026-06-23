# Copyright (c) 2024, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.model.naming import append_number_if_name_exists


class CRMReferrer(Document):
    def autoname(self):
        # Docname uu tien ten nguoi gioi thieu cho de doc/de hien thi (Link tren CRM Lead).
        # Dinh danh duy nhat (staff_code / phone) do logic get-or-create dam nhan, nen cho phep
        # trung ten o cac dinh danh khac nhau bang cach them hau to so (vd "Le", "Le-1").
        base = (
            (self.referrer_name or "").strip()
            or (self.staff_code or "").strip()
            or (self.phone or "").strip()
            or "Referrer"
        )
        self.name = append_number_if_name_exists("CRM Referrer", base)
