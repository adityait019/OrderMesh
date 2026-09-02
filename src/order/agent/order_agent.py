"""
Order Agent - A2A-compliant order lifecycle management agent with parameter validation
"""

from __future__ import annotations
import os
import json
import logging
import asyncio
from typing import AsyncGenerator, Optional, cast

from dotenv import load_dotenv
from agents import Agent, AgentOutputSchema, Runner, Tool
from agents.memory import SQLiteSession
from openai import AsyncAzureOpenAI
from agents.models.openai_responses import OpenAIResponsesModel

from src.order.agent.system_instruction import SYSTEM_INSTRUCTION
from src.order.tools.order_tools import all_tools
from src.common.responses import OrderResponse

load_dotenv(override=True)
logger = logging.getLogger(__name__)

AGENT_ID = "org.ecommerce.order_agent.v1"
AGENT_NAME = "OrderAgent"

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
    output_type=AgentOutputSchema(OrderResponse, strict_json_schema=False),
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
            if raw_type in ("question", "input_required"):
                return raw_text, "request_input"
            if raw_type in ("error", "failed"):
                return raw_text, "failed"
            if raw_type == "completion":
                return raw_text, "complete"
    except Exception:
        pass

    return raw_text, "complete"


def _validate_order_parameters(query_data: dict) -> tuple[bool, Optional[str]]:
    """
    Validate that required order parameters are present.
    
    Returns:
        (is_valid, error_message)
    """
    required_fields = ["customer_id", "items"]
    missing_fields = [field for field in required_fields if not query_data.get(field)]
    
    if missing_fields:
        return False, f"Missing required order fields: {', '.join(missing_fields)}"
    
    # Validate items
    items = query_data.get("items", [])
    if not isinstance(items, list) or len(items) == 0:
        return False, "Order must contain at least one item"
    
    # Validate each item has required fields
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            return False, f"Item {idx} must be an object/dictionary"
        if not item.get("sku") and not item.get("product_id"):
            return False, f"Item {idx} missing required field: sku"
        if "quantity" not in item:
            return False, f"Item {idx} missing required field: quantity"
        
        try:
            quantity = int(item.get("quantity", 0))
            if quantity <= 0:
                return False, f"Item {idx} quantity must be greater than zero"
        except (ValueError, TypeError):
            return False, f"Item {idx} quantity must be a valid positive integer"
    
    # Validate customer_id is not empty
    customer_id = query_data.get("customer_id", "").strip()
    if not customer_id:
        return False, "customer_id cannot be empty"
    
    return True, None


async def execute_agent(query: str, session_id: str) -> AsyncGenerator[dict, None]:
    """
    A2A-compatible async generator for order agent execution with validation.
    
    Args:
        query: Natural language query or JSON input
        session_id: Session context ID for state persistence
    
    Yields:
        Dict events: tool_call, tool_output, agent_response, usage, done
    """
    sanitized_query = query.strip()
    
    # Try to parse input as JSON for parameter validation
    query_data = {}
    try:
        query_data = json.loads(sanitized_query)
    except (json.JSONDecodeError, ValueError):
        # If not JSON, pass through to agent
        pass
    
    # Validate order parameters if JSON structure detected
    if query_data and isinstance(query_data, dict):
        is_valid, error_msg = _validate_order_parameters(query_data)
        if not is_valid:
            # Emit clarification request
            question_payload = {
                "type": "question",
                "message": error_msg,
                "required_fields": {
                    "customer_id": "string (non-empty)",
                    "items": "array of objects with: sku (string), quantity (positive integer), unit_price (number)"
                },
                "example": {
                    "customer_id": "CUST-12345",
                    "items": [
                        {"sku": "SKU-001", "quantity": 2, "unit_price": 25.0}
                    ]
                }
            }
            yield {
                "type": "agent_response",
                "payload": json.dumps(question_payload),
                "interaction": "request_input",
            }
            yield {"type": "done", "payload": ""}
            return
    
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
    has_completed_successfully = False

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
            tool_output = item.output
            
            # Check if tool execution was successful
            try:
                output_data = json.loads(tool_output) if isinstance(tool_output, str) else tool_output
                if isinstance(output_data, dict) and "success" in output_data:
                    has_completed_successfully = output_data.get("success") is True
            except (json.JSONDecodeError, ValueError):
                pass
            
            yield {
                "type": "tool_output",
                "payload": {
                    "output": tool_output,
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
            
            # Only mark as complete if we had successful tool execution
            if interaction == "complete" and not has_completed_successfully:
                interaction = "request_input"
            
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
