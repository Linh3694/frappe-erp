# Copyright (c) 2024, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class CRMGuardian(Document):
    def before_save(self):
        """Set default values before saving"""
        # Chỉ set relationship nếu field tồn tại
        if hasattr(self, 'relationship') and not self.relationship:
            self.relationship = "other"
    
    def validate(self):
        """Validate guardian data"""
        # Chỉ validate nếu các fields tồn tại
        key_person = getattr(self, 'key_person', None)
        parent_account = getattr(self, 'parent_account', None)
        if key_person and parent_account:
            frappe.throw("A guardian cannot be both key person and parent account")
