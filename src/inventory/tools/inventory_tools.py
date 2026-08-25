"""
Inventory Agent Tools - Handles stock verification, reservations, and substitutions.
"""

from __future__ import annotations
import uuid
from datetime import datetime, timedelta
from agents import function_tool
from agents.decorators import tool
from pydantic import BaseModel, Field

# =====================================================================
# Tool Input Models
# =====================================================================

class ReservationItem(BaseModel):
    """A single reservation item."""

    sku: str = Field(description="Product SKU (e.g., SKU-001)")
    quantity: int = Field(description="Quantity to reserve", ge=1)


# =====================================================================
# Mock Stock Database
# =====================================================================

class StockDBMock:
    """Mock in-memory stock database with toggleable quantities."""
    
    # Default catalog with initial stock
    DEFAULT_CATALOG = {
        "SKU-001": {"name": "Wireless Headphones", "quantity": 50, "price": 79.99},
        "SKU-002": {"name": "USB-C Cable", "quantity": 200, "price": 9.99},
        "SKU-003": {"name": "Phone Case", "quantity": 120, "price": 14.99},
        "SKU-004": {"name": "Screen Protector", "quantity": 0, "price": 4.99},  # Out of stock
        "SKU-005": {"name": "Laptop Stand", "quantity": 30, "price": 34.99},
    }
    
    def __init__(self):
        self.stock = dict(self.DEFAULT_CATALOG)
        self.reservations = {}  # reservation_id -> reservation_data
    
    def check_stock(self, sku: str) -> dict | None:
        """Check stock level for a SKU."""
        if sku not in self.stock:
            return None
        item = self.stock[sku]
        return {
            "sku": sku,
            "name": item["name"],
            "quantity": item["quantity"],
            "price": item["price"],
            "in_stock": item["quantity"] > 0,
        }
    
    def reserve_stock(self, sku: str, quantity: int) -> dict:
        """
        Reserve stock temporarily.
        Returns reservation ID if successful, error otherwise.
        """
        if sku not in self.stock:
            return {"success": False, "error": f"SKU {sku} not found"}
        
        item = self.stock[sku]
        if item["quantity"] < quantity:
            return {
                "success": False,
                "error": f"Insufficient stock for {sku}. Available: {item['quantity']}, Requested: {quantity}",
            }
        
        reservation_id = f"RES-{uuid.uuid4().hex[:8].upper()}"
        expiry = (datetime.now() + timedelta(minutes=15)).isoformat()
        
        self.reservations[reservation_id] = {
            "reservation_id": reservation_id,
            "sku": sku,
            "quantity": quantity,
            "created_at": datetime.now().isoformat(),
            "expires_at": expiry,
            "status": "active",
        }
        
        # Decrement stock temporarily
        item["quantity"] -= quantity
        
        return {
            "success": True,
            "reservation_id": reservation_id,
            "sku": sku,
            "quantity": quantity,
            "expires_at": expiry,
            "remaining_stock": item["quantity"],
        }
    
    def release_reservation(self, reservation_id: str) -> dict:
        """Release a reservation and restore stock."""
        if reservation_id not in self.reservations:
            return {"success": False, "error": f"Reservation {reservation_id} not found"}
        
        res = self.reservations[reservation_id]
        if res["status"] != "active":
            return {"success": False, "error": f"Reservation {reservation_id} is not active"}
        
        sku = res["sku"]
        quantity = res["quantity"]
        
        # Restore stock
        self.stock[sku]["quantity"] += quantity
        
        # Mark as released
        res["status"] = "released"
        res["released_at"] = datetime.now().isoformat()
        
        return {
            "success": True,
            "reservation_id": reservation_id,
            "sku": sku,
            "quantity_restored": quantity,
            "restored_stock": self.stock[sku]["quantity"],
        }
    
    def get_all_skus(self) -> list[dict]:
        """Get all SKUs in catalog."""
        return [
            {
                "sku": sku,
                "name": item["name"],
                "quantity": item["quantity"],
                "price": item["price"],
                "in_stock": item["quantity"] > 0,
            }
            for sku, item in self.stock.items()
        ]
    
    def confirm_reservation(self, reservation_id: str) -> dict:
        """Confirm a reservation (marks as consumed)."""
        if reservation_id not in self.reservations:
            return {"success": False, "error": f"Reservation {reservation_id} not found"}
        
        res = self.reservations[reservation_id]
        if res["status"] != "active":
            return {"success": False, "error": f"Reservation {reservation_id} is not active"}
        
        res["status"] = "confirmed"
        res["confirmed_at"] = datetime.now().isoformat()
        
        return {
            "success": True,
            "reservation_id": reservation_id,
            "status": "confirmed",
            "message": f"Reservation {reservation_id} confirmed",
        }


