from __future__ import annotations

import inspect
import uuid
import logging
import asyncio
import json
from typing import Any

from a2a.server.agent_execution import AgentExecutor
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import (
    Message,
    Part,
    Role,
    TaskState,
    TextPart,
    UnsupportedOperationError,
    FilePart,
    FileWithUri,
)
from a2a.utils.errors import ServerError
from src.notification.utils.artifact_downloader import fetch_remote_file

logger = logging.getLogger(__name__)


class NotificationAgentExecutor(AgentExecutor):
    """
    Properly implements A2A protocol for agent execution.

    Key fixes:
    - Validates RequestContext completely
    - Properly handles streaming vs non-streaming execution
    - Correct TaskState lifecycle management
    - Proper message formatting per A2A spec
    - Error handling with proper task lifecycle
    """

    def __init__(self, agent_id: str, execute_fn):
        self.agent_id = agent_id
        self.execute_fn = execute_fn

    def _coerce_text(self, payload: Any) -> str:
        """Convert payload to text, handling various types."""
        if payload is None:
            return ""

        if isinstance(payload, str):
            return payload

        if isinstance(payload, (dict, list, tuple)):
            try:
                return json.dumps(payload, indent=2, ensure_ascii=False, default=str)
            except Exception:
                return str(payload)

        return str(payload)

    def _make_text_part(self, text: str) -> Part:
        """Create a properly formatted A2A text part."""
        return Part(root=TextPart(text=text))

    def _make_message(self, text: str, role: Role = Role.agent) -> Message:
        """Create a properly formatted A2A message."""
        return Message(
            message_id=str(uuid.uuid4()),
            role=role,
            parts=[self._make_text_part(text)],
        )

    def _extract_interaction(self, ev: dict, text_payload: str) -> str:
        """
        Extract interaction type from event.
        Valid values: 'complete', 'request_input', 'failed'
        """
        interaction = ev.get("interaction")

        if isinstance(interaction, str) and interaction.strip():
            valid = interaction.strip().lower()
            if valid in ("complete", "request_input", "failed"):
                return valid
            logger.warning(
                f"Unknown interaction type: {valid}, defaulting to 'complete'"
            )
            return "complete"

        try:
            parsed = json.loads(text_payload)
            if isinstance(parsed, dict):
                value = parsed.get("interaction", "").strip().lower()
                if value in ("complete", "request_input", "failed"):
                    return value
        except Exception:
            pass

        return "complete"

    async def _extract_file(self, context: RequestContext) -> str | None:
        """
        Extract file from request context safely.
        Returns local file path or None if no file attached.
        """
        if not context.message or not context.message.parts:
            return None

        file_url = None

        for part in context.message.parts:
            root = part.root
            if isinstance(root, FilePart):
                if isinstance(root.file, FileWithUri):
                    file_url = root.file.uri
                    break

        if not file_url:
            return None

        try:
            file_id, filename, local_path = await fetch_remote_file(file_url)
            logger.info(f"Downloaded file {filename} to {local_path}")
            return local_path
        except Exception as e:
            logger.error(f"Failed to download file from {file_url}: {e}")
            raise ValueError(f"Failed to download file from {file_url}: {e}") from e

    async def _extract_file_data(self, local_path: str) -> str:
        """Extract data from file as string."""
        try:
            with open(local_path, "r", encoding="utf-8") as f:
                data = f.read()
                return data
        except Exception as e:
            logger.error(f"Failed to read file {local_path}: {e}")
            raise ValueError(f"Failed to read file {local_path}: {e}") from e

    def _extract_query_text(self, context: RequestContext) -> str:
        """Extract query text from request context (A2A compliant)."""
        if not context.message or not context.message.parts:
            raise ValueError("RequestContext must contain message parts")

        for part in context.message.parts:
            root = getattr(part, "root", None)

            # Try root.text first
            if root is not None:
                text = getattr(root, "text", None)
                if isinstance(text, str) and text.strip():
                    return text.strip()

            # Fall back to part.text
            text = getattr(part, "text", None)
            if isinstance(text, str) and text.strip():
                return text.strip()

        raise ValueError("Could not extract query text from message parts")

    def _validate_request_context(self, context: RequestContext) -> None:
        """Validate RequestContext has all required fields per A2A spec."""
        if not context:
            raise ValueError("RequestContext cannot be None")

        if not context.task_id:
            raise ValueError("RequestContext missing task_id")

        if not context.context_id:
            raise ValueError("RequestContext missing context_id")

        if not context.message or not context.message.parts:
            raise ValueError("RequestContext must contain message with parts")

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        """
        Main execution entry point (A2A protocol compliant).

        Lifecycle:
        1. Validate context
        2. Start work
        3. Execute agent function
        4. Handle streaming or non-streaming results
        5. Transition to final state (complete or failed)
        """
        try:
            # STEP 1: Validate context
            self._validate_request_context(context)

            if not context.task_id or not context.context_id:
                raise ValueError("RequestContext must have task_id and context_id")
            updater = TaskUpdater(
                event_queue,
                context.task_id,
                context.context_id,
            )

            # STEP 2: Submit if no task exists yet
            if not context.current_task:
                await updater.submit()

            # STEP 3: Mark work as started
            await updater.start_work()

            # STEP 4: Extract inputs
            query = self._extract_query_text(context)
            logger.info("[%s] Received query: %s", self.agent_id, query[:200])

            # Try to extract attached file (optional)
            file_path = None
            try:
                file_path = await self._extract_file(context)
                if file_path:
                    file_data = await self._extract_file_data(file_path)
                    query += f"\n\n[Attached File Content]:\n{file_data}"
                    logger.info(f"[{self.agent_id}] Attached file processed")
            except Exception as e:
                logger.warning(f"Failed to process file: {e}")
                # Don't fail the task, just continue without file

            # STEP 5: Notify execution started
            await updater.update_status(
                TaskState.working,
                message=updater.new_agent_message(
                    [self._make_text_part(f"{self.agent_id} started processing")]
                ),
            )

            # STEP 6: Execute agent function
            out = self.execute_fn(query, context.context_id)

            # STEP 7a: STREAMING CASE
            if inspect.isasyncgen(out):
                await self._handle_streaming_execution(
                    updater, out, context.context_id
                )
                return

            # STEP 7b: NON-STREAMING CASE
            await self._handle_non_streaming_execution(updater, out)

        except Exception as exc:
            logger.exception("Executor error for %s", self.agent_id)
            if not context.task_id or not context.context_id:
                logger.error("Cannot update task state due to missing IDs")
                return
            updater = TaskUpdater(
                event_queue,
                context.task_id,
                context.context_id,
            )
            await updater.failed(
                message=self._make_message(f"Execution failed: {str(exc)}")
            )

    async def _handle_streaming_execution(
        self,
        updater: TaskUpdater,
        stream,
        context_id: str,
    ) -> None:
        """Handle streaming async generator execution (A2A protocol)."""
        final_interaction = "complete"
        final_response_text = ""
        active_tool_name = "unknown_tool"

        try:
            async for ev in stream:
                await asyncio.sleep(0)  # Yield control

                ev_type = ev.get("type")
                payload = ev.get("payload")

                # ================================
                # TOOL CALL EVENT
                # ================================
                if ev_type == "tool_call":
                    tool_name = payload.get("tool_name", "unknown_tool")
                    tool_call_id = payload.get("tool_call_id", "unknown_id")
                    active_tool_name = tool_name

                    await updater.update_status(
                        TaskState.working,
                        metadata={
                            "type": "tool_event",
                            "phase": "call",
                            "tool_name": active_tool_name,
                            "tool_call_id": tool_call_id,
                        },
                    )
                    continue

                # ================================
                # TOOL OUTPUT EVENT
                # ================================
                if ev_type == "tool_output":
                    tool_call_id = payload.get("tool_call_id", "unknown_id")
                    tool_output = payload.get("output")

                    await updater.update_status(
                        TaskState.working,
                        metadata={
                            "type": "tool_event",
                            "phase": "response",
                            "tool_name": active_tool_name,
                            "tool_call_id": tool_call_id,
                        },
                    )
                    continue

                # ================================
                # AGENT RESPONSE EVENT
                # ================================
                if ev_type == "agent_response":
                    # Extract interaction type
                    interaction = self._extract_interaction(ev, payload)
                    final_interaction = interaction

                    # Coerce payload to text
                    if isinstance(payload, list):
                        text_payload = "\n".join(
                            [f"{i + 1}. {q}" for i, q in enumerate(payload)]
                        )
                    else:
                        text_payload = self._coerce_text(payload).strip()

                    final_response_text = text_payload

                    # Handle request_input state
                    if interaction == "request_input":
                        await updater.update_status(
                            TaskState.input_required,
                            message=updater.new_agent_message(
                                [self._make_text_part(text_payload)]
                            ),
                            final=True,
                        )
                        return

                    if interaction == "failed":
                        await updater.failed(
                            message=self._make_message(text_payload or "Agent task failed")
                        )
                        return

                    # Continue streaming
                    await updater.update_status(
                        TaskState.working,
                        message=updater.new_agent_message(
                            [self._make_text_part(text_payload)]
                        ),
                    )
                    continue

                # ================================
                # USAGE EVENT (metadata only)
                # ================================
                if ev_type == "usage":
                    await updater.update_status(
                        TaskState.working,
                        metadata={
                            "type": "usage",
                            "input_tokens": payload.get("input_tokens"),
                            "output_tokens": payload.get("output_tokens"),
                            "total_tokens": payload.get("total_tokens"),
                        },
                    )
                    continue

                logger.debug(f"Unhandled event type: {ev_type}")

            # Stream ended - transition to final state
            if final_interaction == "request_input":
                # Already marked as input_required with final=True
                return

            # Mark as complete
            await updater.complete(
                message=self._make_message(
                    final_response_text or "Task completed successfully"
                )
            )

        except Exception as e:
            logger.exception("Error during streaming execution")
            await updater.failed(
                message=self._make_message(f"Streaming execution failed: {str(e)}")
            )

    async def _handle_non_streaming_execution(
        self,
        updater: TaskUpdater,
        out,
    ) -> None:
        """Handle non-streaming (sync or async) execution (A2A protocol)."""
        try:
            # Await if it's awaitable
            result = await out if inspect.isawaitable(out) else out
            result_text = self._coerce_text(result).strip()

            final_text = result_text or "Task completed successfully"

            # Update status and complete
            await updater.update_status(
                TaskState.working,
                message=updater.new_agent_message(
                    [self._make_text_part(final_text)]
                ),
            )

            await updater.complete(message=self._make_message(final_text))

        except Exception as e:
            logger.exception("Error during non-streaming execution")
            await updater.failed(
                message=self._make_message(f"Execution failed: {str(e)}")
            )

    async def cancel(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        """Cancel operation (not supported)."""
        raise ServerError(error=UnsupportedOperationError())
