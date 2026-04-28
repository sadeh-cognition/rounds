from __future__ import annotations

import logging
from typing import Any

from django.db import transaction

from analytics.models import (
    AnalyticsResultMetadata,
    GeneratedSQL,
    PendingClarification,
    SlackConversation,
    SlackTurn,
)

logger = logging.getLogger(__name__)


def _model_pk(instance: object) -> object:
    return getattr(instance, "pk", None)


def get_or_create_conversation(
    *,
    team_id: str,
    channel_id: str,
    thread_ts: str,
) -> SlackConversation:
    conversation, created = SlackConversation.objects.get_or_create(
        team_id=team_id,
        channel_id=channel_id,
        thread_ts=thread_ts,
    )
    logger.info(
        "Resolved Slack conversation conversation_id=%s created=%s team=%s channel=%s "
        "thread=%s",
        _model_pk(conversation),
        created,
        team_id,
        channel_id,
        thread_ts,
    )
    return conversation


def record_user_turn(
    *,
    conversation: SlackConversation,
    slack_user_id: str,
    slack_ts: str,
    text: str,
    metadata: dict[str, Any] | None = None,
) -> SlackTurn:
    turn = SlackTurn.objects.create(
        conversation=conversation,
        role=SlackTurn.Role.USER,
        slack_user_id=slack_user_id,
        slack_ts=slack_ts,
        text=text,
        metadata=metadata or {},
    )
    logger.info(
        "Recorded Slack user turn turn_id=%s conversation_id=%s user=%s slack_ts=%s "
        "text_length=%s metadata_keys=%s",
        _model_pk(turn),
        _model_pk(conversation),
        slack_user_id,
        slack_ts,
        len(text),
        sorted((metadata or {}).keys()),
    )
    return turn


def record_assistant_turn(
    *,
    conversation: SlackConversation,
    text: str,
    slack_ts: str = "",
    metadata: dict[str, Any] | None = None,
) -> SlackTurn:
    turn = SlackTurn.objects.create(
        conversation=conversation,
        role=SlackTurn.Role.ASSISTANT,
        slack_ts=slack_ts,
        text=text,
        metadata=metadata or {},
    )
    logger.info(
        "Recorded Slack assistant turn turn_id=%s conversation_id=%s slack_ts=%s "
        "text_length=%s metadata_keys=%s",
        _model_pk(turn),
        _model_pk(conversation),
        slack_ts,
        len(text),
        sorted((metadata or {}).keys()),
    )
    return turn


def upsert_pending_clarification(
    *,
    conversation: SlackConversation,
    question: str,
    context: dict[str, Any] | None = None,
) -> PendingClarification:
    clarification, created = PendingClarification.objects.update_or_create(
        conversation=conversation,
        defaults={
            "question": question,
            "context": context or {},
        },
    )
    logger.info(
        "Upserted pending clarification clarification_id=%s conversation_id=%s "
        "created=%s question_length=%s context_keys=%s",
        _model_pk(clarification),
        _model_pk(conversation),
        created,
        len(question),
        sorted((context or {}).keys()),
    )
    return clarification


def clear_pending_clarification(
    *,
    conversation: SlackConversation,
) -> PendingClarification | None:
    try:
        clarification = conversation.pending_clarification
    except PendingClarification.DoesNotExist:
        logger.info(
            "No pending clarification to clear conversation_id=%s",
            _model_pk(conversation),
        )
        return None

    clarification_id = _model_pk(clarification)
    clarification.delete()
    logger.info(
        "Cleared pending clarification clarification_id=%s conversation_id=%s",
        clarification_id,
        _model_pk(conversation),
    )
    return clarification


def record_generated_sql(
    *,
    turn: SlackTurn,
    sql: str,
    validation_status: str,
    error: str = "",
) -> GeneratedSQL:
    generated_sql = GeneratedSQL.objects.create(
        turn=turn,
        sql=sql,
        validation_status=validation_status,
        error=error,
    )
    logger.info(
        "Recorded generated SQL generated_sql_id=%s turn_id=%s conversation_id=%s "
        "validation_status=%s sql_length=%s has_error=%s",
        _model_pk(generated_sql),
        _model_pk(turn),
        _model_pk(turn.conversation),
        validation_status,
        len(sql),
        bool(error),
    )
    return generated_sql


def record_result_metadata(
    *,
    turn: SlackTurn,
    row_count: int,
    returned_row_count: int,
    truncated: bool,
    columns: list[str],
    csv_attachment_id: str = "",
    sql_attachment_id: str = "",
) -> AnalyticsResultMetadata:
    metadata, created = AnalyticsResultMetadata.objects.update_or_create(
        turn=turn,
        defaults={
            "row_count": row_count,
            "returned_row_count": returned_row_count,
            "truncated": truncated,
            "columns": columns,
            "csv_attachment_id": csv_attachment_id,
            "sql_attachment_id": sql_attachment_id,
        },
    )
    logger.info(
        "Recorded result metadata metadata_id=%s turn_id=%s conversation_id=%s "
        "created=%s row_count=%s returned_row_count=%s truncated=%s columns=%s",
        _model_pk(metadata),
        _model_pk(turn),
        _model_pk(turn.conversation),
        created,
        row_count,
        returned_row_count,
        truncated,
        columns,
    )
    return metadata


