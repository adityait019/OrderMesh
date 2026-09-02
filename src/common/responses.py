"""Typed response contracts shared by the A2A agents.

The ``type`` field is the wire-level discriminator used by the current
streaming adapter. ``status`` is intentionally not included here: A2A task
state belongs to the executor, while this payload describes the agent result.
"""

from __future__ import annotations

from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, Field


ResponseType = Literal["completion", "question", "error"]
OperationT = TypeVar("OperationT", bound=str)


class AgentResponse(BaseModel, Generic[OperationT]):
    """Common wire payload returned by every agent."""

    type: ResponseType
    operation: OperationT
    success: bool
    message: str | None = None
    missing: list[str] = Field(default_factory=list)
    error: str | None = None


class OrderItem(BaseModel):
    sku: str
    quantity: int
    unit_price: float | None = None


class OrderData(BaseModel):
    order_id: str | None = None
    customer_id: str | None = None
    items: list[OrderItem] = Field(default_factory=list)
    subtotal: float | None = None
    tax: float | None = None
    total: float | None = None
    order_status: str | None = None
    metadata: dict[str, str | None] = Field(default_factory=dict)


class OrderResponse(
    AgentResponse[Literal["create_order_record", "get_order", "update_order_status", "calculate_totals"]]
):
    data: OrderData | None = None


class InventoryData(BaseModel):
    sku: str | None = None
    quantity_available: int | None = None
    in_stock: bool | None = None
    reservation_id: str | None = None
    quantity_reserved: int | None = None


class InventoryResponse(
    AgentResponse[
        Literal[
            "check_availability",
            "reserve_items",
            "release_reservation",
            "confirm_reservation",
            "find_substitutes",
            "get_inventory_status",
        ]
    ]
):
    data: InventoryData | None = None


class PaymentData(BaseModel):
    order_id: str | None = None
    amount: float | None = None
    payment_status: Literal["authorized", "captured", "refunded", "declined", "failed"] | None = None
    auth_id: str | None = None
    transaction_id: str | None = None
    card_last4: str | None = None


class PaymentResponse(
    AgentResponse[
        Literal[
            "authorize_payment",
            "capture_payment",
            "void_authorization",
            "refund_payment",
            "get_payment_status",
        ]
    ]
):
    data: PaymentData | None = None


class ShippingData(BaseModel):
    order_id: str | None = None
    carrier: str | None = None
    service: str | None = None
    rates: dict[str, float] = Field(default_factory=dict)
    label_id: str | None = None
    tracking_number: str | None = None
    address_valid: bool | None = None


class ShippingResponse(
    AgentResponse[
        Literal[
            "validate_address",
            "get_shipping_rates",
            "create_shipping_label",
            "get_tracking_info",
        ]
    ]
):
    data: ShippingData | None = None


class NotificationData(BaseModel):
    channel: Literal["email", "sms", "push"] | None = None
    recipient: str | None = None
    notification_id: str | None = None
    delivery_status: str | None = None


class NotificationResponse(
    AgentResponse[Literal["send_receipt_email", "send_failure_sms", "send_tracking_update"]]
):
    data: NotificationData | None = None
