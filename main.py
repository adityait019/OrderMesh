"""Run all agents in the background."""

import asyncio
import logging
from src.notification.main import build_app as build_notification_app
from src.payment.main import build_app as build_payment_app
from src.shipping.main import build_app as build_shipping_app
from src.inventory.main import build_app as build_inventory_app
from src.order.main import build_app as build_order_app 
import uvicorn
import os
from dotenv import load_dotenv
load_dotenv(override=True)

#=====================================================================
# Setup
#=====================================================================
# 1. Order Agent
ORDER_AGENT_PORT = os.environ.get("ORDER_AGENT_PORT", "8002")
ORDER_AGENT_HOST = os.environ.get("ORDER_AGENT_HOST", "localhost")


# 2. Inventory Agent
INVENTORY_AGENT_PORT = os.environ.get("INVENTORY_AGENT_PORT", "8003")
INVENTORY_AGENT_HOST = os.environ.get("INVENTORY_AGENT_HOST", "localhost")

# 3. Payment Agent
PAYMENT_AGENT_PORT = os.environ.get("PAYMENT_AGENT_PORT", "8001")
PAYMENT_AGENT_HOST = os.environ.get("PAYMENT_AGENT_HOST", "localhost")

# 4. Shipping Agent
SHIPPING_AGENT_PORT = os.environ.get("SHIPPING_AGENT_PORT", "8003")
SHIPPING_AGENT_HOST = os.environ.get("SHIPPING_AGENT_HOST", "localhost")

# 5. Notification Agent
NOTIFICATION_AGENT_PORT = os.environ.get("NOTIFICATION_AGENT_PORT", "8004")
NOTIFICATION_AGENT_HOST = os.environ.get("NOTIFICATION_AGENT_HOST", "localhost")


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
async def main():
    """Run all agents in the background."""

    # Start all agents concurrently
    await asyncio.gather(
        asyncio.to_thread(
            uvicorn.run, build_notification_app(),
            host=NOTIFICATION_AGENT_HOST, port=int(NOTIFICATION_AGENT_PORT)
        ),
        asyncio.to_thread(
            uvicorn.run, build_shipping_app(),
            host=SHIPPING_AGENT_HOST, port=int(SHIPPING_AGENT_PORT)
        ),
        asyncio.to_thread(
            uvicorn.run, build_inventory_app(),
            host=INVENTORY_AGENT_HOST, port=int(INVENTORY_AGENT_PORT)
        ),
        asyncio.to_thread(
            uvicorn.run, build_payment_app(),
            host=PAYMENT_AGENT_HOST, port=int(PAYMENT_AGENT_PORT)
        ),
        asyncio.to_thread(
            uvicorn.run, build_order_app(),
            host=ORDER_AGENT_HOST, port=int(ORDER_AGENT_PORT)
        )
    )


if __name__ == "__main__":
    try:
        logger.info("Starting all agents...")
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutting down all agents...")
        asyncio.run(asyncio.sleep(1))  # Allow time for graceful shutdown
