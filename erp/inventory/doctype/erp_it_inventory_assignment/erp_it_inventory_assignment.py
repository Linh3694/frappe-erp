# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class ERPITInventoryAssignment(Document):
    def validate(self):
        if self.user:
            # Auto-populate user name and job title
            user_doc = frappe.get_doc("User", self.user)
            self.user_name = user_doc.full_name
            # Assuming job title is stored in User doctype
            # Adjust field name as per your User doctype structure
            if hasattr(user_doc, 'job_title'):
                self.job_title = user_doc.job_title