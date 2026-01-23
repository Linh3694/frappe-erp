# -*- coding: utf-8 -*-
"""
Report Card Form APIs
=====================

DEPRECATED: File này được giữ lại để backward compatible.
Code thực tế đã được move vào package erp.api.erp_sis.report_card/form.py

Tất cả imports và API paths cũ vẫn hoạt động bình thường.
"""

# Re-export tất cả APIs từ package mới
from erp.api.erp_sis.report_card.form import (
    get_all_forms,
    get_form_by_id,
    create_form,
    update_form,
    delete_form,
    ensure_default_forms,
    ensure_intl_forms,
)

# Export cho backward compatibility
__all__ = [
    "get_all_forms",
    "get_form_by_id",
    "create_form",
    "update_form",
    "delete_form",
    "ensure_default_forms",
    "ensure_intl_forms",
]
