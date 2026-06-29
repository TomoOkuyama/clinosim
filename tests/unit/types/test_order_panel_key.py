"""Unit tests for Order.panel_key field (PR1 ServiceRequest foundation)."""

from clinosim.types.encounter import Order, OrderType


def test_order_default_panel_key_is_empty():
    """Stand-alone Order defaults to panel_key=''."""
    o = Order(order_id="ORD-1", order_type=OrderType.LAB)
    assert o.panel_key == ""


def test_order_panel_key_settable():
    """Panel Order can be assigned a panel name."""
    o = Order(order_id="ORD-1", order_type=OrderType.LAB, panel_key="CBC")
    assert o.panel_key == "CBC"
