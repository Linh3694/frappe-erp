# Copyright (c) 2024, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class CRMIssue(Document):
    def has_permission(self, ptype, user=None, *args, **kwargs):
        """
        Doc lap: doc cho moi user dang nhap; xoa chi SM / SIS Sales Admin.
        Ghi/tao: dung quyen Role trong DocType (permissions JSON).
        """
        if not user:
            user = frappe.session.user
        if user == "Guest":
            return False
        if ptype == "read":
            return True
        if ptype == "delete":
            roles = frappe.get_roles(user)
            return "System Manager" in roles or "SIS Sales Admin" in roles
        return None
