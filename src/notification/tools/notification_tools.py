"""
Notification Agent Tools - Template compilation and multi-channel dispatch.
"""

from __future__ import annotations
import uuid
import logging
from datetime import datetime
from agents import function_tool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# =====================================================================
# Tool Input Models
# =====================================================================

class ReceiptData(BaseModel):
    """Data required to compile a receipt email."""

    customer_name: str = Field(description="Customer's display name")
    order_id: str = Field(description="Order ID the receipt refers to")
    total: float = Field(description="Final order total", ge=0)
    currency: str = Field(default="USD", description="Currency code")


class FailureData(BaseModel):
    """Data required to compile a failure/alert SMS."""

    customer_name: str = Field(description="Customer's display name")
    reference_id: str = Field(description="Order or payment ID related to the failure")
    reason: str = Field(description="Short human-readable failure reason")


class TrackingData(BaseModel):
    """Data required to compile a tracking update."""

    customer_name: str = Field(description="Customer's display name")
    order_id: str = Field(description="Order ID being shipped")
    carrier: str = Field(description="Carrier name, e.g. FedEx, UPS")
    tracking_number: str = Field(description="Carrier tracking number")
    status: str = Field(
        default="shipped",
        description="Shipment status: shipped, in_transit, or delivered",
    )


# =====================================================================
# Mock Template Compiler
# =====================================================================

class TemplateCompiler:
    """Mock template compiler that populates data tags into message bodies."""

    TEMPLATES = {
        "receipt_email": (
            "Hi {customer_name},\n\n"
            "Thanks for your order! Your order {order_id} has been confirmed.\n"
            "Total charged: {currency} {total:.2f}\n\n"
            "We'll notify you again once it ships."
        ),
        "failure_sms": (
            "Hi {customer_name}, we had an issue with {reference_id}: {reason}. "
            "Please check your account or contact support."
        ),
        "tracking_update": (
            "Hi {customer_name}, your order {order_id} is {status}. "
            "Carrier: {carrier}, Tracking #: {tracking_number}."
        ),
    }

    @classmethod
    def compile(cls, template_name: str, **data) -> str:
        """Populate a named template with the given data tags."""
        template = cls.TEMPLATES.get(template_name)
        if not template:
            raise ValueError(f"Unknown template: {template_name}")
        return template.format(**data)


# =====================================================================
# Mock Dispatchers
# =====================================================================

class EmailDispatcherMock:
    """Mock email dispatcher that logs the email output to console."""

    @staticmethod
    def send(to: str, subject: str, body: str) -> dict:
        message_id = f"EMAIL-{uuid.uuid4().hex[:10].upper()}"
        logger.info(
            "[EmailDispatcherMock] to=%s subject=%s message_id=%s\n%s",
            to, subject, message_id, body,
        )
        return {
            "message_id": message_id,
            "to": to,
            "subject": subject,
            "sent_at": datetime.now().isoformat(),
            "status": "sent",
        }


class SMSServiceSimulator:
    """Mock SMS service that logs the SMS payload to console."""

    @staticmethod
    def send(to: str, body: str) -> dict:
        message_id = f"SMS-{uuid.uuid4().hex[:10].upper()}"
        logger.info(
            "[SMSServiceSimulator] to=%s message_id=%s body=%s",
            to, message_id, body,
        )
        return {
            "message_id": message_id,
            "to": to,
            "sent_at": datetime.now().isoformat(),
            "status": "sent",
        }


# =====================================================================
# Global Mock Instances
# =====================================================================

email_dispatcher = EmailDispatcherMock()
sms_service = SMSServiceSimulator()
template_compiler = TemplateCompiler()


# =====================================================================
# Tool Registration for OpenAI Agents SDK
# =====================================================================

