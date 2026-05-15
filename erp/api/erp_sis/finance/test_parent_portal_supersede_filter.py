# Copyright (c) 2026, Wellspring and contributors
"""Unit nhẹ: lọc đơn superseded + bypass_supersession (Parent Portal)."""


def _base_row(**kw):
    """Dòng mock tối thiểu cho _filter_orders_for_parent_portal."""
    defaults = {
        "tuition_paid_elsewhere": 0,
        "sort_order": 0,
        "order_creation": "2026-01-01",
        "payment_status": "unpaid",
    }
    defaults.update(kw)
    return defaults


def test_filter_keeps_bypass_superseded():
    from erp.api.parent_portal.finance import _filter_orders_for_parent_portal

    items = [
        _base_row(
            name="hidden",
            is_superseded=1,
            bypass_supersession=0,
            order_type="service",
            paid_amount=0,
            payment_status="unpaid",
        ),
        _base_row(
            name="visible_bypass",
            is_superseded=1,
            bypass_supersession=1,
            order_type="service",
            paid_amount=0,
            payment_status="unpaid",
            order_creation="2026-01-02",
        ),
    ]
    out = _filter_orders_for_parent_portal(items)
    assert len(out) == 1
    assert out[0]["name"] == "visible_bypass"


def test_filter_keeps_non_superseded():
    from erp.api.parent_portal.finance import _filter_orders_for_parent_portal

    items = [
        _base_row(
            name="active",
            is_superseded=0,
            bypass_supersession=0,
            order_type="other",
            paid_amount=0,
            sort_order=1,
            order_creation="2026-01-03",
        ),
    ]
    out = _filter_orders_for_parent_portal(items)
    assert len(out) == 1


def test_filter_keeps_superseded_when_paid_amount_positive():
    from erp.api.parent_portal.finance import _filter_orders_for_parent_portal

    items = [
        _base_row(
            name="superseded_partial",
            is_superseded=1,
            bypass_supersession=0,
            order_type="service",
            paid_amount=1000,
            payment_status="partial",
        ),
    ]
    out = _filter_orders_for_parent_portal(items)
    assert len(out) == 1
    assert out[0]["name"] == "superseded_partial"


def test_filter_keeps_superseded_when_payment_status_paid_despite_zero_paid_amount():
    """Legacy edge: paid_amount = 0 nhưng payment_status vẫn paid."""
    from erp.api.parent_portal.finance import _filter_orders_for_parent_portal

    items = [
        _base_row(
            name="legacy_paid",
            is_superseded=1,
            bypass_supersession=0,
            order_type="service",
            paid_amount=0,
            payment_status="paid",
        ),
    ]
    out = _filter_orders_for_parent_portal(items)
    assert len(out) == 1
    assert out[0]["name"] == "legacy_paid"


def test_filter_keeps_superseded_when_refunded():
    from erp.api.parent_portal.finance import _filter_orders_for_parent_portal

    items = [
        _base_row(
            name="refunded_row",
            is_superseded=1,
            bypass_supersession=0,
            order_type="service",
            paid_amount=0,
            payment_status="refunded",
        ),
    ]
    out = _filter_orders_for_parent_portal(items)
    assert len(out) == 1


def test_filter_drops_superseded_pure_unpaid():
    from erp.api.parent_portal.finance import _filter_orders_for_parent_portal

    items = [
        _base_row(
            name="gone",
            is_superseded=1,
            bypass_supersession=0,
            order_type="tuition",
            paid_amount=0,
            payment_status="unpaid",
        ),
    ]
    assert _filter_orders_for_parent_portal(items) == []


def test_tuition_dedup_prefers_row_with_payment_when_superseded_paid_and_active_unpaid():
    """Một tuition superseded đã thu + một tuition đơn đang hiệu lực chưa đóng → giữ dòng có paid."""
    from erp.api.parent_portal.finance import _filter_orders_for_parent_portal

    items = [
        _base_row(
            name="tuition_active_unpaid",
            is_superseded=0,
            order_type="tuition",
            paid_amount=0,
            payment_status="unpaid",
            sort_order=10,
            order_creation="2026-06-01",
        ),
        _base_row(
            name="tuition_superseded_paid",
            is_superseded=1,
            order_type="tuition",
            paid_amount=120000000,
            payment_status="paid",
            sort_order=5,
            order_creation="2026-05-01",
        ),
    ]
    out = _filter_orders_for_parent_portal(items)
    tuition_out = [x for x in out if x.get("order_type") == "tuition"]
    assert len(tuition_out) == 1
    assert tuition_out[0]["name"] == "tuition_superseded_paid"
