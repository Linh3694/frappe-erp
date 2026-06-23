# -*- coding: utf-8 -*-
"""Thêm index phục vụ truy vấn báo cáo CRM (Lead + Step History). Idempotent."""

import frappe


def _add_index_if_missing(table: str, index_name: str, columns_sql: str) -> None:
    if not frappe.db.table_exists(table):
        return
    existing = frappe.db.sql(
        f"SHOW INDEX FROM `{table}` WHERE Key_name = %s",
        (index_name,),
    )
    if existing:
        return
    frappe.db.sql(f"ALTER TABLE `{table}` ADD INDEX `{index_name}` ({columns_sql})")


def execute():
    # CRM Lead — lọc theo kỳ + chiều
    _add_index_if_missing(
        "tabCRM Lead",
        "crm_lead_report_creation",
        "`creation`, `campus_id`, `pic`, `target_academic_year`, `target_grade`",
    )
    _add_index_if_missing(
        "tabCRM Lead",
        "crm_lead_report_step_status",
        "`step`, `status`",
    )
    _add_index_if_missing(
        "tabCRM Lead",
        "crm_lead_report_enrollment_date",
        "`enrollment_date`",
    )

    # CRM Lead Step History — sự kiện theo ngày
    _add_index_if_missing(
        "tabCRM Lead Step History",
        "crm_lead_hist_report_event",
        "`changed_at`, `new_step`, `new_status`",
    )
    _add_index_if_missing(
        "tabCRM Lead Step History",
        "crm_lead_hist_report_lead",
        "`lead`, `new_step`",
    )