class AlternativeSKUFinder:
    """Mock product substitution engine."""
    
    # Substitution mappings: sku -> list of alternative skus
    SUBSTITUTIONS = {
        "SKU-001": ["SKU-003", "SKU-005"],  # Headphones -> alternatives
        "SKU-002": ["SKU-005"],              # Cable -> alternatives
        "SKU-003": ["SKU-001"],              # Case -> alternatives
        "SKU-004": ["SKU-002"],              # Protector -> alternatives
        "SKU-005": ["SKU-001", "SKU-003"],  # Stand -> alternatives
    }
    
    def __init__(self, stock_db: StockDBMock):
        self.stock_db = stock_db
    
    def find_substitutes(self, sku: str) -> list[dict]:
        """
        Find available substitute products for a given SKU.
        Returns only in-stock alternatives.
        """
        if sku not in self.SUBSTITUTIONS:
            return []
        
        alternatives = []
        for alt_sku in self.SUBSTITUTIONS[sku]:
            stock_info = self.stock_db.check_stock(alt_sku)
            if stock_info and stock_info["in_stock"]:
                alternatives.append(stock_info)
        
        return alternatives


# =====================================================================
# Global Mock Instances
# =====================================================================

stock_db = StockDBMock()
substitute_finder = AlternativeSKUFinder(stock_db)


# =====================================================================
# Tool Registration for OpenAI Agents SDK
# =====================================================================

@tool
def check_availability(sku: str) -> dict:
    """
    Check if a SKU is available and get current stock level.

    Args:
        sku: SKU identifier (e.g., SKU-001).

    Returns:
        Stock information including quantity, price, and availability status.
    """
    info = stock_db.check_stock(sku)
    if not info:
        return {"success": False, "error": f"SKU {sku} not found in catalog"}
    
    return {
        "success": True,
        "sku": info["sku"],
        "name": info["name"],
        "quantity_available": info["quantity"],
        "price": info["price"],
        "in_stock": info["in_stock"],
        "status": "available" if info["in_stock"] else "out_of_stock",
    }


@tool
def reserve_items(
    sku: str,
    quantity: int,
) -> dict:
    """
    Reserve items temporarily with a 15-minute hold.

    Args:
        sku: SKU to reserve.
        quantity: Number of units to reserve (must be positive).

    Returns:
        Reservation ID if successful, error otherwise.
    """
    if quantity <= 0:
        return {"success": False, "error": "Quantity must be positive"}
    
    result = stock_db.reserve_stock(sku, quantity)
    
    if result["success"]:
        return {
            "success": True,
            "reservation_id": result["reservation_id"],
            "sku": sku,
            "quantity_reserved": quantity,
            "expires_at": result["expires_at"],
            "message": f"Reserved {quantity} units of {sku}. Hold expires in 15 minutes.",
        }
    
    return result


@tool
def find_substitutes(sku: str) -> dict:
    """
    Find available substitute products when stock is zero.

    Args:
        sku: SKU that is out of stock or needs alternatives.

    Returns:
        List of in-stock alternatives with details.
    """
    # First check if original SKU exists
    original = stock_db.check_stock(sku)
    if not original:
        return {"success": False, "error": f"SKU {sku} not found"}
    
    alternatives = substitute_finder.find_substitutes(sku)
    
    if not alternatives:
        return {
            "success": True,
            "sku": sku,
            "original_name": original["name"],
            "substitutes": [],
            "message": f"No suitable substitutes found for {sku}",
        }
    
    return {
        "success": True,
        "sku": sku,
        "original_name": original["name"],
        "substitutes": alternatives,
        "message": f"Found {len(alternatives)} substitute(s) for {sku}",
    }


@tool
def get_inventory_status() -> dict:
    """
    Get comprehensive inventory status across all SKUs.

    Returns:
        List of all products with current stock levels and statistics.
    """
    all_skus = stock_db.get_all_skus()
    in_stock_count = sum(1 for item in all_skus if item["in_stock"])
    out_of_stock_count = len(all_skus) - in_stock_count
    total_units = sum(item["quantity"] for item in all_skus)
    
    return {
        "success": True,
        "total_skus": len(all_skus),
        "in_stock": in_stock_count,
        "out_of_stock": out_of_stock_count,
        "total_units": total_units,
        "catalog": all_skus,
    }


@tool
def release_reservation(reservation_id: str) -> dict:
    """
    Release a reservation and restore stock to inventory.

    Args:
        reservation_id: Reservation ID to release.

    Returns:
        Confirmation of stock restoration.
    """
    result = stock_db.release_reservation(reservation_id)
    
    if result["success"]:
        return {
            "success": True,
            "reservation_id": reservation_id,
            "sku": result["sku"],
            "quantity_released": result["quantity_restored"],
            "message": f"Reservation {reservation_id} released. Stock restored.",
        }
    
    return result


@tool
def confirm_reservation(reservation_id: str) -> dict:
    """
    Confirm a reservation (marks as consumed/committed).

    Args:
        reservation_id: Reservation ID to confirm.

    Returns:
        Confirmation of reservation status change.
    """
    result = stock_db.confirm_reservation(reservation_id)
    
    if result["success"]:
        return {
            "success": True,
            "reservation_id": reservation_id,
            "message": f"Reservation {reservation_id} confirmed and locked for fulfillment",
        }
    
    return result


# List of all tools for agent registration
all_tools = [
    check_availability,
    reserve_items,
    find_substitutes,
    get_inventory_status,
    release_reservation,
    confirm_reservation,
]