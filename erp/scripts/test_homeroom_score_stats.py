#!/usr/bin/env python3
"""
Script test API get_homeroom_score_stats.
Chạy: bench --site [site] execute erp.scripts.test_homeroom_score_stats.test
"""
import frappe


def test(class_id="SIS-CLASS-10421", year=2026, month=3):
    """Gọi get_homeroom_score_stats để debug lỗi 500"""
    try:
        from erp.api.erp_sis.homeroom_score import get_homeroom_score_stats

        result = get_homeroom_score_stats(
            class_id=class_id,
            year=year,
            month=month,
        )
        print("Result:", frappe.as_json(result, indent=2))
        return result
    except Exception as e:
        import traceback

        print("ERROR:", str(e))
        traceback.print_exc()
        raise
