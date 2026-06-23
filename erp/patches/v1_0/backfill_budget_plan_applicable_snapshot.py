# -*- coding: utf-8 -*-
"""Backfill snapshot mã áp dụng cho các bản ngân sách cũ — TỪ DÒNG (lines), KHÔNG từ master.

Trước đây danh sách mã áp dụng được suy ra live từ master toàn cục, nên sửa master
lọt vào cả bản đang duyệt. Nay mỗi bản giữ snapshot riêng. Với bản cũ chưa có snapshot,
chốt snapshot = các mã của chính bản đó (dòng không bị gạch bỏ) — phản ánh đúng nội dung
đã lập/đã duyệt. Idempotent: chỉ xử lý bản đang trống snapshot.
"""

import json

import frappe


def execute():
    try:
        if not frappe.db.has_column("ERP Budget Plan", "applicable_snapshot"):
            return
        names = frappe.get_all(
            "ERP Budget Plan",
            filters={"applicable_snapshot": ("in", ["", None])},
            pluck="name",
        )
        for name in names:
            doc = frappe.get_doc("ERP Budget Plan", name)
            codes = [
                l.budget_code
                for l in (doc.lines or [])
                if l.budget_code and not l.get("is_removed")
            ]
            frappe.db.set_value(
                "ERP Budget Plan",
                name,
                "applicable_snapshot",
                json.dumps(codes),
                update_modified=False,
            )
    except Exception:
        frappe.log_error(title="backfill_budget_plan_applicable_snapshot")
