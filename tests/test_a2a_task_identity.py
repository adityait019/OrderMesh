"""Integration coverage for server-assigned A2A task identity."""

from a2a.types import Message, Part, Role, TextPart

from src.common.a2a_compat import new_task_from_user_message


def test_new_message_uses_request_context_task_id() -> None:
    """A newly created task must reuse the IDs assigned by RequestContext."""
    request_message = Message(
        message_id="message-1",
        role=Role.user,
        parts=[Part(root=TextPart(text="check shipping rates"))],
    )
    request_context_task_id = "server-task-123"
    request_context_id = "server-context-456"

    task = new_task_from_user_message(
        request_message,
        request_context_task_id,
        request_context_id,
    )

    assert task.id == request_context_task_id
    assert task.context_id == request_context_id
