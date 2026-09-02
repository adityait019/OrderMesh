"""
Payment Agent A2A Server
Handles card authorization, payment capture, and transaction management
"""

from __future__ import annotations

import asyncio
import os
import json
import logging
import sys
from datetime import datetime
from contextlib import asynccontextmanager
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore

from src.payment.utils.agent_executor import PaymentAgentExecutor
from src.payment.utils.agent_card_builder import build_agent_card_from_meta
from dotenv import load_dotenv

# =====================================================================
# Setup
# =====================================================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
load_dotenv(override=True)

# Load agent metadata
with open(Path(__file__).resolve().parent / "agent_cards" / "payment_agent_card.json", "r", encoding="utf-8") as f:
    META = json.load(f)

AGENT_ID = META.get("agent_id", "org.ecommerce.payment_agent.v1")
PAYMENT_AGENT_PORT = os.environ.get("PAYMENT_AGENT_PORT", "8001")
PAYMENT_AGENT_HOST = os.environ.get("PAYMENT_AGENT_HOST", "localhost")
ORCHESTRATOR_URL = os.environ.get("ORCHESTRATOR_URL", "http://localhost:8000")
ORCHESTRATOR_TOKEN = os.environ.get("ORCHESTRATOR_TOKEN", "")

# Import agent execution function
from src.payment.agent.payment_agent import execute_agent as execute_fn


# =====================================================================
# Application Factory
# =====================================================================

def build_app() -> Starlette:
    """Build A2A-compliant Starlette application for Payment Agent."""
    
    task_store = InMemoryTaskStore()

    agent_executor = PaymentAgentExecutor(
        agent_id=AGENT_ID,
        execute_fn=execute_fn,
    )

    request_handler = DefaultRequestHandler(
        agent_executor=agent_executor,
        task_store=task_store,
    )

    agent_card = build_agent_card_from_meta(
        meta=META,
        base_url=f"http://{PAYMENT_AGENT_HOST}:{PAYMENT_AGENT_PORT}",
    )

    logger.info(f"Agent card built: {agent_card.name} v{agent_card.version}")

    a2a_app = A2AStarletteApplication(
        agent_card=agent_card,
        http_handler=request_handler,
    )

    # =====================================================================
    # Orchestrator Registration & Heartbeat
    # =====================================================================

    async def register_with_orchestrator():
        """Register this agent with the orchestrator."""
        if not ORCHESTRATOR_TOKEN:
            logger.warning("ORCHESTRATOR_TOKEN not set - skipping registration")
            return

        payload = {
            "name": META.get("short_name", "PaymentAgent"),
            "host": PAYMENT_AGENT_HOST,
            "port": int(PAYMENT_AGENT_PORT),
        }

        max_retries = 5
        retry_count = 0

        while retry_count < max_retries:
            try:
                async with httpx.AsyncClient() as client:
                    logger.info(
                        f"Registering with orchestrator at {ORCHESTRATOR_URL}... "
                        f"(attempt {retry_count + 1}/{max_retries})"
                    )
                    
                    response = await client.post(
                        f"{ORCHESTRATOR_URL}/agents/add",
                        json=payload,
                        headers={
                            "Content-Type": "application/json",
                            "x-admin-token": ORCHESTRATOR_TOKEN,
                        },
                        timeout=10.0,
                    )

                    if response.status_code == 200:
                        logger.info("Successfully registered with orchestrator.")
                        return
                    else:
                        logger.warning(
                            f"Registration failed: {response.status_code} - {response.text}"
                        )
                        retry_count += 1
                        if retry_count < max_retries:
                            await asyncio.sleep(2 ** retry_count)

            except Exception as e:
                logger.warning(f"Registration attempt failed: {e}")
                retry_count += 1
                if retry_count < max_retries:
                    await asyncio.sleep(2 ** retry_count)

    async def heartbeat_loop():
        """Send periodic heartbeats to orchestrator."""
        if not ORCHESTRATOR_TOKEN:
            logger.info("Orchestrator token not set - heartbeat disabled")
            return

        heartbeat_url = f"{ORCHESTRATOR_URL}/agents/heartbeat"
        version = META.get("version", "1.0.0")

        async with httpx.AsyncClient() as client:
            while True:
                try:
                    await client.post(
                        heartbeat_url,
                        json={
                            "agent_id": AGENT_ID,
                            "version": version,
                        },
                        timeout=5.0,
                    )
                    logger.debug("Heartbeat sent successfully.")
                except asyncio.TimeoutError:
                    logger.debug("Heartbeat timeout (non-fatal)")
                except Exception as e:
                    logger.debug(f"Heartbeat failed (non-fatal): {e}")

                await asyncio.sleep(30)

    @asynccontextmanager
    async def lifespan(app: Starlette):
        """Application lifecycle manager."""
        registration_task = None
        heartbeat_task = None

        try:
            logger.info(f"Starting {AGENT_ID}")
            
            registration_task = asyncio.create_task(register_with_orchestrator())

            if ORCHESTRATOR_TOKEN:
                heartbeat_task = asyncio.create_task(heartbeat_loop())
                logger.info("Heartbeat loop started")

            yield

        finally:
            if registration_task:
                registration_task.cancel()
            if heartbeat_task:
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass
                logger.info("Heartbeat loop cancelled")

            logger.info(f"Stopped {AGENT_ID}")

    # =====================================================================
    # Create Starlette App
    # =====================================================================

    app = Starlette(lifespan=lifespan)
    a2a_app.add_routes_to_app(app)

    # =====================================================================
    # Health Check Endpoints
    # =====================================================================

    async def health(_: Request) -> JSONResponse:
        """Health check endpoint."""
        return JSONResponse(
            {
                "status": "ok",
                "agent_id": AGENT_ID,
                "agent_name": META.get("name", "Unknown"),
                "agent_version": META.get("version", "unknown"),
                "timestamp": datetime.now().astimezone().isoformat(),
            }
        )

    app.add_route("/health", health, methods=["GET"])
    app.add_route("/healthz", health, methods=["GET"])

    # =====================================================================
    # Debug Endpoint
    # =====================================================================

    async def debug_info(_: Request) -> JSONResponse:
        """Debug info endpoint."""
        return JSONResponse(
            {
                "agent_id": AGENT_ID,
                "agent_name": agent_card.name,
                "version": agent_card.version,
                "skills": [
                    {
                        "id": skill.id,
                        "name": skill.name,
                        "description": skill.description,
                    }
                    for skill in agent_card.skills
                ],
                "capabilities": {
                    "streaming": agent_card.capabilities.streaming,
                },
            }
        )

    app.add_route("/debug/info", debug_info, methods=["GET"])

    return app


# =====================================================================
# Main Entry Point
# =====================================================================

if __name__ == "__main__":
    import uvicorn

    app = build_app()

    logger.info(f"Starting A2A Payment Agent server on {PAYMENT_AGENT_HOST}:{PAYMENT_AGENT_PORT}")

    uvicorn.run(
        app,
        host=PAYMENT_AGENT_HOST,
        port=int(PAYMENT_AGENT_PORT),
        log_level="info",
    )
