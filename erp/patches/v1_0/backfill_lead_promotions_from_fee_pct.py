# -*- coding: utf-8 -*-
"""Backfill bảng con CRM Lead Promotion từ 4 field *_fee_pct cũ.

Trước đây mỗi phân loại ưu đãi chỉ lưu được 1 con số % trên CRM Lead. Nay danh
sách ưu đãi của hồ sơ nằm trong bảng con `promotions` (không giới hạn số dòng /
phân loại). Patch suy ngược: với hồ sơ CHƯA có dòng promotions nào, mỗi field
*_fee_pct có giá trị được khớp tới đúng 1 CRM Promotion (cùng phân loại + cùng %)
để tạo dòng tương ứng — đúng như cách FE/BE cũ suy ưu đãi đã gán.

Idempotent: chỉ xử lý hồ sơ đang trống bảng con; KHÔNG đụng tới 4 field *_fee_pct
(các giá trị "mồ côi" không khớp promotion nào giữ nguyên, không bị xoá).
"""

import frappe

CATEGORY_TO_FEE_FIELD = {
    "Học phí": "tuition_fee_pct",
    "Phí dịch vụ": "service_fee_pct",
    "Phí phát triển trường": "dev_fee_pct",
    "Khảo sát đầu vào": "ksdv_pct",
}


def execute():
    try:
        if not frappe.db.exists("DocType", "CRM Lead Promotion"):
            return

        # Lookup CRM Promotion theo (phân loại, %) -> promotion (ưu tiên cái đầu nếu trùng)
        promo_by_cat_val = {}
        for p in frappe.get_all(
            "CRM Promotion",
            fields=["name", "promotion_name", "category", "value"],
            order_by="promotion_name asc",
        ):
            cat = (p.get("category") or "").strip()
            if not cat or p.get("value") is None:
                continue
            try:
                key = (cat, round(float(p["value"]), 6))
            except (TypeError, ValueError):
                continue
            promo_by_cat_val.setdefault(key, p)

        # Hồ sơ đã có dòng promotions -> bỏ qua (idempotent)
        already = set(
            frappe.get_all(
                "CRM Lead Promotion",
                filters={"parenttype": "CRM Lead", "parentfield": "promotions"},
                pluck="parent",
            )
        )

        leads = frappe.get_all(
            "CRM Lead",
            fields=["name"] + list(CATEGORY_TO_FEE_FIELD.values()),
        )
        for lead in leads:
            if lead["name"] in already:
                continue
            idx = 0
            for category, field in CATEGORY_TO_FEE_FIELD.items():
                value = lead.get(field)
                if value is None:
                    continue
                try:
                    fval = float(value)
                except (TypeError, ValueError):
                    continue
                if fval == 0:
                    continue
                promo = promo_by_cat_val.get((category, round(fval, 6)))
                if not promo:
                    continue
                idx += 1
                child = frappe.get_doc(
                    {
                        "doctype": "CRM Lead Promotion",
                        "parenttype": "CRM Lead",
                        "parentfield": "promotions",
                        "parent": lead["name"],
                        "idx": idx,
                        "promotion": promo["name"],
                        "promotion_name": promo.get("promotion_name") or "",
                        "category": category,
                        "value": fval,
                    }
                )
                child.insert(ignore_permissions=True)
        frappe.db.commit()
    except Exception:
        frappe.log_error(title="backfill_lead_promotions_from_fee_pct")
