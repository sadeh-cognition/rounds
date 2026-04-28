from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from ninja import Schema
from pydantic import Field, field_validator


SqlVisibilityPreference = Literal["auto", "requested", "never"]


class AnalyticsChatRequest(Schema):
    slack_team_id: str = Field(min_length=1)
    slack_channel_id: str = Field(min_length=1)
    slack_thread_id: str = Field(min_length=1)
    slack_user_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    utc_timestamp: datetime
    sql_visibility_preference: SqlVisibilityPreference = "auto"

    @field_validator("utc_timestamp")
    @classmethod
    def require_utc_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
            raise ValueError("utc_timestamp must be timezone-aware UTC")
        return value


class AnalyticsSnippetPayload(Schema):
    filename: str
    content: str
    title: str = ""
    mime_type: str = "text/plain"


class AnalyticsClarificationPayload(Schema):
    required: bool
    question: str
    context: dict[str, Any] = Field(default_factory=dict)


class AnalyticsChatResponse(Schema):
    message_text: str
    table_columns: list[str] = Field(default_factory=list)
    table_rows: list[dict[str, Any]] = Field(default_factory=list)
    csv_snippet: AnalyticsSnippetPayload | None = None
    sql_snippet: AnalyticsSnippetPayload | None = None
    clarification: AnalyticsClarificationPayload | None = None
    row_count: int = 0
    returned_row_count: int = 0
    truncated: bool = False
