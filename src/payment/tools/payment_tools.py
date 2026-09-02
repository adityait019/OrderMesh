"""
Payment Agent Tools - Handles card authorizations, payment tokens, and transaction reversals.
"""

from __future__ import annotations
import uuid
from datetime import datetime, timedelta
from agents import function_tool
from pydantic import BaseModel, Field
from enum import Enum


# =====================================================================
# Enums
# =====================================================================

class PaymentStatus(str, Enum):
    """Payment status enumeration."""
    PENDING = "pending"
    AUTHORIZED = "authorized"
    CAPTURED = "captured"
    DECLINED = "declined"
    VOIDED = "voided"
    REFUNDED = "refunded"
    FAILED = "failed"


class CardType(str, Enum):
    """Card type enumeration."""
    VISA = "visa"
    MASTERCARD = "mastercard"
    AMEX = "amex"
    DISCOVER = "discover"


# =====================================================================
# Tool Input Models
# =====================================================================

class PaymentToken(BaseModel):
    """Safe payment reference accepted by the agent boundary."""

    payment_token: str = Field(description="Tokenized payment reference; never a card number")
    card_last4: str | None = Field(default=None, description="Optional four-digit display suffix")


class BillingAddress(BaseModel):
    """Billing address for payment."""

    street: str = Field(description="Street address")
    city: str = Field(description="City")
    state_province: str = Field(description="State or province")
    postal_code: str = Field(description="Postal code")
    country: str = Field(description="Country code (e.g., US, CA)")


# =====================================================================
# Mock Payment Gateway
# =====================================================================

