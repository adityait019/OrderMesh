"""
Inventory Agent - A2A-compliant inventory management agent
"""

from __future__ import annotations
import os
import json
import logging
import asyncio
from typing import AsyncGenerator, Optional, cast

from dotenv import load_dotenv
from agents import Agent, Runner,Tool
from agents.memory import SQLiteSession
from langchain import tools
from openai import AsyncAzureOpenAI
from agents.models.openai_responses import OpenAIResponsesModel

from src.inventory.agent.system_instructions import SYSTEM_INSTRUCTION
from src.inventory.tools.inventory_tools import all_tools

load_dotenv(override=True)
logger = logging.getLogger(__name__)

AGENT_ID = "org.ecommerce.inventory_agent.v1"
AGENT_NAME = "InventoryAgent"

client = AsyncAzureOpenAI(
    azure_endpoint=os.getenv("AZURE_OPENAI_API_BASE", ""),
    api_key=os.getenv("AZURE_OPENAI_API_KEY", ""),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION", ""),
)

model = OpenAIResponsesModel(
    model=os.getenv("DEPLOYMENT_NAME", ""),
    openai_client=client,
)

agent = Agent(
    name=AGENT_NAME,
    instructions=SYSTEM_INSTRUCTION,
    model=model,
    tools=cast(list[Tool], all_tools),
    tool_use_behavior="run_llm_again",
    reset_tool_choice=True,
)


def _coerce_final_payload(raw_text: str) -> tuple[str, str]:
    """Returns (payload, interaction) for A2A executor compatibility."""
    raw_text = (raw_text or "").strip()
    if not raw_text:
        return "", "request_input"

    # Try JSON wrapper first
    try:
        parsed = json.loads(raw_text)
        if isinstance(parsed, dict):
            raw_type = str(parsed.get("type") or "").lower().strip()
            if raw_type == "question":
                return raw_text, "request_input"
    except Exception:
        pass

    return raw_text, "complete"


async def execute_agent(query: str, session_id: str) -> AsyncGenerator[dict, None]:
    """
    A2A-compatible async generator for inventory agent execution.
    
    Args:
        query: Natural language query or JSON input
        session_id: Session context ID for state persistence
    
    Yields:
        Dict events: tool_call, tool_output, agent_response, usage, done
    """
    sanitized_query = query.strip()
    
    session = SQLiteSession(
        session_id=session_id,
        db_path=os.getenv("AGENT_SESSION_DB", "./session_db.db"),
    )
    
    streamed = Runner.run_streamed(
        agent,
        sanitized_query,
        session=session,
        max_turns=50,
    )

    last_agent_response_text = ""

    async for event in streamed.stream_events():
        if event.type != "run_item_stream_event":
            continue

        item = event.item

        if item.type == "tool_call_item":
            raw = item.raw_item
            tool_call_id = raw.get("call_id") if isinstance(raw, dict) else getattr(raw, "call_id", None)
            tool_name = raw.get("name") if isinstance(raw, dict) else getattr(raw, "name", None)
            arguments = raw.get("arguments") if isinstance(raw, dict) else getattr(raw, "arguments", None)

            yield {
                "type": "tool_call",
                "payload": {
                    "tool_name": tool_name,
                    "tool_call_id": tool_call_id,
                    "input": arguments,
                },
            }
            continue

        if item.type == "tool_call_output_item":
            raw = item.raw_item
            tool_call_id = raw.get("call_id") if isinstance(raw, dict) else getattr(raw, "call_id", None)
            yield {
                "type": "tool_output",
                "payload": {
                    "output": item.output,
                    "tool_call_id": tool_call_id,
                },
            }
            continue

        if item.type == "message_output_item":
            raw_text = ""
            try:
                raw_text = (
                    getattr(item.raw_item.content[0], "text", "")
                    if item.raw_item.content
                    else ""
                )
            except Exception:
                raw_text = ""
            
            raw_text = (raw_text or "").strip()
            payload, interaction = _coerce_final_payload(raw_text)
            last_agent_response_text = payload

            yield {
                "type": "agent_response",
                "payload": payload,
                "interaction": interaction,
            }

            if interaction == "request_input":
                return

    if streamed.run_loop_task is not None:
        await streamed.run_loop_task

    # Collect usage metrics
    input_tokens = 0
    output_tokens = 0
    total_tokens = 0
    for response in streamed.raw_responses:
        if response.usage:
            input_tokens += response.usage.input_tokens
            output_tokens += response.usage.output_tokens
            total_tokens += response.usage.total_tokens

    yield {
        "type": "usage",
        "payload": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
        },
    }
    yield {"type": "done", "payload": ""}