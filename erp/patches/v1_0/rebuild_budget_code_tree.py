"""Khởi tạo cây cho ERP Budget Code sau khi chuyển sang NestedSet.

Chạy post_model_sync (sau khi các field lft/rgt/parent_budget_code đã tồn tại):
- rebuild_tree -> điền lft/rgt cho mọi dòng hiện có.
- Tính lại level theo số cấp trên (không parent = 1, ...).
"""

import frappe
from frappe.utils.nestedset import rebuild_tree


def execute():
    if not frappe.db.table_exists("ERP Budget Code"):
        return

    # Điền lft/rgt theo quan hệ parent_budget_code
    rebuild_tree("ERP Budget Code", "parent_budget_code")

    # Tính lại level cho mọi dòng
    rows = frappe.get_all("ERP Budget Code", fields=["name", "parent_budget_code"])
    parent_map = {r.name: r.parent_budget_code for r in rows}

    def depth(name, _seen=None):
        _seen = _seen or set()
        level = 1
        p = parent_map.get(name)
        while p and p not in _seen:
            _seen.add(p)
            level += 1
            p = parent_map.get(p)
        return level

    for r in rows:
        frappe.db.set_value(
            "ERP Budget Code", r.name, "level", depth(r.name), update_modified=False
        )

    frappe.db.commit()
