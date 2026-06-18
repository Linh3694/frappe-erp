# Copyright (c) 2026, ERP and contributors
# Mã ngân sách — cây phân cấp (NestedSet) tối đa 4 cấp; level tự tính theo số cấp trên.

import frappe
from frappe import _
from frappe.utils.nestedset import NestedSet

MAX_LEVEL = 4
CODE_DT = "ERP Budget Code"


def sync_is_group_for_code(name):
    """Có mã con → nhóm; không có → lá. Gọi sau save/delete để đồng bộ parent."""
    if not name:
        return
    has_child = frappe.db.exists(CODE_DT, {"parent_budget_code": name})
    frappe.db.set_value(
        CODE_DT,
        name,
        "is_group",
        1 if has_child else 0,
        update_modified=False,
    )


class ERPBudgetCode(NestedSet):
    nsm_parent_field = "parent_budget_code"

    def validate(self):
        self._validate_unique_code()
        self._validate_not_own_parent()
        self._set_level()
        if self.level and self.level > MAX_LEVEL:
            frappe.throw(
                _("Mã ngân sách tối đa {0} cấp (mã này đang ở cấp {1})").format(MAX_LEVEL, self.level)
            )
        # Tự suy luận is_group theo số mã con (không tin client)
        if self.name:
            self.is_group = 1 if frappe.db.exists(CODE_DT, {"parent_budget_code": self.name}) else 0
        else:
            self.is_group = 0

    def _validate_unique_code(self):
        # Mã ngân sách dùng chung toàn trường -> duy nhất toàn hệ thống
        if self.budget_code:
            existing = frappe.db.get_value(
                "ERP Budget Code",
                {
                    "budget_code": self.budget_code,
                    "name": ("!=", self.name or ""),
                },
                "name",
            )
            if existing:
                frappe.throw(
                    _("Mã ngân sách '{0}' đã tồn tại").format(self.budget_code)
                )

    def _validate_not_own_parent(self):
        if self.parent_budget_code and self.parent_budget_code == self.name:
            frappe.throw(_("Mã ngân sách không thể là cấp trên của chính nó"))

    def _set_level(self):
        """level = số cấp trên + 1. Không parent -> 1, có 1 parent -> 2, ..."""
        level = 1
        parent = self.parent_budget_code
        seen = {self.name} if self.name else set()
        while parent:
            if parent in seen:  # chống vòng lặp
                frappe.throw(_("Phát hiện vòng lặp trong cây mã ngân sách"))
            seen.add(parent)
            level += 1
            if level > MAX_LEVEL + 1:  # vượt xa giới hạn -> dừng để báo lỗi ở validate
                break
            parent = frappe.db.get_value("ERP Budget Code", parent, "parent_budget_code")
        self.level = level

    def on_update(self):
        old_doc = self.get_doc_before_save()
        old_parent = old_doc.parent_budget_code if old_doc else None

        # NestedSet duy trì lft/rgt
        super().on_update()
        # Nếu đổi cấp trên -> cập nhật lại level cho toàn bộ con cháu
        if self.has_value_changed("parent_budget_code"):
            self._resync_descendant_levels(self.name, self.level or 1)

        sync_is_group_for_code(self.name)
        if old_parent and old_parent != self.parent_budget_code:
            sync_is_group_for_code(old_parent)
        if self.parent_budget_code:
            sync_is_group_for_code(self.parent_budget_code)

    def after_delete(self):
        if self.parent_budget_code:
            sync_is_group_for_code(self.parent_budget_code)

    def _resync_descendant_levels(self, parent_name, parent_level):
        children = frappe.get_all(
            "ERP Budget Code", filters={"parent_budget_code": parent_name}, pluck="name"
        )
        for child in children:
            child_level = parent_level + 1
            if child_level > MAX_LEVEL:
                frappe.throw(
                    _("Di chuyển làm mã con vượt quá {0} cấp — không cho phép").format(MAX_LEVEL)
                )
            frappe.db.set_value(
                "ERP Budget Code", child, "level", child_level, update_modified=False
            )
            self._resync_descendant_levels(child, child_level)