@function_tool
def send_receipt_email(
    recipient_email: str,
    receipt: ReceiptData,
) -> dict:
    """
    Compile and send an order/payment receipt email to the customer.

    Args:
        recipient_email: Customer's email address.
        receipt: Receipt data — customer name, order ID, total, currency.

    Returns:
        Dispatch result with message ID and status.
    """
    if not recipient_email or "@" not in recipient_email:
        return {
            "success": False,
            "error": f"Invalid recipient email: {recipient_email!r}",
        }

    body = template_compiler.compile(
        "receipt_email",
        customer_name=receipt.customer_name,
        order_id=receipt.order_id,
        total=receipt.total,
        currency=receipt.currency,
    )

    result = email_dispatcher.send(
        to=recipient_email,
        subject=f"Your receipt for order {receipt.order_id}",
        body=body,
    )

    return {
        "success": True,
        "channel": "email",
        "message_id": result["message_id"],
        "order_id": receipt.order_id,
        "message": f"Receipt email sent to {recipient_email} for order {receipt.order_id}",
    }


@function_tool
def send_failure_sms(
    recipient_phone: str,
    failure: FailureData,
) -> dict:
    """
    Compile and send a short failure/alert SMS (e.g. payment declined, item unavailable).

    Args:
        recipient_phone: Customer's phone number.
        failure: Failure data — customer name, reference ID, reason.

    Returns:
        Dispatch result with message ID and status.
    """
    if not recipient_phone:
        return {
            "success": False,
            "error": "recipient_phone is required",
        }

    body = template_compiler.compile(
        "failure_sms",
        customer_name=failure.customer_name,
        reference_id=failure.reference_id,
        reason=failure.reason,
    )

    result = sms_service.send(to=recipient_phone, body=body)

    return {
        "success": True,
        "channel": "sms",
        "message_id": result["message_id"],
        "reference_id": failure.reference_id,
        "message": f"Failure SMS sent to {recipient_phone} for {failure.reference_id}",
    }


@function_tool
def send_tracking_update(
    order_id: str,
    tracking: TrackingData,
    channel: str = "email",
    recipient_email: str | None = None,
    recipient_phone: str | None = None,
) -> dict:
    """
    Compile and send a shipment tracking update via email or SMS.

    Args:
        order_id: Order ID the update refers to (must match tracking.order_id).
        tracking: Tracking data — customer name, order ID, carrier, tracking number, status.
        channel: Delivery channel, "email" or "sms". Defaults to "email".
        recipient_email: Required when channel is "email".
        recipient_phone: Required when channel is "sms".

    Returns:
        Dispatch result with message ID and status.
    """
    valid_channels = ("email", "sms")
    if channel not in valid_channels:
        return {
            "success": False,
            "error": f"Invalid channel '{channel}'. Valid: {valid_channels}",
        }

    if order_id != tracking.order_id:
        return {
            "success": False,
            "error": "order_id does not match tracking.order_id",
        }

    body = template_compiler.compile(
        "tracking_update",
        customer_name=tracking.customer_name,
        order_id=tracking.order_id,
        carrier=tracking.carrier,
        tracking_number=tracking.tracking_number,
        status=tracking.status,
    )

    if channel == "email":
        if not recipient_email or "@" not in recipient_email:
            return {
                "success": False,
                "error": f"Invalid recipient_email for email channel: {recipient_email!r}",
            }
        result = email_dispatcher.send(
            to=recipient_email,
            subject=f"Tracking update for order {order_id}",
            body=body,
        )
        recipient = recipient_email
    else:
        if not recipient_phone:
            return {
                "success": False,
                "error": "recipient_phone is required for sms channel",
            }
        result = sms_service.send(to=recipient_phone, body=body)
        recipient = recipient_phone

    return {
        "success": True,
        "channel": channel,
        "message_id": result["message_id"],
        "order_id": order_id,
        "message": f"Tracking update ({tracking.status}) sent to {recipient} for order {order_id}",
    }


# List of all tools for agent registration
all_tools = [
    send_receipt_email,
    send_failure_sms,
    send_tracking_update,
]