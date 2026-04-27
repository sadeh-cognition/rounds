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
def test_chat_api_without_llm_config_does_not_make_local_ambiguity_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LITELLM_MODEL", raising=False)

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
    assistant_turn = conversation.turns.get(role=SlackTurn.Role.ASSISTANT)
    assert assistant_turn.metadata["response_type"] == "agent_not_configured"


@pytest.mark.django_db
def test_chat_api_clarification_response_is_persisted_when_model_decides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from analytics.ambiguity import AmbiguityDecision

    monkeypatch.setenv("LITELLM_MODEL", "groq/llama-3.1-8b-instant")
    monkeypatch.setattr(
        "analytics.chat_service.decide_ambiguity_with_llm",
        lambda **_: AmbiguityDecision(
            needs_clarification=True,
            question="Which revenue definition should I use?",
            ambiguous_term="revenue",
            possible_interpretations=["in-app revenue", "ads revenue", "total revenue"],
        ),
    )

    response = client.post(
        "/analytics/chat",
        json=_payload(text="which countries generate the most revenue?"),
    )

    assert response.status_code == 200
    body = AnalyticsChatResponse.model_validate(response.json())
    assert body.message_text == "Which revenue definition should I use?"
    assert body.clarification is not None
    assert body.clarification.required is True
    assert body.clarification.context == {
        "ambiguous_term": "revenue",
        "possible_interpretations": [
            "in-app revenue",
            "ads revenue",
            "total revenue",
        ],
        "original_text": "which countries generate the most revenue?",
    }

    pending = PendingClarification.objects.get()
    assert pending.question == "Which revenue definition should I use?"
    assert pending.context["possible_interpretations"] == [
        "in-app revenue",
        "ads revenue",
        "total revenue",
    ]


@pytest.mark.django_db
def test_chat_api_resolves_pending_clarification_from_next_reply() -> None:
    conversation = SlackConversation.objects.create(
        team_id="T123",
        channel_id="C123",
        thread_ts="1710000000.000001",
    )
    PendingClarification.objects.create(
        conversation=conversation,
        question="Which revenue definition should I use?",
        context={
            "ambiguous_term": "revenue",
            "possible_interpretations": [
                "in-app revenue",
                "ads revenue",
                "total revenue",
            ],
            "original_text": "which countries generate the most revenue?",
        },
    )

    response = client.post(
        "/analytics/chat",
        json=_payload(
            text="Use total revenue",
            utc_timestamp="2026-04-27T12:01:00Z",
        ),
    )

    assert response.status_code == 200
    body = AnalyticsChatResponse.model_validate(response.json())
    assert body.clarification is None
    assert "Resolved clarification for revenue: Use total revenue" in body.assumptions
    assert PendingClarification.objects.count() == 0

    assistant_turn = SlackTurn.objects.filter(role=SlackTurn.Role.ASSISTANT).latest("id")
    assert assistant_turn.metadata["response_type"] == "pending_clarification_resolved"
    assert assistant_turn.metadata["clarification_answer"] == "Use total revenue"
    assert assistant_turn.metadata["resolved_question"] == (
        "which countries generate the most revenue?\n"
        "Clarification for revenue: Use total revenue"
    )


@pytest.mark.django_db
def test_chat_api_records_sql_visibility_preference_without_generating_sql(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LITELLM_MODEL", raising=False)

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
