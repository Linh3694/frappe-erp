# Copyright (c) 2024, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class CRMGuardian(Document):
    def before_save(self):
        """Set default values before saving"""
        if not self.relationship:
            self.relationship = "other"
    
    def validate(self):
        """Validate guardian data"""
        if self.key_person and self.parent_account:
            frappe.throw("A guardian cannot be both key person and parent account")
