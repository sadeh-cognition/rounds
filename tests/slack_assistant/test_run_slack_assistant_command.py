from __future__ import annotations

import json
from datetime import timezone
from pathlib import Path
from typing import Any

from analytics.chat_schemas import AnalyticsChatResponse, AnalyticsSnippetPayload
from slack_assistant.management.commands.run_slack_assistant import (
    build_chat_request,
    infer_sql_visibility_preference,
    is_direct_user_message,
    post_chat_response,
    render_slack_message,
)


class FakeSlackClient:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.uploads: list[dict[str, Any]] = []

    def chat_postMessage(self, **kwargs: Any) -> None:
        self.messages.append(kwargs)

    def files_upload_v2(self, **kwargs: Any) -> None:
        self.uploads.append(kwargs)


def test_build_chat_request_uses_assistant_thread_identity_and_utc_timestamp() -> None:
    payload = build_chat_request(
        body={"team_id": "T123"},
        event={
            "channel": "C123",
            "thread_ts": "1710000000.000001",
            "ts": "1710000001.000002",
            "user": "U123",
            "text": "  how many apps do we have?  ",
        },
    )

    assert payload.slack_team_id == "T123"
    assert payload.slack_channel_id == "C123"
    assert payload.slack_thread_id == "1710000000.000001"
    assert payload.slack_user_id == "U123"
    assert payload.text == "how many apps do we have?"
    assert payload.utc_timestamp.tzinfo == timezone.utc
    assert payload.sql_visibility_preference == "auto"


def test_build_chat_request_uses_message_ts_for_top_level_direct_message() -> None:
    payload = build_chat_request(
        body={"team_id": "T123"},
        event={
            "type": "message",
            "channel_type": "im",
            "channel": "D123",
            "ts": "1710000001.000002",
            "user": "U123",
            "text": "how many apps do we have?",
        },
    )

    assert payload.slack_channel_id == "D123"
    assert payload.slack_thread_id == "1710000001.000002"
    assert payload.text == "how many apps do we have?"


def test_is_direct_user_message_matches_app_messages_tab_events() -> None:
    assert is_direct_user_message(
        {
            "type": "message",
            "channel_type": "im",
            "channel": "D123",
            "ts": "1710000001.000002",
            "user": "U123",
            "text": "how many apps do we have?",
        }
    )
    assert not is_direct_user_message(
        {
            "type": "message",
            "channel_type": "im",
            "channel": "D123",
            "thread_ts": "1710000000.000001",
            "ts": "1710000001.000002",
            "user": "U123",
            "text": "follow up",
        }
    )
    assert not is_direct_user_message(
        {
            "type": "message",
            "channel_type": "im",
            "channel": "D123",
            "ts": "1710000001.000002",
            "bot_id": "B123",
            "text": "bot response",
        }
    )


def test_infer_sql_visibility_preference_from_user_text() -> None:
    assert (
        infer_sql_visibility_preference("Show me the SQL for this answer")
        == "requested"
    )
    assert infer_sql_visibility_preference("Answer this without SQL") == "never"
    assert infer_sql_visibility_preference("How many apps do we have?") == "auto"


def test_render_slack_message_includes_table_and_truncation() -> None:
    response = AnalyticsChatResponse(
        message_text="Top countries by installs:",
        table_columns=["country", "installs"],
        table_rows=[
            {"country": "US", "installs": 120},
            {"country": "DE", "installs": 45},
        ],
        row_count=500,
        returned_row_count=25,
        truncated=True,
    )

    text = render_slack_message(response)

    assert "Top countries by installs:" in text
    assert "country | installs" in text
    assert "US      | 120" in text
    assert "Showing 25 of 500 returned rows." in text


def test_post_chat_response_posts_message_and_uploads_snippets() -> None:
    client = FakeSlackClient()
    response = AnalyticsChatResponse(
        message_text="Query failed once, here is the SQL.",
        csv_snippet=AnalyticsSnippetPayload(
            filename="results.csv",
            content="country,installs\nUS,120\n",
            title="Results",
            mime_type="text/csv",
        ),
        sql_snippet=AnalyticsSnippetPayload(
            filename="query.sql",
            content="select * from apps;",
            title="Generated SQL",
            mime_type="application/sql",
        ),
    )

    post_chat_response(
        client=client,  # type: ignore[arg-type]
        channel_id="C123",
        thread_ts="1710000000.000001",
        response=response,
    )

    assert client.messages == [
        {
            "channel": "C123",
            "thread_ts": "1710000000.000001",
            "text": "Query failed once, here is the SQL.",
            "unfurl_links": False,
            "unfurl_media": False,
        }
    ]
    assert [upload["snippet_type"] for upload in client.uploads] == ["csv", "sql"]
    assert [upload["filename"] for upload in client.uploads] == [
        "results.csv",
        "query.sql",
    ]


def test_post_chat_response_can_post_top_level_direct_message() -> None:
    client = FakeSlackClient()
    response = AnalyticsChatResponse(message_text="There are 2 apps.")

    post_chat_response(
        client=client,  # type: ignore[arg-type]
        channel_id="D123",
        thread_ts=None,
        response=response,
    )

    assert client.messages == [
        {
            "channel": "D123",
            "text": "There are 2 apps.",
            "unfurl_links": False,
            "unfurl_media": False,
        }
    ]


def test_first_bolt_app_manifest_supports_assistant_command() -> None:
    manifest_path = (
        Path(__file__).resolve().parents[2] / "first-bolt-app" / "manifest.json"
    )
    manifest = json.loads(manifest_path.read_text())

    assert "assistant_view" in manifest["features"]
    assert set(manifest["oauth_config"]["scopes"]["bot"]) >= {
        "assistant:write",
        "chat:write",
        "files:write",
        "im:history",
    }
    assert set(manifest["settings"]["event_subscriptions"]["bot_events"]) >= {
        "assistant_thread_started",
        "assistant_thread_context_changed",
        "message.im",
    }
    assert manifest["settings"]["socket_mode_enabled"] is True


def test_first_bolt_app_slack_hooks_use_project_uv_environment() -> None:
    hooks_path = (
        Path(__file__).resolve().parents[2] / "first-bolt-app" / ".slack" / "hooks.json"
    )
    hooks = json.loads(hooks_path.read_text())

    assert (
        hooks["hooks"]["get-hooks"]
        == "uv run python -m slack_cli_hooks.hooks.get_hooks"
    )