@transaction.atomic
def record_assistant_response(
    *,
    conversation: SlackConversation,
    text: str,
    slack_ts: str = "",
    metadata: dict[str, Any] | None = None,
    generated_sql: str = "",
    sql_validation_status: str = "",
    sql_error: str = "",
    result_columns: list[str] | None = None,
    row_count: int | None = None,
    returned_row_count: int | None = None,
    truncated: bool = False,
    csv_attachment_id: str = "",
    sql_attachment_id: str = "",
) -> SlackTurn:
    logger.info(
        "Recording assistant response conversation_id=%s generated_sql=%s "
        "row_count=%s returned_row_count=%s",
        _model_pk(conversation),
        bool(generated_sql),
        row_count,
        returned_row_count,
    )
    turn = record_assistant_turn(
        conversation=conversation,
        text=text,
        slack_ts=slack_ts,
        metadata=metadata,
    )
    if generated_sql:
        record_generated_sql(
            turn=turn,
            sql=generated_sql,
            validation_status=sql_validation_status or "executed",
            error=sql_error,
        )
    if row_count is not None and returned_row_count is not None:
        record_result_metadata(
            turn=turn,
            row_count=row_count,
            returned_row_count=returned_row_count,
            truncated=truncated,
            columns=result_columns or [],
            csv_attachment_id=csv_attachment_id,
            sql_attachment_id=sql_attachment_id,
        )
    return turn


def get_thread_context(
    *,
    team_id: str,
    channel_id: str,
    thread_ts: str,
    max_turns: int = 12,
) -> dict[str, Any]:
    conversation = get_or_create_conversation(
        team_id=team_id,
        channel_id=channel_id,
        thread_ts=thread_ts,
    )
    turns = (
        SlackTurn.objects.filter(conversation=conversation)
        .prefetch_related("generated_sql")
        .order_by("-created_at", "-id")[:max_turns]
    )
    ordered_turns = list(reversed(turns))

    pending_clarification = _serialize_pending_clarification(conversation)
    serialized_turns = [_serialize_turn(turn) for turn in ordered_turns]

    user_turns = [
        turn for turn in serialized_turns if turn["role"] == SlackTurn.Role.USER
    ]
    assistant_turns = [
        turn for turn in serialized_turns if turn["role"] == SlackTurn.Role.ASSISTANT
    ]
    logger.info(
        "Built Slack thread context conversation_id=%s team=%s channel=%s thread=%s "
        "turns=%s pending_clarification=%s last_user_length=%s last_assistant_length=%s",
        _model_pk(conversation),
        team_id,
        channel_id,
        thread_ts,
        len(serialized_turns),
        pending_clarification is not None,
        len(user_turns[-1]["text"]) if user_turns else 0,
        len(assistant_turns[-1]["text"]) if assistant_turns else 0,
    )

    return {
        "conversation": {
            "team_id": conversation.team_id,
            "channel_id": conversation.channel_id,
            "thread_ts": conversation.thread_ts,
        },
        "pending_clarification": pending_clarification,
        "turns": serialized_turns,
        "last_user_question": user_turns[-1]["text"] if user_turns else "",
        "last_assistant_response": assistant_turns[-1]["text"]
        if assistant_turns
        else "",
    }


def _serialize_pending_clarification(
    conversation: SlackConversation,
) -> dict[str, Any] | None:
    try:
        clarification = conversation.pending_clarification
    except PendingClarification.DoesNotExist:
        return None

    return {
        "question": clarification.question,
        "context": clarification.context,
        "created_at": clarification.created_at.isoformat(),
    }


def _serialize_turn(turn: SlackTurn) -> dict[str, Any]:
    generated_sql = [
        {
            "sql": sql.sql,
            "validation_status": sql.validation_status,
            "error": sql.error,
            "created_at": sql.created_at.isoformat(),
        }
        for sql in turn.generated_sql.all()
    ]
    result_metadata = None
    try:
        metadata = turn.result_metadata
    except AnalyticsResultMetadata.DoesNotExist:
        metadata = None
    if metadata is not None:
        result_metadata = {
            "row_count": metadata.row_count,
            "returned_row_count": metadata.returned_row_count,
            "truncated": metadata.truncated,
            "columns": metadata.columns,
            "csv_attachment_id": metadata.csv_attachment_id,
            "sql_attachment_id": metadata.sql_attachment_id,
        }

    return {
        "role": turn.role,
        "slack_user_id": turn.slack_user_id,
        "slack_ts": turn.slack_ts,
        "text": turn.text,
        "metadata": turn.metadata,
        "created_at": turn.created_at.isoformat(),
        "generated_sql": generated_sql,
        "result_metadata": result_metadata,
    }
