from __future__ import annotations

from datetime import datetime, timezone
import logging
from pathlib import Path
import sys
from typing import Any, cast
from urllib.parse import urljoin

import djclick as click
from django.conf import settings
from loguru import logger
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
app_logger = logger
SLACK_ASSISTANT_LOG_FILE = Path.home() / ".slack" / "logs" / "slack-assistant.log"


def configure_slack_assistant_logging() -> None:
    log_path = Path(
        getattr(settings, "SLACK_ASSISTANT_LOG_FILE", str(SLACK_ASSISTANT_LOG_FILE))
    ).expanduser()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.add(sys.stderr, level="DEBUG")
    logger.add(
        log_path,
        level="DEBUG",
        rotation="10 MB",
        retention=5,
        enqueue=True,
        backtrace=True,
        diagnose=True,
    )
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.StreamHandler(sys.stderr), logging.FileHandler(log_path)],
        force=True,
    )
    for logger_name in ("slack_bolt", "slack_sdk", "slack_sdk.socket_mode"):
        logging.getLogger(logger_name).setLevel(logging.DEBUG)
    logger.info("Slack assistant file logging configured path={}", log_path)


def log_slack_event_received(
    surface: str, body: dict[str, Any], event: dict[str, Any]
) -> None:
    logger.info(
        "Received Slack {} event type={} subtype={} team={} channel={} channel_type={} "
        "thread={} ts={} user={} bot_id={} text_length={}",
        surface,
        event.get("type"),
        event.get("subtype"),
        body.get("team_id") or event.get("team"),
        event.get("channel"),
        event.get("channel_type"),
        event.get("thread_ts"),
        event.get("ts"),
        event.get("user"),
        event.get("bot_id"),
        len(event.get("text") or ""),
    )


def is_direct_user_message(event: dict[str, Any]) -> bool:
    return (
        event.get("type") == "message"
        and event.get("channel_type") == "im"
        and event.get("bot_id") is None
        and event.get("subtype") in (None, "file_share")
        and event.get("thread_ts") is None
    )


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

    missing_fields = [
        field
        for field, value in {
            "thread_ts": thread_ts,
            "team_id": team_id,
            "channel_id": channel_id,
            "user_id": user_id,
            "text": text,
            "event_ts": event_ts,
        }.items()
        if not value
    ]
    if missing_fields:
        logger.warning(
            "Slack assistant event is missing required chat fields missing={} "
            "body_keys={} event_keys={} event_type={} channel_type={} subtype={}",
            missing_fields,
            sorted(body.keys()),
            sorted(event.keys()),
            event.get("type"),
            event.get("channel_type"),
            event.get("subtype"),
        )
        raise ValueError("Slack assistant event is missing required chat fields.")

    team_id = cast(str, team_id)
    channel_id = cast(str, channel_id)
    thread_ts = cast(str, thread_ts)
    user_id = cast(str, user_id)
    event_ts = cast(str, event_ts)
    payload = AnalyticsChatRequest(
        slack_team_id=team_id,
        slack_channel_id=channel_id,
        slack_thread_id=thread_ts,
        slack_user_id=user_id,
        text=text,
        utc_timestamp=datetime.fromtimestamp(float(event_ts), tz=timezone.utc),
        sql_visibility_preference=sql_visibility_preference
        or infer_sql_visibility_preference(text),
    )
    logger.info(
        "Built analytics chat payload team={} channel={} thread={} user={} "
        "event_ts={} text_length={} sql_visibility={}",
        payload.slack_team_id,
        payload.slack_channel_id,
        payload.slack_thread_id,
        payload.slack_user_id,
        payload.utc_timestamp.isoformat(),
        len(payload.text),
        payload.sql_visibility_preference,
    )
    return payload


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
    url = urljoin(base_url, ANALYTICS_CHAT_PATH.removeprefix("/"))
    logger.info(
        "Posting analytics chat request url={} team={} channel={} thread={} user={} "
        "text_length={} sql_visibility={}",
        url,
        payload.slack_team_id,
        payload.slack_channel_id,
        payload.slack_thread_id,
        payload.slack_user_id,
        len(payload.text),
        payload.sql_visibility_preference,
    )
    response = requests.post(
        url,
        json=payload.model_dump(mode="json"),
        timeout=getattr(settings, "ANALYTICS_API_TIMEOUT_SECONDS", 30),
    )
    logger.info(
        "Analytics chat response received status_code={} content_type={} bytes={}",
        response.status_code,
        response.headers.get("content-type"),
        len(response.content),
    )
    if response.status_code >= 400:
        logger.warning(
            "Analytics chat request failed status_code={} response_text={}",
            response.status_code,
            response.text[:1000],
        )
    response.raise_for_status()
    chat_response = AnalyticsChatResponse.model_validate(response.json())
    logger.info(
        "Parsed analytics chat response message_length={} rows={} returned_rows={} "
        "truncated={} csv_snippet={} sql_snippet={}",
        len(chat_response.message_text),
        chat_response.row_count,
        chat_response.returned_row_count,
        chat_response.truncated,
        chat_response.csv_snippet is not None,
        chat_response.sql_snippet is not None,
    )
    return chat_response


