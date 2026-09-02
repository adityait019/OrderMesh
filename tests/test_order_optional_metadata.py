"""Order input contract tests."""

from src.order.agent.order_agent import _validate_order_parameters


def test_create_order_does_not_require_optional_metadata() -> None:
    request = {
        "customer_id": "CUST-90412",
        "items": [{"sku": "SKU-001", "quantity": 2, "unit_price": 25.0}],
    }

    valid, error = _validate_order_parameters(request)

    assert valid is True
    assert error is None
