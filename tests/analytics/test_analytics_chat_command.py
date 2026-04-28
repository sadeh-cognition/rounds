from __future__ import annotations

from datetime import datetime, timezone
import json

import pytest
from django.core.management import call_command
from rich.console import Console

from analytics.chat_schemas import AnalyticsChatResponse
from analytics.management.commands.analytics_chat import (
    build_cli_chat_request,
    render_cli_response,
)
from analytics.models import SlackConversation, SlackTurn


def test_build_cli_chat_request_uses_cli_identity_and_utc_timestamp() -> None:
    timestamp = datetime(2026, 4, 28, 8, 30, tzinfo=timezone.utc)

    payload = build_cli_chat_request(
        text="  how many apps do we have?  ",
        thread_id="demo-thread",
        sql_visibility_preference="requested",
        utc_timestamp=timestamp,
    )

    assert payload.slack_team_id == "CLI"
    assert payload.slack_channel_id == "CLI"
    assert payload.slack_thread_id == "demo-thread"
    assert payload.slack_user_id == "cli-user"
    assert payload.text == "how many apps do we have?"
    assert payload.utc_timestamp == timestamp
    assert payload.sql_visibility_preference == "requested"


def test_render_cli_response_includes_table_and_truncation() -> None:
    console = Console(record=True, force_terminal=False, width=120)
    response = AnalyticsChatResponse(
        message_text="Top countries by installs:",
        table_columns=["country", "installs"],
        table_rows=[{"country": "US", "installs": 120}],
        row_count=500,
        returned_row_count=25,
        truncated=True,
    )

    render_cli_response(response, console=console)
    text = console.export_text()

    assert "Top countries by installs:" in text
    assert "country" in text
    assert "installs" in text
    assert "US" in text
    assert "120" in text
    assert "Showing 25 of 500 returned rows." in text


@pytest.mark.django_db
def test_analytics_chat_command_triggers_handle_analytics_chat_without_llm_config(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("LITELLM_MODEL", raising=False)

    call_command(
        "analytics_chat",
        "how",
        "many",
        "apps",
        "do",
        "we",
        "have?",
        "--thread-id",
        "demo-thread",
        "--show-sql",
    )

    captured = capsys.readouterr()
    assert "SQL generation is not available yet" in captured.out

    conversation = SlackConversation.objects.get(
        team_id="CLI",
        channel_id="CLI",
        thread_ts="demo-thread",
    )
    assert list(conversation.turns.values_list("role", flat=True)) == [
        SlackTurn.Role.USER,
        SlackTurn.Role.ASSISTANT,
    ]
    assistant_turn = conversation.turns.get(role=SlackTurn.Role.ASSISTANT)
    assert assistant_turn.metadata["response_type"] == "agent_not_configured"
    assert assistant_turn.metadata["sql_visibility_preference"] == "requested"


@pytest.mark.django_db
def test_analytics_chat_command_can_print_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("LITELLM_MODEL", raising=False)

    call_command(
        "analytics_chat",
        "how many apps do we have?",
        "--thread-id",
        "json-thread",
        "--json-output",
    )

    body = json.loads(capsys.readouterr().out)
    response = AnalyticsChatResponse.model_validate(body)
    assert "SQL generation is not available yet" in response.message_text
    assert response.table_rows == []


def test_analytics_chat_command_rejects_conflicting_sql_options() -> None:
    with pytest.raises(Exception, match="cannot be used together"):
        call_command(
            "analytics_chat",
            "how many apps do we have?",
            "--show-sql",
            "--hide-sql",
        )