def render_slack_message(response: AnalyticsChatResponse) -> str:
    parts = [response.message_text]

    if response.table_columns and response.table_rows:
        parts.append(render_slack_table(response.table_columns, response.table_rows))

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
    header = " | ".join(
        column.ljust(widths[index]) for index, column in enumerate(columns)
    )
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
    thread_ts: str | None,
    response: AnalyticsChatResponse,
) -> None:
    rendered_message = render_slack_message(response)
    message_kwargs: dict[str, Any] = {
        "channel": channel_id,
        "text": rendered_message,
        "unfurl_links": False,
        "unfurl_media": False,
    }
    if thread_ts:
        message_kwargs["thread_ts"] = thread_ts

    logger.info(
        "Posting Slack response channel={} thread={} text_length={} csv_snippet={} "
        "sql_snippet={}",
        channel_id,
        thread_ts,
        len(rendered_message),
        response.csv_snippet is not None,
        response.sql_snippet is not None,
    )
    result = client.chat_postMessage(**message_kwargs)
    logger.info(
        "Slack chat_postMessage completed result_type={}", type(result).__name__
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
    thread_ts: str | None,
    snippet: AnalyticsSnippetPayload,
) -> None:
    upload_kwargs: dict[str, Any] = {
        "channel": channel_id,
        "filename": snippet.filename,
        "title": snippet.title or snippet.filename,
        "content": snippet.content,
        "snippet_type": _snippet_type(snippet),
    }
    if thread_ts:
        upload_kwargs["thread_ts"] = thread_ts
    logger.info(
        "Uploading Slack snippet channel={} thread={} filename={} snippet_type={} bytes={}",
        channel_id,
        thread_ts,
        snippet.filename,
        upload_kwargs["snippet_type"],
        len(snippet.content.encode()),
    )
    result = client.files_upload_v2(**upload_kwargs)
    logger.info("Slack files_upload_v2 completed result_type={}", type(result).__name__)


def _snippet_type(snippet: AnalyticsSnippetPayload) -> str | None:
    if snippet.filename.endswith(".sql") or snippet.mime_type == "application/sql":
        return "sql"
    if snippet.filename.endswith(".csv") or snippet.mime_type == "text/csv":
        return "csv"
    return None


def handle_slack_chat_event(
    *,
    body: dict[str, Any],
    event: dict[str, Any],
    client: WebClient,
    set_status: Any | None = None,
    post_in_thread: bool = True,
) -> None:
    channel_id = event.get("channel")
    thread_ts = event.get("thread_ts") or event.get("ts")
    response_thread_ts = thread_ts if post_in_thread else None
    try:
        logger.info(
            "Handling Slack user message team={} channel={} thread={} ts={}",
            body.get("team_id") or event.get("team"),
            channel_id,
            thread_ts,
            event.get("ts"),
        )
        if set_status is not None:
            logger.info("Setting Slack assistant status: Reading analytics data")
            set_status("Reading analytics data")
        payload = build_chat_request(body=body, event=event)
        response = post_analytics_chat(payload)
        post_chat_response(
            client=client,
            channel_id=payload.slack_channel_id,
            thread_ts=response_thread_ts,
            response=response,
        )
        if set_status is not None:
            logger.info("Clearing Slack assistant status after successful response")
            set_status("")
    except Exception:
        logger.exception("Slack analytics assistant request failed")
        if channel_id and thread_ts:
            logger.info(
                "Posting Slack failure response channel={} thread={}",
                channel_id,
                thread_ts,
            )
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=(
                    "I could not reach the analytics backend or format its response. "
                    "Please try again once the local API is running."
                ),
            )
        if set_status is not None:
            logger.info("Clearing Slack assistant status after failure")
            set_status("")


@click.command()
def command() -> None:
    """Run the Slack AI Assistant bot in Socket Mode."""
    configure_slack_assistant_logging()
    if not settings.SLACK_BOT_TOKEN:
        raise click.ClickException("SLACK_BOT_TOKEN is required.")
    if not settings.SLACK_APP_TOKEN:
        raise click.ClickException("SLACK_APP_TOKEN is required.")

    logger.info(
        "Configuring Slack analytics assistant api_base_url={} api_timeout_seconds={} "
        "bot_token_configured={} app_token_configured={}",
        settings.ANALYTICS_API_BASE_URL,
        getattr(settings, "ANALYTICS_API_TIMEOUT_SECONDS", 30),
        bool(settings.SLACK_BOT_TOKEN),
        bool(settings.SLACK_APP_TOKEN),
    )

    app = App(token=settings.SLACK_BOT_TOKEN)
    assistant = Assistant()
    app.use(assistant)

    @assistant.thread_started
    def handle_thread_started(set_title, set_suggested_prompts) -> None:
        logger.info("Slack assistant thread_started event received")
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
        log_slack_event_received("assistant.user_message", body, event)
        handle_slack_chat_event(
            body=body,
            event=event,
            client=client,
            set_status=set_status,
        )

    @app.event("message")
    def handle_direct_message(body, event, client, logger) -> None:
        log_slack_event_received("message", body, event)
        if not is_direct_user_message(event):
            app_logger.info(
                "Ignoring Slack message event type={} subtype={} channel_type={} "
                "thread={} bot_id={} user={}",
                event.get("type"),
                event.get("subtype"),
                event.get("channel_type"),
                event.get("thread_ts"),
                event.get("bot_id"),
                event.get("user"),
            )
            return
        handle_slack_chat_event(
            body=body,
            event=event,
            client=client,
            post_in_thread=False,
        )

    @app.error
    def handle_bolt_error(error, body, logger) -> None:
        app_logger.opt(exception=error).error(
            "Slack Bolt error body_type={} body_keys={}",
            type(body).__name__,
            sorted(body.keys()) if isinstance(body, dict) else None,
        )

    logger.info("Starting Slack analytics assistant in Socket Mode")
    SocketModeHandler(app, settings.SLACK_APP_TOKEN).start()
