from __future__ import annotations

from django.db import transaction

from analytics.ambiguity import AmbiguityDecision, decide_ambiguity_with_llm
from analytics.chat_schemas import (
    AnalyticsClarificationPayload,
    AnalyticsChatRequest,
    AnalyticsChatResponse,
)
from analytics.llm import (
    AnalyticsLLMConfig,
    AnalyticsLLMConfigurationError,
    get_analytics_llm_config,
)
from slack_assistant.persistence import (
    clear_pending_clarification,
    get_or_create_conversation,
    get_thread_context,
    record_assistant_response,
    record_user_turn,
    upsert_pending_clarification,
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

    pending_clarification = thread_context.get("pending_clarification")
    if pending_clarification:
        clear_pending_clarification(conversation=conversation)
        response = build_agent_not_configured_response(
            payload,
            resolved_clarification=pending_clarification,
        )
        record_assistant_response(
            conversation=conversation,
            text=response.message_text,
            metadata={
                "response_type": "pending_clarification_resolved",
                "sql_visibility_preference": payload.sql_visibility_preference,
                "pending_clarification": pending_clarification,
                "clarification_answer": payload.text,
                "resolved_question": _resolve_pending_question(
                    pending_clarification=pending_clarification,
                    clarification_answer=payload.text,
                ),
            },
        )
        return response

    try:
        llm_config = get_analytics_llm_config()
    except AnalyticsLLMConfigurationError:
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

    try:
        ambiguity = decide_ambiguity_with_llm(
            text=payload.text,
            conversation_context=thread_context,
            config=llm_config,
        )
    except Exception as exc:
        response = build_ambiguity_detection_failed_response(payload, exc)
        record_assistant_response(
            conversation=conversation,
            text=response.message_text,
            metadata={
                "response_type": "ambiguity_detection_failed",
                "sql_visibility_preference": payload.sql_visibility_preference,
                "error": str(exc),
            },
        )
        return response

    if ambiguity.needs_clarification:
        response = build_clarification_response(payload, ambiguity)
        upsert_pending_clarification(
            conversation=conversation,
            question=ambiguity.question,
            context={
                "ambiguous_term": ambiguity.ambiguous_term,
                "possible_interpretations": ambiguity.possible_interpretations,
                "original_text": payload.text,
                "sql_visibility_preference": payload.sql_visibility_preference,
                "utc_timestamp": payload.utc_timestamp.isoformat(),
            },
        )
        record_assistant_response(
            conversation=conversation,
            text=response.message_text,
            metadata={
                "response_type": "clarification_requested",
                "sql_visibility_preference": payload.sql_visibility_preference,
                "ambiguous_term": ambiguity.ambiguous_term,
            },
        )
        return response

    response = build_agent_not_configured_response(payload, config=llm_config)
    record_assistant_response(
        conversation=conversation,
        text=response.message_text,
        metadata={
            "response_type": "agent_not_implemented",
            "sql_visibility_preference": payload.sql_visibility_preference,
        },
    )
    return response


def build_agent_not_configured_response(
    payload: AnalyticsChatRequest,
    resolved_clarification: dict[str, object] | None = None,
    config: AnalyticsLLMConfig | None = None,
) -> AnalyticsChatResponse:
    if config is not None:
        message = (
            "I saved this Slack thread turn. The analytics SQL agent will answer this "
            "question in the next implementation slice."
        )
    else:
        try:
            get_analytics_llm_config()
        except AnalyticsLLMConfigurationError as exc:
            message = (
                "I saved this Slack thread turn, but SQL generation is not available yet "
                f"because {exc}"
            )
        else:
            message = (
                "I saved this Slack thread turn. The analytics SQL agent will answer this "
                "question in the next implementation slice."
            )

    assumptions = ["Dates are interpreted as UTC calendar dates."]
    if resolved_clarification is not None:
        context = resolved_clarification.get("context", {})
        if isinstance(context, dict):
            ambiguous_term = context.get("ambiguous_term")
            if isinstance(ambiguous_term, str) and ambiguous_term:
                assumptions.append(
                    f"Resolved clarification for {ambiguous_term}: {payload.text}"
                )
    if payload.sql_visibility_preference == "requested":
        assumptions.append("SQL was requested")

    return AnalyticsChatResponse(
        message_text=message,
        assumptions=assumptions,
    )


def build_clarification_response(
    payload: AnalyticsChatRequest,
    ambiguity: AmbiguityDecision,
) -> AnalyticsChatResponse:
    assumptions = ["Dates are interpreted as UTC calendar dates."]
    if payload.sql_visibility_preference == "requested":
        assumptions.append("SQL was requested")

    context = {
        "ambiguous_term": ambiguity.ambiguous_term,
        "possible_interpretations": ambiguity.possible_interpretations,
        "original_text": payload.text,
    }
    return AnalyticsChatResponse(
        message_text=ambiguity.question,
        assumptions=assumptions,
        clarification=AnalyticsClarificationPayload(
            required=True,
            question=ambiguity.question,
            context=context,
        ),
    )


def build_ambiguity_detection_failed_response(
    payload: AnalyticsChatRequest,
    exc: Exception,
) -> AnalyticsChatResponse:
    assumptions = ["Dates are interpreted as UTC calendar dates."]
    if payload.sql_visibility_preference == "requested":
        assumptions.append("SQL was requested")

    return AnalyticsChatResponse(
        message_text=(
            "I saved this Slack thread turn, but I could not check whether it needs "
            f"clarification before SQL generation: {exc}"
        ),
        assumptions=assumptions,
    )


def _resolve_pending_question(
    *,
    pending_clarification: dict[str, object],
    clarification_answer: str,
) -> str:
    context = pending_clarification.get("context", {})
    if not isinstance(context, dict):
        return clarification_answer

    original_text = context.get("original_text")
    ambiguous_term = context.get("ambiguous_term")
    if not isinstance(original_text, str) or not original_text:
        return clarification_answer
    if not isinstance(ambiguous_term, str) or not ambiguous_term:
        return f"{original_text}\nClarification: {clarification_answer}"
    return (
        f"{original_text}\n"
        f"Clarification for {ambiguous_term}: {clarification_answer}"
    )
