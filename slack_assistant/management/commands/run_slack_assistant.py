from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin

import djclick as click
from django.conf import settings
import requests
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_bolt.middleware.assistant import Assistant
from slack_sdk.web.client import WebClient

from analytics.chat_schemas import (
    AnalyticsChatRequest,
    AnalyticsChatResponse,
    AnalyticsSnippetPayload,
    SqlVisibilityPreference,
)


ANALYTICS_CHAT_PATH = "/api/analytics/chat"


def build_chat_request(
    *,
    body: dict[str, Any],
    event: dict[str, Any],
    sql_visibility_preference: SqlVisibilityPreference | None = None,
) -> AnalyticsChatRequest:
    thread_ts = event.get("thread_ts") or event.get("ts")
    team_id = body.get("team_id") or event.get("team")
    channel_id = event.get("channel")
    user_id = event.get("user")
    text = (event.get("text") or "").strip()
    event_ts = event.get("ts")

    if (
        not thread_ts
        or not team_id
        or not channel_id
        or not user_id
        or not text
        or not event_ts
    ):
        raise ValueError("Slack assistant event is missing required chat fields.")

    return AnalyticsChatRequest(
        slack_team_id=team_id,
        slack_channel_id=channel_id,
        slack_thread_id=thread_ts,
        slack_user_id=user_id,
        text=text,
        utc_timestamp=datetime.fromtimestamp(float(event_ts), tz=timezone.utc),
        sql_visibility_preference=sql_visibility_preference
        or infer_sql_visibility_preference(text),
    )


def infer_sql_visibility_preference(text: str) -> SqlVisibilityPreference:
    normalized = text.lower()
    if any(
        phrase in normalized
        for phrase in (
            "without sql",
            "don't show sql",
            "do not show sql",
            "no sql",
        )
    ):
        return "never"
    if any(
        phrase in normalized
        for phrase in (
            "show sql",
            "show me the sql",
            "include sql",
            "attach sql",
            "with sql",
            "sql please",
        )
    ):
        return "requested"
    return "auto"


def post_analytics_chat(payload: AnalyticsChatRequest) -> AnalyticsChatResponse:
    base_url = settings.ANALYTICS_API_BASE_URL.rstrip("/") + "/"
    response = requests.post(
        urljoin(base_url, ANALYTICS_CHAT_PATH.removeprefix("/")),
        json=payload.model_dump(mode="json"),
        timeout=getattr(settings, "ANALYTICS_API_TIMEOUT_SECONDS", 30),
    )
    response.raise_for_status()
    return AnalyticsChatResponse.model_validate(response.json())


def render_slack_message(response: AnalyticsChatResponse) -> str:
    parts = [response.message_text]

    if response.table_columns and response.table_rows:
        parts.append(render_slack_table(response.table_columns, response.table_rows))

    if response.assumptions:
        assumptions = "\n".join(f"- {assumption}" for assumption in response.assumptions)
        parts.append(f"*Assumptions*\n{assumptions}")

    if response.truncated:
        parts.append(
            f"Showing {response.returned_row_count} of {response.row_count} returned rows."
        )

    return "\n\n".join(part for part in parts if part)


def render_slack_table(columns: list[str], rows: list[dict[str, Any]]) -> str:
    values = [[_cell_text(row.get(column)) for column in columns] for row in rows]
    widths = [
        max(len(column), *(len(row[index]) for row in values))
        for index, column in enumerate(columns)
    ]
    header = " | ".join(column.ljust(widths[index]) for index, column in enumerate(columns))
    divider = "-+-".join("-" * width for width in widths)
    body = [
        " | ".join(row[index].ljust(widths[index]) for index in range(len(columns)))
        for row in values
    ]
    return "```" + "\n".join([header, divider, *body]) + "```"


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def post_chat_response(
    *,
    client: WebClient,
    channel_id: str,
    thread_ts: str,
    response: AnalyticsChatResponse,
) -> None:
    client.chat_postMessage(
        channel=channel_id,
        thread_ts=thread_ts,
        text=render_slack_message(response),
        unfurl_links=False,
        unfurl_media=False,
    )

    for snippet in (response.csv_snippet, response.sql_snippet):
        if snippet is not None:
            upload_snippet(
                client=client,
                channel_id=channel_id,
                thread_ts=thread_ts,
                snippet=snippet,
            )


def upload_snippet(
    *,
    client: WebClient,
    channel_id: str,
    thread_ts: str,
    snippet: AnalyticsSnippetPayload,
) -> None:
    client.files_upload_v2(
        channel=channel_id,
        thread_ts=thread_ts,
        filename=snippet.filename,
        title=snippet.title or snippet.filename,
        content=snippet.content,
        snippet_type=_snippet_type(snippet),
    )


def _snippet_type(snippet: AnalyticsSnippetPayload) -> str | None:
    if snippet.filename.endswith(".sql") or snippet.mime_type == "application/sql":
        return "sql"
    if snippet.filename.endswith(".csv") or snippet.mime_type == "text/csv":
        return "csv"
    return None


@click.command()
def command() -> None:
    """Run the Slack AI Assistant bot in Socket Mode."""
    if not settings.SLACK_BOT_TOKEN:
        raise click.ClickException("SLACK_BOT_TOKEN is required.")
    if not settings.SLACK_APP_TOKEN:
        raise click.ClickException("SLACK_APP_TOKEN is required.")

    app = App(token=settings.SLACK_BOT_TOKEN)
    assistant = Assistant()
    app.use(assistant)

    @assistant.thread_started
    def handle_thread_started(set_title, set_suggested_prompts) -> None:
        set_title("Portfolio analytics")
        set_suggested_prompts(
            prompts=[
                {
                    "title": "Top countries",
                    "message": "Which countries have the most installs this month?",
                },
                {
                    "title": "Revenue definition",
                    "message": "Which countries generate the most revenue?",
                },
            ]
        )

    @assistant.user_message
    def handle_user_message(body, event, client, set_status, logger) -> None:
        channel_id = event.get("channel")
        thread_ts = event.get("thread_ts") or event.get("ts")
        try:
            set_status("Reading analytics data")
            payload = build_chat_request(body=body, event=event)
            response = post_analytics_chat(payload)
            post_chat_response(
                client=client,
                channel_id=channel_id,
                thread_ts=thread_ts,
                response=response,
            )
            set_status("")
        except Exception:
            logger.exception("Slack analytics assistant request failed")
            if channel_id and thread_ts:
                client.chat_postMessage(
                    channel=channel_id,
                    thread_ts=thread_ts,
                    text=(
                        "I could not reach the analytics backend or format its response. "
                        "Please try again once the local API is running."
                    ),
                )
            set_status("")

    SocketModeHandler(app, settings.SLACK_APP_TOKEN).start()