class StripeGatewayMock:
    """Mock Stripe payment gateway."""
    
    # Simulate declined cards
    DECLINED_PATTERNS = ["4000000000000002", "5555555555554444"]
    
    def __init__(self):
        self.transactions = {}  # transaction_id -> transaction_data
        self.authorizations = {}  # auth_id -> authorization_data
    
    def authorize_payment(
        self,
        order_id: str,
        amount: float,
        currency: str,
        card: dict,
        billing_address: dict | None = None,
    ) -> dict:
        """
        Authorize a card payment.
        Returns auth ID if approved, error if declined.
        """
        # Simulate card validation
        card_number = card.get("card_number", "")
        
        # Check if card matches declined pattern
        if any(card_number.endswith(pattern) for pattern in self.DECLINED_PATTERNS):
            return {
                "success": False,
                "status": PaymentStatus.DECLINED.value,
                "error": "Card declined by issuer",
                "error_code": "card_declined",
            }
        
        # Simulate expiry check
        expiry_year = card.get("expiry_year", 0)
        expiry_month = card.get("expiry_month", 0)
        now = datetime.now()
        
        if expiry_year < now.year or (expiry_year == now.year and expiry_month < now.month):
            return {
                "success": False,
                "status": PaymentStatus.DECLINED.value,
                "error": "Card expired",
                "error_code": "card_expired",
            }
        
        # Create authorization
        auth_id = f"AUTH-{uuid.uuid4().hex[:12].upper()}"
        auth_code = f"{uuid.uuid4().hex[:6].upper()}"
        
        self.authorizations[auth_id] = {
            "auth_id": auth_id,
            "auth_code": auth_code,
            "order_id": order_id,
            "amount": amount,
            "currency": currency,
            "card_last4": card_number[-4:],
            "card_type": card.get("card_type"),
            "cardholder_name": card.get("cardholder_name"),
            "status": PaymentStatus.AUTHORIZED.value,
            "created_at": datetime.now().isoformat(),
            "expires_at": (datetime.now() + timedelta(days=7)).isoformat(),
        }
        
        return {
            "success": True,
            "status": PaymentStatus.AUTHORIZED.value,
            "auth_id": auth_id,
            "auth_code": auth_code,
            "order_id": order_id,
            "amount": amount,
            "currency": currency,
            "card_last4": card_number[-4:],
            "message": f"Payment authorized: ${amount:.2f} {currency}",
        }
    
    def capture_payment(self, auth_id: str) -> dict:
        """
        Capture an authorized payment (actually charge the card).
        """
        if auth_id not in self.authorizations:
            return {"success": False, "error": f"Authorization {auth_id} not found"}
        
        auth = self.authorizations[auth_id]
        
        if auth["status"] != PaymentStatus.AUTHORIZED.value:
            return {
                "success": False,
                "error": f"Authorization is in {auth['status']} status, cannot capture",
            }
        
        # Create transaction
        transaction_id = f"TXN-{uuid.uuid4().hex[:12].upper()}"
        
        self.transactions[transaction_id] = {
            "transaction_id": transaction_id,
            "auth_id": auth_id,
            "order_id": auth["order_id"],
            "amount": auth["amount"],
            "currency": auth["currency"],
            "status": PaymentStatus.CAPTURED.value,
            "created_at": datetime.now().isoformat(),
        }
        
        # Update authorization status
        auth["status"] = PaymentStatus.CAPTURED.value
        auth["captured_at"] = datetime.now().isoformat()
        
        return {
            "success": True,
            "status": PaymentStatus.CAPTURED.value,
            "transaction_id": transaction_id,
            "auth_id": auth_id,
            "order_id": auth["order_id"],
            "amount": auth["amount"],
            "currency": auth["currency"],
            "message": f"Payment captured: ${auth['amount']:.2f} {auth['currency']}",
        }
    
    def void_authorization(self, auth_id: str) -> dict:
        """
        Void an authorization (cancel without charging).
        """
        if auth_id not in self.authorizations:
            return {"success": False, "error": f"Authorization {auth_id} not found"}
        
        auth = self.authorizations[auth_id]
        
        if auth["status"] != PaymentStatus.AUTHORIZED.value:
            return {
                "success": False,
                "error": f"Can only void authorized payments, current status: {auth['status']}",
            }
        
        auth["status"] = PaymentStatus.VOIDED.value
        auth["voided_at"] = datetime.now().isoformat()
        
        return {
            "success": True,
            "status": PaymentStatus.VOIDED.value,
            "auth_id": auth_id,
            "order_id": auth["order_id"],
            "amount": auth["amount"],
            "message": f"Authorization voided: ${auth['amount']:.2f} hold released",
        }
    
    def refund_payment(self, transaction_id: str, amount: float | None = None) -> dict:
        """
        Refund a captured payment (full or partial).
        """
        if transaction_id not in self.transactions:
            return {"success": False, "error": f"Transaction {transaction_id} not found"}
        
        txn = self.transactions[transaction_id]
        refund_amount = amount or txn["amount"]
        
        if refund_amount > txn["amount"]:
            return {
                "success": False,
                "error": f"Refund amount (${refund_amount:.2f}) exceeds transaction amount (${txn['amount']:.2f})",
            }
        
        if txn["status"] != PaymentStatus.CAPTURED.value:
            return {
                "success": False,
                "error": f"Can only refund captured payments, current status: {txn['status']}",
            }
        
        refund_id = f"REF-{uuid.uuid4().hex[:12].upper()}"
        
        # Update transaction status
        if refund_amount == txn["amount"]:
            txn["status"] = PaymentStatus.REFUNDED.value
        else:
            txn["status"] = "partially_refunded"
        
        txn["refund_id"] = refund_id
        txn["refunded_at"] = datetime.now().isoformat()
        
        return {
            "success": True,
            "status": PaymentStatus.REFUNDED.value,
            "refund_id": refund_id,
            "transaction_id": transaction_id,
            "refund_amount": refund_amount,
            "currency": txn["currency"],
            "message": f"Refund processed: ${refund_amount:.2f} {txn['currency']}",
        }
    
    def get_authorization(self, auth_id: str) -> dict | None:
        """Retrieve authorization details."""
        return self.authorizations.get(auth_id)
    
    def get_transaction(self, transaction_id: str) -> dict | None:
        """Retrieve transaction details."""
        return self.transactions.get(transaction_id)


class AuthTokenGenerator:
    """Generate authentication tokens for transactions."""
    
    @staticmethod
    def generate_token() -> str:
        """Generate a unique payment token."""
        return f"tok_{uuid.uuid4().hex[:24].upper()}"
    
    @staticmethod
    def generate_customer_token(card_last4: str) -> str:
        """Generate a customer/card token for future use."""
        return f"cus_{card_last4}_{uuid.uuid4().hex[:8].upper()}"


# =====================================================================
# Global Mock Instances
# =====================================================================

stripe_gateway = StripeGatewayMock()
token_generator = AuthTokenGenerator()


# =====================================================================
# Tool Registration for OpenAI Agents SDK
# =====================================================================

