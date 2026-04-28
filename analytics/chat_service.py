from __future__ import annotations

import logging

from django.db import transaction

from analytics.agent_tools import SQLExecutionRecord
from analytics.agentic_qa import AgenticQAResult, answer_question_with_agent
from analytics.chat_schemas import (
    AnalyticsChatRequest,
    AnalyticsChatResponse,
)
from analytics.llm import (
    AnalyticsLLMConfig,
    AnalyticsLLMConfigurationError,
    get_analytics_llm_config,
)
from analytics.models import SlackConversation
from slack_assistant.persistence import (
    clear_pending_clarification,
    get_or_create_conversation,
    get_thread_context,
    record_assistant_turn,
    record_assistant_response,
    record_generated_sql,
    record_result_metadata,
    record_user_turn,
    upsert_pending_clarification,
)

logger = logging.getLogger(__name__)


def _model_pk(instance: object) -> object:
    return getattr(instance, "pk", None)


def handle_analytics_chat(payload: AnalyticsChatRequest) -> AnalyticsChatResponse:
    """Persist a Slack turn and produce the backend chat contract response."""
    logger.info(
        "Handling analytics chat team=%s channel=%s thread=%s user=%s text_length=%s "
        "sql_visibility=%s",
        payload.slack_team_id,
        payload.slack_channel_id,
        payload.slack_thread_id,
        payload.slack_user_id,
        len(payload.text),
        payload.sql_visibility_preference,
    )
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
    logger.info(
        "Recorded analytics user turn conversation_id=%s team=%s channel=%s thread=%s",
        _model_pk(conversation),
        payload.slack_team_id,
        payload.slack_channel_id,
        payload.slack_thread_id,
    )

    thread_context = get_thread_context(
        team_id=payload.slack_team_id,
        channel_id=payload.slack_channel_id,
        thread_ts=payload.slack_thread_id,
    )

    pending_clarification = thread_context.get("pending_clarification")
    if pending_clarification:
        logger.info(
            "Resolving pending clarification conversation_id=%s team=%s channel=%s "
            "thread=%s",
            _model_pk(conversation),
            payload.slack_team_id,
            payload.slack_channel_id,
            payload.slack_thread_id,
        )
        clear_pending_clarification(conversation=conversation)
        resolved_question = _resolve_pending_question(
            pending_clarification=pending_clarification,
            clarification_answer=payload.text,
        )
        return _answer_with_agent(
            payload=payload,
            conversation=conversation,
            question=resolved_question,
            thread_context={
                **thread_context,
                "pending_clarification": None,
                "resolved_clarification": pending_clarification,
                "last_user_question": resolved_question,
            },
            response_metadata={
                "response_type": "pending_clarification_resolved",
                "pending_clarification": pending_clarification,
                "clarification_answer": payload.text,
                "resolved_question": resolved_question,
            },
        )

    try:
        llm_config = get_analytics_llm_config()
    except AnalyticsLLMConfigurationError:
        logger.warning(
            "Analytics LLM is not configured conversation_id=%s team=%s channel=%s "
            "thread=%s",
            _model_pk(conversation),
            payload.slack_team_id,
            payload.slack_channel_id,
            payload.slack_thread_id,
        )
        response = build_agent_not_configured_response(payload)
        record_assistant_response(
            conversation=conversation,
            text=response.message_text,
            metadata={
                "response_type": "agent_not_configured",
                "sql_visibility_preference": payload.sql_visibility_preference,
            },
        )
        logger.info(
            "Returning agent-not-configured response conversation_id=%s message_length=%s",
            _model_pk(conversation),
            len(response.message_text),
        )
        return response

    return _answer_with_agent(
        payload=payload,
        conversation=conversation,
        question=payload.text,
        thread_context=thread_context,
        config=llm_config,
        response_metadata={"response_type": "agent_answered"},
    )


