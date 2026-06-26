# Copyright (c) 2026, WSHN and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class FaceIDDevice(Document):
    def validate(self):
        # IP không được trống
        if not self.ip:
            frappe.throw("IP thiết bị là bắt buộc")
