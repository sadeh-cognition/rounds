from __future__ import annotations

from typing import Any

from django.db import transaction

from analytics.models import (
    AnalyticsResultMetadata,
    GeneratedSQL,
    PendingClarification,
    SlackConversation,
    SlackTurn,
)


def get_or_create_conversation(
    *,
    team_id: str,
    channel_id: str,
    thread_ts: str,
) -> SlackConversation:
    conversation, _ = SlackConversation.objects.get_or_create(
        team_id=team_id,
        channel_id=channel_id,
        thread_ts=thread_ts,
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
    return SlackTurn.objects.create(
        conversation=conversation,
        role=SlackTurn.Role.USER,
        slack_user_id=slack_user_id,
        slack_ts=slack_ts,
        text=text,
        metadata=metadata or {},
    )


def record_assistant_turn(
    *,
    conversation: SlackConversation,
    text: str,
    slack_ts: str = "",
    metadata: dict[str, Any] | None = None,
) -> SlackTurn:
    return SlackTurn.objects.create(
        conversation=conversation,
        role=SlackTurn.Role.ASSISTANT,
        slack_ts=slack_ts,
        text=text,
        metadata=metadata or {},
    )


def upsert_pending_clarification(
    *,
    conversation: SlackConversation,
    question: str,
    context: dict[str, Any] | None = None,
) -> PendingClarification:
    clarification, _ = PendingClarification.objects.update_or_create(
        conversation=conversation,
        defaults={
            "question": question,
            "context": context or {},
        },
    )
    return clarification


def clear_pending_clarification(
    *,
    conversation: SlackConversation,
) -> PendingClarification | None:
    try:
        clarification = conversation.pending_clarification
    except PendingClarification.DoesNotExist:
        return None

    clarification.delete()
    return clarification


def record_generated_sql(
    *,
    turn: SlackTurn,
    sql: str,
    validation_status: str,
    error: str = "",
) -> GeneratedSQL:
    return GeneratedSQL.objects.create(
        turn=turn,
        sql=sql,
        validation_status=validation_status,
        error=error,
    )


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
    metadata, _ = AnalyticsResultMetadata.objects.update_or_create(
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

    user_turns = [turn for turn in serialized_turns if turn["role"] == SlackTurn.Role.USER]
    assistant_turns = [
        turn for turn in serialized_turns if turn["role"] == SlackTurn.Role.ASSISTANT
    ]

    return {
        "conversation": {
            "team_id": conversation.team_id,
            "channel_id": conversation.channel_id,
            "thread_ts": conversation.thread_ts,
        },
        "pending_clarification": pending_clarification,
        "turns": serialized_turns,
        "last_user_question": user_turns[-1]["text"] if user_turns else "",
        "last_assistant_response": assistant_turns[-1]["text"] if assistant_turns else "",
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
    if hasattr(turn, "result_metadata"):
        metadata = turn.result_metadata
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
