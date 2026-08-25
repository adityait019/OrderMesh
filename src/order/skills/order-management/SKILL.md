---
name: order-management
description: Processes incoming validated order items, calculates taxes, applies discounts, and initializes order status records.
---

# Order Management Skill

Use this skill to transform raw customer line items into an actionable financial order record.

## Instructions
1. Run `scripts/calculate_totals.py` with the raw item list to compute tax rates and final total.
2. Initialize an order object set to status `PENDING_INVENTORY`.
3. Return the calculated payload back to the orchestrator.

## Execution Output Schema
- `order_id`: String (UUID)
- `line_items`: Array of items with subtotal
- `grand_total`: Float