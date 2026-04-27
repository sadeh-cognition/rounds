from __future__ import annotations

from datetime import datetime, timezone

import pytest
from ninja.testing import TestClient

from analytics.chat_schemas import AnalyticsChatRequest, AnalyticsChatResponse
from analytics.models import PendingClarification, SlackConversation, SlackTurn
from config.api import api


client = TestClient(api)


def _payload(**overrides: object) -> dict[str, object]:
    payload = AnalyticsChatRequest(
        slack_team_id="T123",
        slack_channel_id="C123",
        slack_thread_id="1710000000.000001",
        slack_user_id="U123",
        text="how many apps do we have?",
        utc_timestamp=datetime(2026, 4, 27, 12, 0, tzinfo=timezone.utc),
        sql_visibility_preference="auto",
    ).model_dump(mode="json")
    payload.update(overrides)
    return payload


@pytest.mark.django_db
def test_chat_api_does_not_heuristically_clarify_revenue_and_persists_turns() -> None:
    response = client.post(
        "/analytics/chat",
        json=_payload(text="which countries generate the most revenue?"),
    )

    assert response.status_code == 200
    body = AnalyticsChatResponse.model_validate(response.json())
    assert body.clarification is None
    assert body.table_rows == []

    conversation = SlackConversation.objects.get()
    assert not PendingClarification.objects.filter(conversation=conversation).exists()
    assert list(conversation.turns.values_list("role", flat=True)) == [
        SlackTurn.Role.USER,
        SlackTurn.Role.ASSISTANT,
    ]


@pytest.mark.django_db
def test_chat_api_does_not_heuristically_clarify_popularity() -> None:
    response = client.post(
        "/analytics/chat",
        json=_payload(text="List all iOS apps sorted by their popularity"),
    )

    assert response.status_code == 200
    body = AnalyticsChatResponse.model_validate(response.json())
    assert body.clarification is None
    assert PendingClarification.objects.count() == 0


@pytest.mark.django_db
def test_chat_api_records_sql_visibility_preference_without_generating_sql(
    settings,
) -> None:
    settings.LITELLM_MODEL = ""

    response = client.post(
        "/analytics/chat",
        json=_payload(
            text="how many apps do we have?",
            sql_visibility_preference="requested",
        ),
    )

    assert response.status_code == 200
    body = AnalyticsChatResponse.model_validate(response.json())
    assert body.clarification is None
    assert body.sql_snippet is None
    assert "SQL was requested" in body.assumptions
    assert body.row_count == 0
    assert body.truncated is False

    assistant_turn = SlackTurn.objects.get(role=SlackTurn.Role.ASSISTANT)
    assert assistant_turn.metadata == {
        "response_type": "agent_not_configured",
        "sql_visibility_preference": "requested",
    }


@pytest.mark.django_db
def test_chat_api_rejects_non_utc_timestamp() -> None:
    response = client.post(
        "/analytics/chat",
        json=_payload(utc_timestamp="2026-04-27T12:00:00"),
    )

    assert response.status_code == 422
    assert SlackConversation.objects.count() == 0
