# Copyright (c) 2026, Wellspring and contributors
"""Unit nhẹ: lọc đơn superseded + bypass_supersession (Parent Portal)."""


def test_filter_keeps_bypass_superseded():
    from erp.api.parent_portal.finance import _filter_orders_for_parent_portal

    items = [
        {
            "name": "hidden",
            "is_superseded": 1,
            "bypass_supersession": 0,
            "order_type": "service",
            "tuition_paid_elsewhere": 0,
            "paid_amount": 0,
            "sort_order": 0,
            "order_creation": "2026-01-01",
        },
        {
            "name": "visible_bypass",
            "is_superseded": 1,
            "bypass_supersession": 1,
            "order_type": "service",
            "tuition_paid_elsewhere": 0,
            "paid_amount": 0,
            "sort_order": 0,
            "order_creation": "2026-01-02",
        },
    ]
    out = _filter_orders_for_parent_portal(items)
    assert len(out) == 1
    assert out[0]["name"] == "visible_bypass"


def test_filter_keeps_non_superseded():
    from erp.api.parent_portal.finance import _filter_orders_for_parent_portal

    items = [
        {
            "name": "active",
            "is_superseded": 0,
            "bypass_supersession": 0,
            "order_type": "other",
            "tuition_paid_elsewhere": 0,
            "paid_amount": 0,
            "sort_order": 1,
            "order_creation": "2026-01-03",
        },
    ]
    out = _filter_orders_for_parent_portal(items)
    assert len(out) == 1
