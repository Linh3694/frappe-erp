"""
Điều kiện workflow GENERIC: lấy danh sách trường hợp lệ của 1 doctype qua frappe.get_meta,
lọc theo KIỂU TRƯỜNG an toàn (đây là ranh giới bảo mật — whitelist theo fieldtype, không theo tên).
Thay cho CONDITION_WHITELIST cứng trong engine. PR/PO giữ chạy: các field cũ đều thuộc kiểu an toàn.
"""

import frappe

# Kiểu trường được phép dùng trong điều kiện (so sánh giá trị đơn giản).
SAFE_FIELDTYPES = {
    "Data",
    "Select",
    "Int",
    "Float",
    "Currency",
    "Check",
    "Link",
    "Date",
    "Datetime",
    "Percent",
    "Rating",
    "Duration",
    "Small Text",
}

# Field cũ của PR/PO (một số là computed/không nằm trong meta như field thường) — luôn cho phép (phòng thủ).
LEGACY_WHITELIST = {
    "total_estimated",
    "total_qty",
    "request_group",
    "campus_id",
    "budget_in_out",
    "has_substitution",
    "is_urgent",
}

_cache = {}


def _meta_safe_fields(target_doctype):
    """Map fieldname -> field meta cho các field kiểu an toàn của doctype (có cache)."""
    if not target_doctype:
        return {}
    if target_doctype in _cache:
        return _cache[target_doctype]
    out = {}
    try:
        meta = frappe.get_meta(target_doctype)
    except Exception:
        _cache[target_doctype] = out
        return out
    for df in meta.fields:
        if df.fieldtype in SAFE_FIELDTYPES:
            out[df.fieldname] = df
    _cache[target_doctype] = out
    return out


def field_allowed(target_doctype, fieldname):
    """Field có được phép dùng trong điều kiện không."""
    if not fieldname:
        return False
    if fieldname in LEGACY_WHITELIST:
        return True
    return fieldname in _meta_safe_fields(target_doctype)


_LAYOUT_TYPES = {"Section Break", "Column Break", "Tab Break", "HTML", "Heading"}


def all_fields(target_doctype):
    """Mọi field (trừ layout) của doctype — cho picker 'tương đối' chọn field (Link đơn vị/User, bảng con)."""
    if not target_doctype:
        return []
    try:
        meta = frappe.get_meta(target_doctype)
    except Exception:
        return []
    return [
        {"fieldname": d.fieldname, "label": d.label or d.fieldname, "fieldtype": d.fieldtype, "options": d.options or None}
        for d in meta.fields
        if d.fieldtype not in _LAYOUT_TYPES
    ]


def allowed_condition_fields(target_doctype):
    """Danh sách field cho builder chọn: [{fieldname,label,fieldtype,options}]."""
    fields = _meta_safe_fields(target_doctype)
    rows = []
    for fieldname, df in fields.items():
        rows.append(
            {
                "fieldname": fieldname,
                "label": df.label or fieldname,
                "fieldtype": df.fieldtype,
                "options": df.options or None,
            }
        )
    rows.sort(key=lambda r: (r["label"] or "").lower())
    return rows