def _answer_with_agent(
    *,
    payload: AnalyticsChatRequest,
    conversation: SlackConversation,
    question: str,
    thread_context: dict[str, object],
    response_metadata: dict[str, object],
    config: AnalyticsLLMConfig | None = None,
) -> AnalyticsChatResponse:
    turns = thread_context.get("turns", [])
    context_turn_count = len(turns) if isinstance(turns, list) else 0
    logger.info(
        "Preparing analytics agent answer conversation_id=%s question_length=%s "
        "context_turns=%s sql_visibility=%s",
        _model_pk(conversation),
        len(question),
        context_turn_count,
        payload.sql_visibility_preference,
    )
    try:
        llm_config = config or get_analytics_llm_config()
    except AnalyticsLLMConfigurationError:
        resolved_clarification = response_metadata.get("pending_clarification")
        response = build_agent_not_configured_response(
            payload,
            resolved_clarification=resolved_clarification
            if isinstance(resolved_clarification, dict)
            else None,
        )
        record_assistant_response(
            conversation=conversation,
            text=response.message_text,
            metadata={
                **response_metadata,
                "response_type": response_metadata.get(
                    "response_type",
                    "agent_not_configured",
                ),
                "sql_visibility_preference": payload.sql_visibility_preference,
            },
        )
        logger.warning(
            "Analytics agent answer skipped because LLM config is missing "
            "conversation_id=%s response_type=%s",
            _model_pk(conversation),
            response_metadata.get("response_type", "agent_not_configured"),
        )
        return response

    try:
        logger.info(
            "Calling analytics SQL agent conversation_id=%s model=%s",
            _model_pk(conversation),
            llm_config.model_id,
        )
        result = answer_question_with_agent(
            question=question,
            conversation_context=thread_context,
            sql_visibility_preference=payload.sql_visibility_preference,
            config=llm_config,
        )
    except Exception as exc:
        logger.exception(
            "Analytics SQL agent failed conversation_id=%s error_type=%s",
            _model_pk(conversation),
            type(exc).__name__,
        )
        response = build_agent_failed_response(payload, exc)
        record_assistant_response(
            conversation=conversation,
            text=response.message_text,
            metadata={
                **response_metadata,
                "response_type": "agent_failed",
                "sql_visibility_preference": payload.sql_visibility_preference,
                "error": str(exc),
            },
        )
        return response

    response = result.response
    logger.info(
        "Analytics SQL agent returned conversation_id=%s message_length=%s "
        "executions=%s row_count=%s returned_row_count=%s clarification_required=%s",
        _model_pk(conversation),
        len(response.message_text),
        len(result.executions),
        response.row_count,
        response.returned_row_count,
        response.clarification is not None and response.clarification.required,
    )
    if response.clarification is not None and response.clarification.required:
        logger.info(
            "Persisting analytics clarification request conversation_id=%s "
            "question_length=%s",
            _model_pk(conversation),
            len(response.clarification.question),
        )
        upsert_pending_clarification(
            conversation=conversation,
            question=response.clarification.question,
            context={
                **response.clarification.context,
                "original_text": question,
                "sql_visibility_preference": payload.sql_visibility_preference,
                "utc_timestamp": payload.utc_timestamp.isoformat(),
            },
        )

    _record_agent_result(
        conversation=conversation,
        result=result,
        metadata={
            **response_metadata,
            "sql_visibility_preference": payload.sql_visibility_preference,
            "execution_count": len(result.executions),
        },
    )
    return response


@transaction.atomic
def _record_agent_result(
    *,
    conversation: SlackConversation,
    result: AgenticQAResult,
    metadata: dict[str, object],
) -> None:
    response = result.response
    turn = record_assistant_turn(
        conversation=conversation,
        text=response.message_text,
        metadata={
            **metadata,
            "raw_agent_answer": result.raw_agent_answer,
        },
    )
    logger.info(
        "Recording analytics agent result conversation_id=%s assistant_turn_id=%s "
        "executions=%s",
        _model_pk(conversation),
        _model_pk(turn),
        len(result.executions),
    )

    for execution in result.executions:
        record_generated_sql(
            turn=turn,
            sql=execution.sql,
            validation_status=execution.validation_status,
            error=execution.error,
        )

    successful_execution = _last_successful_execution(result.executions)
    if successful_execution is not None:
        logger.info(
            "Recording analytics result metadata conversation_id=%s assistant_turn_id=%s "
            "row_count=%s returned_row_count=%s truncated=%s columns=%s",
            _model_pk(conversation),
            _model_pk(turn),
            successful_execution.row_count,
            successful_execution.returned_row_count,
            successful_execution.truncated,
            successful_execution.columns,
        )
        record_result_metadata(
            turn=turn,
            row_count=successful_execution.row_count,
            returned_row_count=successful_execution.returned_row_count,
            truncated=successful_execution.truncated,
            columns=successful_execution.columns,
        )
    else:
        logger.info(
            "No successful SQL execution found conversation_id=%s assistant_turn_id=%s",
            _model_pk(conversation),
            _model_pk(turn),
        )


def _last_successful_execution(
    executions: list[SQLExecutionRecord],
) -> SQLExecutionRecord | None:
    for execution in reversed(executions):
        if execution.validation_status == "executed":
            return execution
    return None


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


def build_agent_failed_response(
    payload: AnalyticsChatRequest,
    exc: Exception,
) -> AnalyticsChatResponse:
    assumptions = ["Dates are interpreted as UTC calendar dates."]
    if payload.sql_visibility_preference == "requested":
        assumptions.append("SQL was requested")

    return AnalyticsChatResponse(
        message_text=(
            "I saved this Slack thread turn, but the analytics SQL agent could not "
            f"complete the answer: {exc}"
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
