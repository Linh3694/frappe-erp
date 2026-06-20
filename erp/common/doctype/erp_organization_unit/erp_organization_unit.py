# Copyright (c) 2026, Wellspring International School and contributors
# Đơn vị tổ chức — cây phân cấp (NestedSet) cho Sơ đồ tổ chức

import frappe
from frappe import _
from frappe.utils.nestedset import NestedSet


class ERPOrganizationUnit(NestedSet):
    nsm_parent_field = "parent_organization_unit"

    def validate(self):
        self.validate_not_own_parent()
        self.validate_type_top_down()
        self.validate_members_unique()

    def validate_not_own_parent(self):
        if self.parent_organization_unit and self.parent_organization_unit == self.name:
            frappe.throw(_("Đơn vị không thể là cấp trên của chính nó"))

    def validate_type_top_down(self):
        """Loại của cấp trên phải có 'order' nhỏ hơn loại của đơn vị hiện tại.
        Dấu < (chặt) vừa chặn lộn ngược, vừa tự động chống trùng loại trên cùng nhánh.
        Cho phép nhảy cấp (không bắt liền kề)."""
        if not self.parent_organization_unit or not self.unit_type:
            return
        parent_type = frappe.db.get_value(
            "ERP Organization Unit", self.parent_organization_unit, "unit_type"
        )
        if not parent_type:
            return
        self._assert_type_order(parent_type, self.unit_type)

    @staticmethod
    def _assert_type_order(parent_type: str, child_type: str):
        parent_order = frappe.db.get_value("ERP Organization Unit Type", parent_type, "type_order")
        child_order = frappe.db.get_value("ERP Organization Unit Type", child_type, "type_order")
        if parent_order is None or child_order is None:
            return
        if int(parent_order) >= int(child_order):
            frappe.throw(
                _(
                    "Loại đơn vị cấp dưới ({0}) phải có thứ tự cấp lớn hơn loại của cấp trên ({1})"
                ).format(child_type, parent_type)
            )

    def validate_members_unique(self):
        """Leaders và members không trùng nhau trong cùng đơn vị.
        Một người có thể là lãnh đạo/thành viên của nhiều đơn vị khác nhau."""
        leader_users = [row.user for row in (self.leaders or []) if row.user]
        member_users = [row.user for row in (self.members or []) if row.user]

        # Trùng trong cùng đơn vị (giữa leaders và members, hoặc lặp trong 1 bảng)
        seen = set()
        for user in leader_users + member_users:
            if user in seen:
                frappe.throw(
                    _("Người dùng {0} bị lặp trong đơn vị (leaders/members)").format(user)
                )
            seen.add(user)

    def on_trash(self):
        # Chặn xóa khi còn thành viên/lãnh đạo
        if (self.leaders or []) or (self.members or []):
            frappe.throw(_("Không thể xóa đơn vị còn lãnh đạo/thành viên. Hãy gỡ trước."))
        # NestedSet.on_trash tự chặn khi còn đơn vị con
        super().on_trash()
