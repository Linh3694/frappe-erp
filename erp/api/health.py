# Copyright (c) 2025, Wellspring International School and contributors
# For license information, please see license.txt

"""
Health Report API - Proxy module
Exposes health API at /api/method/erp.api.health.xxx
"""

# Import và re-export tất cả functions từ erp_sis.health
from erp.api.erp_sis.health import (
    get_class_health_reports,
    create_health_report,
    update_health_report,
    delete_health_report,
    get_daily_health_summary,
    get_porridge_list
)

__all__ = [
    'get_class_health_reports',
    'create_health_report',
    'update_health_report',
    'delete_health_report',
    'get_daily_health_summary',
    'get_porridge_list'
]
