"""Run all agents in the background."""

import asyncio
import logging
import signal
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
SHIPPING_AGENT_PORT = os.environ.get("SHIPPING_AGENT_PORT", "8005")
SHIPPING_AGENT_HOST = os.environ.get("SHIPPING_AGENT_HOST", "localhost")

# 5. Notification Agent
NOTIFICATION_AGENT_PORT = os.environ.get("NOTIFICATION_AGENT_PORT", "8004")
NOTIFICATION_AGENT_HOST = os.environ.get("NOTIFICATION_AGENT_HOST", "localhost")


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
async def main():
    """Run all agents in the background."""

    servers = [
        uvicorn.Server(uvicorn.Config(
            build_notification_app(), host=NOTIFICATION_AGENT_HOST,
            port=int(NOTIFICATION_AGENT_PORT), log_config=None,
        )),
        uvicorn.Server(uvicorn.Config(
            build_shipping_app(), host=SHIPPING_AGENT_HOST,
            port=int(SHIPPING_AGENT_PORT), log_config=None,
        )),
        uvicorn.Server(uvicorn.Config(
            build_inventory_app(), host=INVENTORY_AGENT_HOST,
            port=int(INVENTORY_AGENT_PORT), log_config=None,
        )),
        uvicorn.Server(uvicorn.Config(
            build_payment_app(), host=PAYMENT_AGENT_HOST,
            port=int(PAYMENT_AGENT_PORT), log_config=None,
        )),
        uvicorn.Server(uvicorn.Config(
            build_order_app(), host=ORDER_AGENT_HOST,
            port=int(ORDER_AGENT_PORT), log_config=None,
        )),
    ]

    def request_shutdown(signum, _frame):
        logger.info("Received %s; shutting down all agents...", signal.Signals(signum).name)
        for server in servers:
            server.should_exit = True

    previous_handlers = {
        signum: signal.getsignal(signum)
        for signum in (signal.SIGINT, signal.SIGTERM)
    }
    for signum in previous_handlers:
        signal.signal(signum, request_shutdown)

    try:
        await asyncio.gather(*(asyncio.to_thread(server.run) for server in servers))
    finally:
        for server in servers:
            server.should_exit = True
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)


if __name__ == "__main__":
    logger.info("Starting all agents...")
    asyncio.run(main())
