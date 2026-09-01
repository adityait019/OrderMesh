from __future__ import annotations

import re
from typing import Any

from a2a.types import (
    AgentCard,
    AgentSkill,
    AgentCapabilities,
    AgentExtension,
)

MIME_TEXT = "text/plain"
MIME_JSON = "application/json"


# =====================================================================
# Helpers
# =====================================================================

def _safe_str(value: Any, default: str = "") -> str:
    """Safely convert value to string with default fallback."""
    if value is None:
        return default
    return str(value)


def _safe_id(value: str) -> str:
    """
    Make a stable A2A-safe ID from agent/task names.
    Keeps letters, numbers, underscore, hyphen, dot.
    Replaces everything else with underscore.
    """
    value = _safe_str(value, "unknown")
    value = re.sub(r"[^a-zA-Z0-9_.\-]+", "_", value)
    value = value.strip("_")
    return value or "unknown"


def _get_identity(meta: dict) -> dict:
    """
    Extract identity info from metadata.
    
    Supports both:
    1. Nested format:
       {
         "identity": {
           "agent_id": "...",
           "name": "...",
           "description": "..."
         }
       }

    2. Flat format:
       {
         "agent_id": "...",
         "name": "...",
         "description": "...",
         "agent_type": "...",
         "version": "..."
       }
    """
    identity = meta.get("identity")

    if isinstance(identity, dict) and identity:
        return {
            "agent_id": identity.get("agent_id") or meta.get("agent_id"),
            "name": identity.get("name") or meta.get("name") or "Unnamed Agent",
            "description": identity.get("description") or meta.get("description", ""),
            "short_name": identity.get("short_name") or meta.get("short_name"),
            "agent_type": identity.get("agent_type") or meta.get("agent_type", "generic"),
            "version": (
                identity.get("version")
                or meta.get("version")
                or meta.get("versioning", {}).get("version", "1.0.0")
            ),
        }

    return {
        "agent_id": meta.get("agent_id"),
        "name": meta.get("name", "Unnamed Agent"),
        "description": meta.get("description", ""),
        "short_name": meta.get("short_name"),
        "agent_type": meta.get("agent_type", "generic"),
        "version": (
            meta.get("version")
            or meta.get("versioning", {}).get("version", "1.0.0")
        ),
    }


def _get_tasks(meta: dict) -> list:
    """
    Extract tasks from metadata.
    
    Supports:
    {
      "tasks": {
        "task": [...]
      }
    }

    Also tolerates:
    {
      "task_catalog": [...]
    }
    """
    tasks = meta.get("tasks", {})

    if isinstance(tasks, dict):
        task_list = tasks.get("task", [])
        if isinstance(task_list, list):
            return task_list

    task_catalog = meta.get("task_catalog", [])
    if isinstance(task_catalog, list):
        return task_catalog

    return []


def _get_specialization(meta: dict) -> dict:
    """Extract specialization info from metadata."""
    specialization = meta.get("specialization", {})
    return specialization if isinstance(specialization, dict) else {}


def _get_capabilities(meta: dict) -> dict:
    """Extract capabilities from metadata."""
    capabilities = meta.get("capabilities", {})
    return capabilities if isinstance(capabilities, dict) else {}


def _get_version(meta: dict) -> str:
    """Extract version from metadata with fallback chain."""
    identity = _get_identity(meta)

    return (
        identity.get("version")
        or meta.get("version")
        or meta.get("versioning", {}).get("version")
        or "1.0.0"
    )


# =====================================================================
# Agent Name
# =====================================================================

def agent_name_builder(meta: dict) -> str:
    """Build A2A-compliant agent name from metadata."""
    identity = _get_identity(meta)

    # Prefer short_name if available because A2A names should be compact.
    name = (
        identity.get("short_name")
        or identity.get("name")
        or meta.get("short_name")
        or meta.get("name")
        or "Unnamed Agent"
    )

    # Convert spaces to underscores for A2A compliance
    return "_".join(str(name).split())


# =====================================================================
# Skills
# 1 skill per task (A2A protocol)
# =====================================================================

