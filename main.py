from __future__ import annotations

import os

from datetime import datetime
import json
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from utils.agent_card_builder import build_agent_card_from_meta
from order_service.agent.order_agent import stream_agent_response as execute_fn  # noqa: E402
from srcs.order_service.
from dotenv import load_dotenv
load_dotenv(override=True)

with open(r"agent_card.json", "r", encoding="utf-8") as f:
    META = json.load(f)

AGENT_ID=META.get("agent_id", "org.ordermesh.order_management_agent.v1")

def build_app() -> Starlette:
    task_store = InMemoryTaskStore()

    agent_executor = DynamicFunctionAgentExecutor(
        agent_id=AGENT_ID,
        execute_fn=execute_fn,
    )

    request_handler = DefaultRequestHandler(
        agent_executor=agent_executor,
        task_store=task_store,
    )

    agent_card = build_agent_card_from_meta(
        meta=META,
        base_url=f"http://10.73.83.83:{os.environ['AGENT_PORT']}",
    )

    app = Starlette()
    a2a_app = A2AStarletteApplication(
        agent_card=agent_card,
        http_handler=request_handler,
    )
    a2a_app.add_routes_to_app(app)

    async def health(_: Request):
        return JSONResponse(
            {
                "status": "ok",
                "agent_id": AGENT_ID,
                "agent_name": META.get("Agent_Name"),
                "timestamp": datetime.now().astimezone().isoformat(),
            }
        )

    app.add_route("/health", health, methods=["GET"])
    app.add_route("/healthz", health, methods=["GET"])

    return app


if __name__ == "__main__":
    import uvicorn

    app = build_app()
    uvicorn.run(
        app,
        host="10.73.83.83",
        port=int(os.environ["AGENT_PORT"]),
        log_level="info",
    )
