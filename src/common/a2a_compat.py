"""Compatibility helpers for the pinned A2A v0.3 SDK."""

from __future__ import annotations

from a2a.types import Message, Task, TaskState, TaskStatus


def new_task_from_user_message(
    message: Message,
    task_id: str | None,
    context_id: str | None,
) -> Task:
    """Create an initial task using IDs assigned by RequestContext."""
    if not task_id:
        raise ValueError("RequestContext.task_id is required when creating a task")
    if not context_id:
        raise ValueError("RequestContext.context_id is required when creating a task")

    return Task(
        id=task_id,
        context_id=context_id,
        status=TaskStatus(state=TaskState.submitted),
        history=[message],
    )
