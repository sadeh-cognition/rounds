from __future__ import annotations

from typing import Any

from smolagents import tool

from analytics.schema import get_analytics_schema_context


@tool
def get_schema_context(conversation_context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return allowed analytics schema and SQL rules for portfolio questions.

    Args:
        conversation_context: Optional persisted Slack thread context and prior-turn
            details that can help resolve follow-up questions.
    """
    return get_analytics_schema_context(conversation_context=conversation_context)