def build_skills_from_meta(meta: dict) -> list[AgentSkill]:
    """
    Build A2A skills from metadata.
    
    A2A protocol requires:
    - Each task maps to exactly one skill
    - Skill IDs must be stable and safe
    - Skills must have input/output modes
    - Examples should be clear
    """
    identity = _get_identity(meta)
    tasks = _get_tasks(meta)
    specialization = _get_specialization(meta)

    agent_id = identity.get("agent_id") or "unknown_agent"
    agent_name = identity.get("name") or "Unnamed Agent"
    agent_description = identity.get("description") or ""

    primary_specialization = (
        specialization.get("primary")
        or specialization.get("primary_specialization")
        or "generic"
    )

    agent_type = identity.get("agent_type") or meta.get("agent_type", "generic")

    skills: list[AgentSkill] = []

    # If no tasks defined, create default skill
    if not tasks:
        tasks = [
            {
                "name": "evaluate_architecture_submission",
                "description": (
                    agent_description
                    or "Evaluate architecture submission using architecture governance guardrails."
                ),
                "requires_human_approval": False,
            }
        ]

    for task in tasks:
        task_name = (
            task.get("name")
            or task.get("task_name")
            or task.get("task_id")
            or "agent_task"
        )

        task_description = (
            task.get("description")
            or agent_description
            or f"Invoke {agent_name} for {task_name}"
        )

        skill_id = _safe_id(f"invoke_{agent_id}_{task_name}")

        # Build tags - should be meaningful for A2A discovery
        tags = [
            _safe_str(primary_specialization, "generic"),
            _safe_str(agent_type, "generic"),
            "a2a",
            "enterprise",
            "architecture-governance",
        ]

        skills.append(
            AgentSkill(
                id=skill_id,
                name=task_name,
                description=task_description,
                tags=tags,
                input_modes=[MIME_TEXT, MIME_JSON],
                output_modes=[MIME_TEXT, MIME_JSON],
                examples=[
                    f"Invoke {agent_name} for {task_name}",
                    f"Run {task_name} with an architecture submission JSON payload",
                    f"Execute {task_name} to validate architecture compliance",
                ],
            )
        )

    return skills


# =====================================================================
# Extensions
# SEL / Agent metadata bridge
# =====================================================================

def build_agent_extension(meta: dict) -> AgentExtension:
    """
    Build A2A extension for agent metadata.
    
    This bridges agent metadata with A2A protocol runtime.
    URI format: urn:<organization>:<capability>:<version>
    """
    tasks = _get_tasks(meta)
    first_task = tasks[0] if tasks else {}

    identity = _get_identity(meta)

    return AgentExtension(
        uri="urn:cyberbytes-hardware:notification-agent:metadata",
        params={
            "agent_id": identity.get("agent_id"),
            "short_name": identity.get("short_name"),
            "agent_type": identity.get("agent_type"),
            "status": meta.get("status"),
            "human_in_loop": first_task.get("requires_human_approval", False),
            "specialization": meta.get("specialization"),
            "capabilities": meta.get("capabilities"),
            "backend": meta.get("backend"),
            "config": meta.get("config"),
            "ownership": meta.get("ownership"),
            "version": _get_version(meta),
        },
    )


# =====================================================================
# Capabilities
# =====================================================================

def build_capabilities_from_meta(meta: dict) -> AgentCapabilities:
    """
    Build A2A capabilities from metadata.
    
    A2A protocol specifies:
    - streaming: whether agent supports streaming responses
    - push_notifications: optional notification support
    - state_transition_history: optional history tracking
    - extensions: custom metadata extensions
    """
    return AgentCapabilities(
        streaming=True,
        push_notifications=None,
        state_transition_history=None,
        extensions=[build_agent_extension(meta)],
    )


# =====================================================================
# AgentCard Builder (Main Entry Point)
# =====================================================================

def build_agent_card_from_meta(
    *,
    meta: dict,
    base_url: str,
) -> AgentCard:
    """
    Build A2A AgentCard from metadata dictionary.
    
    This is the main entry point for creating an A2A-compliant agent card.
    
    Args:
        meta: Agent metadata dictionary
        base_url: Base URL for agent endpoint (e.g., "http://localhost:8000")
    
    Returns:
        AgentCard: A2A-compliant agent card
    
    A2A Protocol Requirements:
    - name: A2A-safe identifier (underscores, alphanumeric)
    - version: Semantic versioning (X.Y.Z)
    - preferred_transport: JSONRPC or REST
    - protocol_version: A2A spec version (0.3.0+)
    - skills: At least one skill
    - capabilities: Must include streaming capability
    """
    identity = _get_identity(meta)

    return AgentCard(
        name=agent_name_builder(meta),
        description=identity.get("description", ""),
        url=base_url.rstrip("/") + "/",  # Ensure trailing slash
        version=_get_version(meta),
        preferred_transport="JSONRPC",
        protocol_version="0.3.0",
        default_input_modes=[MIME_TEXT, MIME_JSON],
        default_output_modes=[MIME_TEXT, MIME_JSON],
        capabilities=build_capabilities_from_meta(meta),
        skills=build_skills_from_meta(meta),
    )