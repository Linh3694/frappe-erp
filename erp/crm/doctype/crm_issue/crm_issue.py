# Copyright (c) 2024, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class CRMIssue(Document):
    def has_permission(self, ptype, user=None, *args, **kwargs):
        """
        Doc lap: doc + tao cho moi user dang nhap (API create_issue / SIS); xoa chi SM / SIS Sales Admin.
        Sua (write): None — dung Role Permission trong crm_issue.json.

        LUU Y: phai ton trong self.flags.ignore_permissions, neu khong API goi save(ignore_permissions=True)
        (vd approve_issue / reject_issue / update) van bi PermissionError vi ptype='write' tra None
        va check_permission coi not None == True.
        """
        # Ton trong co bo qua quyen (API-level da kiem tra _can_approve / _can_write_issue_ops truoc khi save)
        if getattr(self, "flags", None) and self.flags.ignore_permissions:
            return True
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
        # Sua/write va cac ptype khac: fallback Role Permission trong crm_issue.json qua Document.has_permission.
        # KHONG tra None — check_permission dung `not self.has_permission(...)` nen None bi coi la deny.
        try:
            return super().has_permission(ptype, user=user)
        except TypeError:
            # Mot so override cu khong nhan user kwarg — thu khong kwarg
            return super().has_permission(ptype)
