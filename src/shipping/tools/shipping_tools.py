"""
Shipping Agent Tools - Handles carrier rates, shipping labels, and tracking.
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

class ShippingService(str, Enum):
    """Shipping service types."""
    STANDARD = "standard"
    EXPRESS = "express"
    OVERNIGHT = "overnight"
    INTERNATIONAL = "international"


class CarrierType(str, Enum):
    """Carrier types."""
    FEDEX = "fedex"
    UPS = "ups"
    USPS = "usps"
    DHL = "dhl"


# =====================================================================
# Tool Input Models
# =====================================================================

class ShippingAddress(BaseModel):
    """Shipping address for label generation."""

    street: str = Field(description="Street address")
    city: str = Field(description="City")
    state_province: str = Field(description="State or province")
    postal_code: str = Field(description="Postal code")
    country: str = Field(description="Country code (e.g., US, CA)")
    phone: str = Field(description="Recipient phone number")


class ShipmentItem(BaseModel):
    """Item in shipment."""

    sku: str = Field(description="Product SKU")
    quantity: int = Field(description="Quantity", ge=1)
    weight_oz: float = Field(description="Weight in ounces", ge=0.1)


# =====================================================================
# Mock Carrier Rate Calculator
# =====================================================================

class CarrierRateCalculator:
    """Mock carrier rate calculation engine."""
    
    # Base rates per service (for domestic US)
    BASE_RATES = {
        ShippingService.STANDARD: 5.99,
        ShippingService.EXPRESS: 12.99,
        ShippingService.OVERNIGHT: 24.99,
        ShippingService.INTERNATIONAL: 35.00,
    }
    
    # Weight multiplier (per oz)
    WEIGHT_MULTIPLIER = 0.05
    
    # Zone multipliers (distance-based)
    ZONE_MULTIPLIERS = {
        1: 1.0,    # Same state
        2: 1.15,   # Adjacent states
        3: 1.35,   # 500+ miles
        4: 1.65,   # 1000+ miles (coast to coast)
    }
    
    # Carrier surcharges
    CARRIER_SURCHARGE = {
        CarrierType.FEDEX: 0.0,      # baseline
        CarrierType.UPS: 0.05,       # 5% surcharge
        CarrierType.USPS: -0.10,     # 10% discount
        CarrierType.DHL: 0.08,       # 8% surcharge
    }
    
    @staticmethod
    def calculate_weight(items: list[dict]) -> float:
        """Calculate total shipment weight."""
        return sum(item.get("weight_oz", 0) for item in items)
    
    @staticmethod
    def get_shipping_zone(origin_zip: str, dest_zip: str) -> int:
        """
        Mock zone calculation based on zip codes.
        In production, would use real distance matrix.
        """
        # Simple mock: compare first digit
        origin_region = int(origin_zip[0]) if origin_zip else 0
        dest_region = int(dest_zip[0]) if dest_zip else 0
        distance = abs(origin_region - dest_region)
        
        if distance == 0:
            return 1
        elif distance <= 1:
            return 2
        elif distance <= 3:
            return 3
        else:
            return 4
    
    @classmethod
    def get_rates(
        cls,
        items: list[dict],
        origin_zip: str,
        dest_zip: str,
        carrier: str | CarrierType = CarrierType.USPS.value,
    ) -> dict:
        """
        Calculate shipping rates for all services.
        
        Returns dict with rates per service.
        """
        total_weight = cls.calculate_weight(items)
        zone = cls.get_shipping_zone(origin_zip, dest_zip)
        zone_multiplier = cls.ZONE_MULTIPLIERS.get(zone, 1.0)
        carrier_key = CarrierType(carrier) if isinstance(carrier, str) else carrier
        carrier_surcharge = cls.CARRIER_SURCHARGE.get(carrier_key, 0.0)
        
        rates = {}
        for service, base_rate in cls.BASE_RATES.items():
            # Calculate: base rate + weight adjustment + zone adjustment + carrier surcharge
            weight_cost = total_weight * cls.WEIGHT_MULTIPLIER
            rate = base_rate + weight_cost
            rate = rate * zone_multiplier
            rate = rate * (1 + carrier_surcharge)
            rates[service.value] = round(rate, 2)
        
        return {
            "carrier": carrier_key.value,
            "total_weight_oz": round(total_weight, 2),
            "zone": zone,
            "rates": rates,
            "currency": "USD",
        }


class TrackingNumGenerator:
    """Generate tracking numbers and labels."""
    
    @staticmethod
    def generate_tracking_number(carrier: str) -> str:
        """Generate realistic tracking number for carrier."""
        if carrier == CarrierType.FEDEX.value:
            # FedEx format: 12 digits
            return f"{uuid.uuid4().hex[:12].upper()}"
        elif carrier == CarrierType.UPS.value:
            # UPS format: 1Z followed by 16 chars
            return f"1Z{uuid.uuid4().hex[:16].upper()}"
        elif carrier == CarrierType.USPS.value:
            # USPS format: 20 digits
            return f"{uuid.uuid4().hex[:9].upper()}{str(int(datetime.now().timestamp()))[:11]}"
        elif carrier == CarrierType.DHL.value:
            # DHL format: 11 digits
            return f"{uuid.uuid4().hex[:11].upper()}"
        else:
            # Generic format
            return f"TRK-{uuid.uuid4().hex[:12].upper()}"
    
    @staticmethod
    def generate_label_id() -> str:
        """Generate unique shipping label ID."""
        return f"LBL-{uuid.uuid4().hex[:12].upper()}"
    
    @staticmethod
    def generate_barcode() -> str:
        """Generate barcode for label."""
        return f"{uuid.uuid4().hex[:20].upper()}"


class ShippingLabel:
    """Mock shipping label storage."""
    
    def __init__(self):
        self.labels = {}  # label_id -> label_data
    
    def create_label(
        self,
        order_id: str,
        carrier: str,
        service: str,
        from_address: dict,
        to_address: dict,
        items: list[dict],
        cost: float,
    ) -> dict:
        """Create and store shipping label."""
        label_id = TrackingNumGenerator.generate_label_id()
        tracking_num = TrackingNumGenerator.generate_tracking_number(carrier)
        barcode = TrackingNumGenerator.generate_barcode()
        
        label_data = {
            "label_id": label_id,
            "order_id": order_id,
            "carrier": carrier,
            "service": service,
            "tracking_number": tracking_num,
            "barcode": barcode,
            "from_address": from_address,
            "to_address": to_address,
            "items": items,
            "cost": cost,
            "status": "created",
            "created_at": datetime.now().isoformat(),
            "estimated_delivery": (datetime.now() + timedelta(days=3 if service == "express" else 7)).isoformat(),
        }
        
        self.labels[label_id] = label_data
        return label_data
    
    def get_label(self, label_id: str) -> dict | None:
        """Retrieve label by ID."""
        return self.labels.get(label_id)
    
    def update_label_status(self, label_id: str, status: str) -> dict | None:
        """Update label status."""
        if label_id not in self.labels:
            return None
        
        self.labels[label_id]["status"] = status
        self.labels[label_id]["updated_at"] = datetime.now().isoformat()
        return self.labels[label_id]


# =====================================================================
# Global Mock Instances
# =====================================================================

rate_calculator = CarrierRateCalculator()
tracking_generator = TrackingNumGenerator()
label_store = ShippingLabel()


# =====================================================================
# Tool Registration for OpenAI Agents SDK
# =====================================================================

@function_tool
def get_shipping_rates(
    items: list[ShipmentItem],
    origin_zip: str,
    dest_zip: str,
    carrier: str = "usps",
) -> dict:
    """
    Get shipping rates from carrier for all service levels.

    Args:
        items: List of items to ship with weight info.
        origin_zip: Origin postal code (e.g., "10001").
        dest_zip: Destination postal code (e.g., "90210").
        carrier: Carrier type (fedex, ups, usps, dhl).

    Returns:
        Rates for all service levels (standard, express, overnight, international).
    """
    if not items:
        return {"success": False, "error": "Items list cannot be empty"}

    # Convert validated Pydantic models to the dictionaries used by the mock calculator.
    item_dicts = [item.model_dump() for item in items]
    
    # Validate items have weight
    for item in item_dicts:
        if "weight_oz" not in item or item["weight_oz"] <= 0:
            return {"success": False, "error": f"Item {item.get('sku')} missing valid weight_oz"}
    
    rates_data = rate_calculator.get_rates(item_dicts, origin_zip, dest_zip, carrier)
    
    return {
        "success": True,
        "carrier": carrier,
        "origin_zip": origin_zip,
        "dest_zip": dest_zip,
        "total_weight_oz": rates_data["total_weight_oz"],
        "shipping_zone": rates_data["zone"],
        "rates": rates_data["rates"],
        "message": f"Rates retrieved for {carrier}: standard=${rates_data['rates']['standard']}, express=${rates_data['rates']['express']}, overnight=${rates_data['rates']['overnight']}",
    }


@function_tool
def create_waybill(
    order_id: str,
    carrier: str,
    service: str,
    from_street: str,
    from_city: str,
    from_state: str,
    from_zip: str,
    from_country: str = "US",
    to_street: str = "",
    to_city: str = "",
    to_state: str = "",
    to_zip: str = "",
    to_country: str = "US",
    to_phone: str = "",
    items: list[ShipmentItem] | None = None,
    shipping_cost: float = 0.0,
) -> dict:
    """
    Create and print physical shipping label (waybill).

    Args:
        order_id: Order ID for this shipment.
        carrier: Shipping carrier (fedex, ups, usps, dhl).
        service: Service level (standard, express, overnight, international).
        from_street: Origin street address.
        from_city: Origin city.
        from_state: Origin state.
        from_zip: Origin postal code.
        from_country: Origin country (default: US).
        to_street: Destination street address.
        to_city: Destination city.
        to_state: Destination state.
        to_zip: Destination postal code.
        to_country: Destination country (default: US).
        to_phone: Recipient phone number.
        items: Items being shipped.
        shipping_cost: Cost of shipping.

    Returns:
        Shipping label with tracking number and barcode.
    """
    # Validate required fields
    if not all([order_id, carrier, service, from_street, from_city, from_zip, to_city, to_zip]):
        return {"success": False, "error": "Missing required shipping address fields"}
    
    from_address = {
        "street": from_street,
        "city": from_city,
        "state": from_state,
        "postal_code": from_zip,
        "country": from_country,
    }
    
    to_address = {
        "street": to_street,
        "city": to_city,
        "state": to_state,
        "postal_code": to_zip,
        "country": to_country,
        "phone": to_phone,
    }
    
    label = label_store.create_label(
        order_id=order_id,
        carrier=carrier,
        service=service,
        from_address=from_address,
        to_address=to_address,
        items=[item.model_dump() for item in (items or [])],
        cost=shipping_cost,
    )
    
    return {
        "success": True,
        "label_id": label["label_id"],
        "tracking_number": label["tracking_number"],
        "barcode": label["barcode"],
        "order_id": order_id,
        "carrier": carrier,
        "service": service,
        "cost": shipping_cost,
        "estimated_delivery": label["estimated_delivery"],
        "message": f"Shipping label created: {label['tracking_number']}",
    }


@function_tool
def get_tracking_info(
    tracking_number: str,
    carrier: str = "usps",
) -> dict:
    """
    Get tracking information for a shipment.

    Args:
        tracking_number: Tracking number from carrier.
        carrier: Carrier type (fedex, ups, usps, dhl).

    Returns:
        Current tracking status and estimated delivery.
    """
    # Mock tracking data based on tracking number
    statuses = ["created", "picked_up", "in_transit", "out_for_delivery", "delivered"]
    
    # Use hash of tracking number to pick status
    hash_val = hash(tracking_number) % len(statuses)
    current_status = statuses[hash_val]
    
    estimated_delivery = (datetime.now() + timedelta(days=3)).isoformat()
    
    return {
        "success": True,
        "tracking_number": tracking_number,
        "carrier": carrier,
        "status": current_status,
        "last_update": datetime.now().isoformat(),
        "estimated_delivery": estimated_delivery,
        "events": [
            {
                "timestamp": (datetime.now() - timedelta(hours=2)).isoformat(),
                "status": "picked_up",
                "location": "Distribution Center",
            },
            {
                "timestamp": (datetime.now() - timedelta(hours=1)).isoformat(),
                "status": "in_transit",
                "location": "Regional Hub",
            },
        ],
        "message": f"Package {tracking_number} is {current_status}. Estimated delivery: {estimated_delivery}",
    }


@function_tool
def estimate_delivery_date(
    origin_zip: str,
    dest_zip: str,
    service: str,
) -> dict:
    """
    Estimate delivery date based on service level and geography.

    Args:
        origin_zip: Origin postal code.
        dest_zip: Destination postal code.
        service: Service level (standard, express, overnight, international).

    Returns:
        Estimated delivery date and delivery window.
    """
    # Mock delivery estimates based on service
    delivery_days = {
        "standard": 5,
        "express": 2,
        "overnight": 1,
        "international": 10,
    }
    
    days = delivery_days.get(service, 5)
    
    # Get zone for additional accuracy
    zone = rate_calculator.get_shipping_zone(origin_zip, dest_zip)
    
    # Add day based on zone
    if zone > 2:
        days += 1
    
    delivery_date = (datetime.now() + timedelta(days=days)).date()
    delivery_window_start = (datetime.now() + timedelta(days=days)).time().replace(hour=8, minute=0)
    delivery_window_end = (datetime.now() + timedelta(days=days)).time().replace(hour=18, minute=0)
    
    return {
        "success": True,
        "service": service,
        "origin_zip": origin_zip,
        "dest_zip": dest_zip,
        "estimated_delivery_date": str(delivery_date),
        "delivery_window_start": "08:00 AM",
        "delivery_window_end": "06:00 PM",
        "business_days": days,
        "message": f"Estimated delivery: {delivery_date} ({days} business days via {service} service)",
    }


@function_tool
def validate_address(
    street: str,
    city: str,
    state: str,
    postal_code: str,
    country: str = "US",
) -> dict:
    """
    Validate shipping address format and deliverability.

    Args:
        street: Street address.
        city: City.
        state: State/province.
        postal_code: Postal code.
        country: Country code.

    Returns:
        Address validation status and corrected fields if needed.
    """
    # Mock validation
    is_valid = all([street, city, state, postal_code])
    
    if not is_valid:
        return {
            "success": False,
            "error": "Address missing required fields",
            "valid": False,
        }
    
    # Check postal code format (simple mock)
    postal_valid = len(postal_code) >= 5
    
    return {
        "success": True,
        "valid": postal_valid,
        "street": street,
        "city": city,
        "state": state,
        "postal_code": postal_code,
        "country": country,
        "deliverable": True,
        "message": "Address is valid and deliverable" if postal_valid else "Address format needs review",
    }


# List of all tools for agent registration
all_tools = [
    get_shipping_rates,
    create_waybill,
    get_tracking_info,
    estimate_delivery_date,
    validate_address,
]
