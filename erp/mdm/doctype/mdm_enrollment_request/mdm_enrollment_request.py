# Copyright (c) 2026, WSHN and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class MDMEnrollmentRequest(Document):
    def validate(self):
        if self.serial_number:
            self.serial_number = self.serial_number.strip()