@function_tool
def authorize_payment(
    order_id: str,
    amount: float,
    currency: str = "USD",
    payment_token: str = "",
    card_last4: str = "",
    card_type: str = "visa",
    cardholder_name: str = "",
    street: str = "",
    city: str = "",
    state_province: str = "",
    postal_code: str = "",
    country: str = "US",
) -> dict:
    """
    Authorize a credit card payment.

    Args:
        order_id: Order ID to charge for.
        amount: Payment amount.
        currency: Currency code (default: USD).
        payment_token: Tokenized payment reference. Never pass raw card data.
        card_last4: Optional last four digits for display and mock processing.
        card_type: Card type (visa, mastercard, amex, discover).
        cardholder_name: Name on card.
        street: Billing street address.
        city: Billing city.
        state_province: Billing state/province.
        postal_code: Billing postal code.
        country: Billing country code.

    Returns:
        Authorization ID if approved, error if declined.
    """
    if amount <= 0:
        return {"success": False, "error": "Amount must be positive"}

    if not payment_token:
        return {"success": False, "error": "A tokenized payment_token is required"}

    if card_last4 and (len(card_last4) != 4 or not card_last4.isdigit()):
        return {"success": False, "error": "card_last4 must contain exactly four digits"}
    
    card = {
        # The mock gateway only needs a display-safe suffix. Never send PAN/CVV.
        "card_number": card_last4,
        "card_type": card_type,
        "expiry_month": datetime.now().month,
        "expiry_year": datetime.now().year,
        "cardholder_name": cardholder_name,
        "payment_token": payment_token,
    }
    
    billing_address = {
        "street": street,
        "city": city,
        "state_province": state_province,
        "postal_code": postal_code,
        "country": country,
    } if any([street, city, postal_code]) else None
    
    return stripe_gateway.authorize_payment(
        order_id=order_id,
        amount=amount,
        currency=currency,
        card=card,
        billing_address=billing_address,
    )


@function_tool
def capture_payment(auth_id: str) -> dict:
    """
    Capture an authorized payment (charge the card).

    Args:
        auth_id: Authorization ID to capture.

    Returns:
        Transaction ID if successful, error if capture fails.
    """
    if not auth_id or not auth_id.strip():
        return {
            "success": False,
            "error": "auth_id is required from a successful authorize_payment result",
            "error_code": "missing_auth_id",
        }

    result = stripe_gateway.capture_payment(auth_id)
    
    if result["success"]:
        # Generate payment token
        result["payment_token"] = token_generator.generate_token()
    
    return result


@function_tool
def void_authorization(auth_id: str) -> dict:
    """
    Void an authorization (cancel without charging).

    Args:
        auth_id: Authorization ID to void.

    Returns:
        Confirmation of void, error if unable to void.
    """
    return stripe_gateway.void_authorization(auth_id)


@function_tool
def refund_payment(
    transaction_id: str,
    amount: float | None = None,
) -> dict:
    """
    Refund a captured payment (full or partial refund).

    Args:
        transaction_id: Transaction ID to refund.
        amount: Refund amount (default: full refund).

    Returns:
        Refund ID if successful, error if refund fails.
    """
    if amount is not None and amount <= 0:
        return {"success": False, "error": "Refund amount must be positive"}
    
    return stripe_gateway.refund_payment(transaction_id, amount)


@function_tool
def get_payment_status(auth_id: str = "", transaction_id: str = "") -> dict:
    """
    Get payment status for an authorization or transaction.

    Args:
        auth_id: Authorization ID (check authorization status).
        transaction_id: Transaction ID (check transaction status).

    Returns:
        Payment status and details.
    """
    if auth_id:
        auth = stripe_gateway.get_authorization(auth_id)
        if not auth:
            return {"success": False, "error": f"Authorization {auth_id} not found"}
        return {
            "success": True,
            "type": "authorization",
            "auth_id": auth_id,
            "status": auth["status"],
            "amount": auth["amount"],
            "currency": auth["currency"],
            "created_at": auth["created_at"],
            "order_id": auth["order_id"],
        }
    
    if transaction_id:
        txn = stripe_gateway.get_transaction(transaction_id)
        if not txn:
            return {"success": False, "error": f"Transaction {transaction_id} not found"}
        return {
            "success": True,
            "type": "transaction",
            "transaction_id": transaction_id,
            "status": txn["status"],
            "amount": txn["amount"],
            "currency": txn["currency"],
            "created_at": txn["created_at"],
            "order_id": txn["order_id"],
        }
    
    return {"success": False, "error": "Either auth_id or transaction_id must be provided"}


# List of all tools for agent registration
all_tools = [
    authorize_payment,
    capture_payment,
    void_authorization,
    refund_payment,
    get_payment_status,
]
