# Copyright (c) 2024, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class CRMIssue(Document):
    def has_permission(self, ptype, user=None, *args, **kwargs):
        """
        Doc lap: doc + tao cho moi user dang nhap (API create_issue / SIS); xoa chi SM / SIS Sales Admin.
        Sua (write): None — dung Role Permission trong crm_issue.json.
        """
        if not user:
            user = frappe.session.user
        if user == "Guest":
            return False
        if ptype == "read":
            return True
        # Tao issue: moi user da login (dong bo mo hinh API — khong bat buoc role CRM tren DocType)
        if ptype == "create":
            return True
        if ptype == "delete":
            roles = frappe.get_roles(user)
            return "System Manager" in roles or "SIS Sales Admin" in roles
        return None
