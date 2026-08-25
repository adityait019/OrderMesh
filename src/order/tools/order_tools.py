"""
Order Agent Tools - Handles order creation, calculations, and state management.
"""

from __future__ import annotations
import uuid
from datetime import datetime
from agents import function_tool
from pydantic import BaseModel, Field

# =====================================================================
# Tool Input Models
# =====================================================================

class OrderItem(BaseModel):
    """A single order line item."""

    sku: str = Field(description="Product SKU")
    quantity: int = Field(description="Quantity of the product", ge=1)
    unit_price: float = Field(description="Unit price of the product", ge=0)


class OrderMetadata(BaseModel):
    """Optional order metadata."""

    notes: str | None = Field(default=None, description="Optional order notes")
    promo_code: str | None = Field(default=None, description="Optional promo code")


# =====================================================================
# Mock Order Store (In-Memory State)
# =====================================================================

class OrderStoreMock:
    """Mock in-memory order database."""
    
    def __init__(self):
        self.orders = {}  # order_id -> order_data
    
    def create_order(self, customer_id: str, order_data: dict) -> str:
        """Create new order and return order_id."""
        order_id = f"ORD-{uuid.uuid4().hex[:8].upper()}"
        self.orders[order_id] = {
            "order_id": order_id,
            "customer_id": customer_id,
            "status": "created",
            "created_at": datetime.now().isoformat(),
            "items": order_data.get("items", []),
            "subtotal": 0.0,
            "tax": 0.0,
            "discount": 0.0,
            "total": 0.0,
            "payment_status": "pending",
            "shipping_status": "pending",
            "metadata": order_data.get("metadata", {}),
        }
        return order_id
    
    def get_order(self, order_id: str) -> dict | None:
        """Retrieve order by ID."""
        return self.orders.get(order_id)
    
    def update_order(self, order_id: str, updates: dict) -> bool:
        """Update order fields."""
        if order_id not in self.orders:
            return False
        self.orders[order_id].update(updates)
        return True
    
    def get_all_orders(self) -> list[dict]:
        """Return all orders."""
        return list(self.orders.values())


class TaxAndDiscountEngine:
    """Mock tax and discount calculator."""
    
    TAX_RATE = 0.10  # 10% tax
    
    @staticmethod
    def calculate_line_items(items: list[dict]) -> dict:
        """
        Calculate line-item subtotals.
        
        items: [{"sku": "ABC123", "quantity": 2, "unit_price": 29.99}, ...]
        """
        subtotal = 0.0
        calculated_items = []
        
        for item in items:
            qty = item.get("quantity", 1)
            price = item.get("unit_price", 0.0)
            line_total = qty * price
            subtotal += line_total
            
            calculated_items.append({
                "sku": item.get("sku"),
                "quantity": qty,
                "unit_price": price,
                "line_total": round(line_total, 2),
            })
        
        return {
            "items": calculated_items,
            "subtotal": round(subtotal, 2),
        }
    
    @staticmethod
    def calculate_totals(subtotal: float, discount_percent: float = 0.0) -> dict:
        """Calculate tax and final total."""
        discount = round(subtotal * (discount_percent / 100), 2)
        taxable = subtotal - discount
        tax = round(taxable * TaxAndDiscountEngine.TAX_RATE, 2)
        total = subtotal - discount + tax
        
        return {
            "subtotal": round(subtotal, 2),
            "discount": discount,
            "discount_percent": discount_percent,
            "tax": tax,
            "tax_rate": TaxAndDiscountEngine.TAX_RATE,
            "total": round(total, 2),
        }


# =====================================================================
# Global Mock Instances
# =====================================================================

order_store = OrderStoreMock()
tax_engine = TaxAndDiscountEngine()


# =====================================================================
# Tool Registration for OpenAI Agents SDK
# =====================================================================

@function_tool
def create_order_record(
    customer_id: str,
    items: list[OrderItem],
    metadata: OrderMetadata | None = None,
) -> dict:
    """
    Create a new order record with customer ID and line items.

    Args:
        customer_id: Customer identifier.
        items: Order line items. Each item contains sku, quantity,
            and unit_price.
        metadata: Optional metadata such as notes or promo codes.

    Returns:
        Order object with ID and initial state.
    """
    item_dicts = [item.model_dump() for item in items]
    metadata_dict = metadata.model_dump(exclude_none=True) if metadata else {}

    order_id = order_store.create_order(
        customer_id,
        {
            "items": item_dicts,
            "metadata": metadata_dict,
        },
    )

    order = order_store.get_order(order_id)

    return {
        "success": True,
        "order_id": order_id,
        "customer_id": customer_id,
        "status": "created",
        "items": item_dicts,
        "created_at": order.get("created_at") if order else None,
        "message": f"Order {order_id} created successfully",
    }


@function_tool
def calculate_totals(
    order_id: str,
    discount_percent: float = 0.0,
) -> dict:
    """
    Calculate line-item subtotals, taxes, and final order total.

    Args:
        order_id: Order ID to calculate totals for.
        discount_percent: Optional discount percentage from 0 to 100.

    Returns:
        Calculation breakdown with subtotal, tax, discount, and total.
    """
    order = order_store.get_order(order_id)

    if not order:
        return {
            "success": False,
            "error": f"Order {order_id} not found",
        }

    if not 0 <= discount_percent <= 100:
        return {
            "success": False,
            "error": "discount_percent must be between 0 and 100",
        }

    line_calc = tax_engine.calculate_line_items(order["items"])

    total_calc = tax_engine.calculate_totals(
        line_calc["subtotal"],
        discount_percent,
    )

    order_store.update_order(
        order_id,
        {
            "items": line_calc["items"],
            "subtotal": total_calc["subtotal"],
            "tax": total_calc["tax"],
            "discount": total_calc["discount"],
            "total": total_calc["total"],
            "discount_percent": discount_percent,
        },
    )

    return {
        "success": True,
        "order_id": order_id,
        "calculation": total_calc,
        "message": f"Totals calculated: ${total_calc['total']:.2f}",
    }


@function_tool
def update_order_status(
    order_id: str,
    status: str,
    substatus: str | None = None,
) -> dict:
    """
    Update the order lifecycle status.

    Args:
        order_id: Order ID.
        status: New order status.
        substatus: Optional sub-status for additional context.

    Returns:
        Updated order status.
    """
    order = order_store.get_order(order_id)

    if not order:
        return {
            "success": False,
            "error": f"Order {order_id} not found",
        }

    valid_statuses = [
        "created",
        "confirmed",
        "payment_pending",
        "payment_complete",
        "preparing",
        "shipped",
        "delivered",
        "cancelled",
    ]

    if status not in valid_statuses:
        return {
            "success": False,
            "error": (
                f"Invalid status '{status}'. "
                f"Valid: {valid_statuses}"
            ),
        }

    updates = {"status": status}

    if substatus is not None:
        updates["substatus"] = substatus

    order_store.update_order(order_id, updates)

    updated = order_store.get_order(order_id) or {}

    return {
        "success": True,
        "order_id": order_id,
        "status": updated.get("status"),
        "substatus": updated.get("substatus"),
        "updated_at": datetime.now().isoformat(),
        "message": f"Order {order_id} status updated to {status}",
    }


# List of all tools for agent registration
all_tools = [
    create_order_record,
    calculate_totals,
    update_order_status,
]