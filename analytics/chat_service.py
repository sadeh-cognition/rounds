from __future__ import annotations

from django.conf import settings
from django.db import transaction

from analytics.chat_schemas import (
    AnalyticsChatRequest,
    AnalyticsChatResponse,
)
from slack_assistant.persistence import (
    clear_pending_clarification,
    get_or_create_conversation,
    get_thread_context,
    record_assistant_response,
    record_user_turn,
)


def handle_analytics_chat(payload: AnalyticsChatRequest) -> AnalyticsChatResponse:
    """Persist a Slack turn and produce the backend chat contract response."""
    conversation = get_or_create_conversation(
        team_id=payload.slack_team_id,
        channel_id=payload.slack_channel_id,
        thread_ts=payload.slack_thread_id,
    )

    with transaction.atomic():
        record_user_turn(
            conversation=conversation,
            slack_user_id=payload.slack_user_id,
            slack_ts=str(payload.utc_timestamp.timestamp()),
            text=payload.text,
            metadata={"utc_timestamp": payload.utc_timestamp.isoformat()},
        )

        thread_context = get_thread_context(
            team_id=payload.slack_team_id,
            channel_id=payload.slack_channel_id,
            thread_ts=payload.slack_thread_id,
        )

        if thread_context.get("pending_clarification"):
            clear_pending_clarification(conversation=conversation)

        response = build_agent_not_configured_response(payload)
        record_assistant_response(
            conversation=conversation,
            text=response.message_text,
            metadata={
                "response_type": "agent_not_configured",
                "sql_visibility_preference": payload.sql_visibility_preference,
            },
        )
        return response


def build_agent_not_configured_response(
    payload: AnalyticsChatRequest,
) -> AnalyticsChatResponse:
    if not getattr(settings, "LITELLM_MODEL", ""):
        message = (
            "I saved this Slack thread turn, but SQL generation is not available yet "
            "because LITELLM_MODEL is not configured for the analytics agent."
        )
    else:
        message = (
            "I saved this Slack thread turn. The analytics SQL agent will answer this "
            "question in the next implementation slice."
        )

    assumptions = ["Dates are interpreted as UTC calendar dates."]
    if payload.sql_visibility_preference == "requested":
        assumptions.append("SQL was requested")

    return AnalyticsChatResponse(
        message_text=message,
        assumptions=assumptions,
    )
