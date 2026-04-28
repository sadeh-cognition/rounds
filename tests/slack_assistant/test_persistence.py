from __future__ import annotations

import pytest

from analytics.models import PendingClarification, SlackConversation, SlackTurn
from slack_assistant.persistence import (
    clear_pending_clarification,
    get_or_create_conversation,
    get_thread_context,
    record_assistant_response,
    record_user_turn,
    upsert_pending_clarification,
)


@pytest.mark.django_db
def test_get_or_create_conversation_uses_slack_thread_identity() -> None:
    first = get_or_create_conversation(
        team_id="T123",
        channel_id="C123",
        thread_ts="1710000000.000001",
    )
    second = get_or_create_conversation(
        team_id="T123",
        channel_id="C123",
        thread_ts="1710000000.000001",
    )

    assert first.pk == second.pk
    assert SlackConversation.objects.count() == 1


@pytest.mark.django_db
def test_thread_context_returns_prior_turns_for_followups() -> None:
    conversation = get_or_create_conversation(
        team_id="T123",
        channel_id="C123",
        thread_ts="1710000000.000001",
    )
    record_user_turn(
        conversation=conversation,
        slack_user_id="U123",
        slack_ts="1710000000.000002",
        text="how many android apps do we have?",
    )
    record_assistant_response(
        conversation=conversation,
        text="We have 25 Android apps.",
        slack_ts="1710000000.000003",
        generated_sql="SELECT COUNT(*) FROM apps WHERE platform = 'Android'",
        row_count=1,
        returned_row_count=1,
        truncated=False,
        result_columns=["count"],
    )
    record_user_turn(
        conversation=conversation,
        slack_user_id="U123",
        slack_ts="1710000000.000004",
        text="what about iOS?",
    )

    context = get_thread_context(
        team_id="T123",
        channel_id="C123",
        thread_ts="1710000000.000001",
    )

    assert context["last_user_question"] == "what about iOS?"
    assert context["last_assistant_response"] == "We have 25 Android apps."
    assert [turn["role"] for turn in context["turns"]] == [
        SlackTurn.Role.USER,
        SlackTurn.Role.ASSISTANT,
        SlackTurn.Role.USER,
    ]
    assistant_turn = context["turns"][1]
    assert assistant_turn["generated_sql"][0]["validation_status"] == "executed"
    assert assistant_turn["result_metadata"] == {
        "row_count": 1,
        "returned_row_count": 1,
        "truncated": False,
        "columns": ["count"],
        "csv_attachment_id": "",
        "sql_attachment_id": "",
    }


@pytest.mark.django_db
def test_pending_clarification_is_upserted_and_cleared() -> None:
    conversation = get_or_create_conversation(
        team_id="T123",
        channel_id="C123",
        thread_ts="1710000000.000001",
    )

    first = upsert_pending_clarification(
        conversation=conversation,
        question="Which revenue definition should I use?",
        context={"ambiguous_term": "revenue"},
    )
    second = upsert_pending_clarification(
        conversation=conversation,
        question="Should popularity mean installs or revenue?",
        context={"ambiguous_term": "popularity"},
    )

    context = get_thread_context(
        team_id="T123",
        channel_id="C123",
        thread_ts="1710000000.000001",
    )

    assert first.pk == second.pk
    assert context["pending_clarification"]["question"] == (
        "Should popularity mean installs or revenue?"
    )
    assert context["pending_clarification"]["context"] == {
        "ambiguous_term": "popularity"
    }
    cleared = clear_pending_clarification(conversation=conversation)
    assert cleared is not None
    assert PendingClarification.objects.filter(conversation=conversation).count() == 0


@pytest.mark.django_db
def test_thread_context_is_scoped_to_one_slack_thread() -> None:
    first = get_or_create_conversation(
        team_id="T123",
        channel_id="C123",
        thread_ts="1710000000.000001",
    )
    second = get_or_create_conversation(
        team_id="T123",
        channel_id="C123",
        thread_ts="1710000000.000999",
    )
    record_user_turn(
        conversation=first,
        slack_user_id="U123",
        slack_ts="1710000000.000002",
        text="how many installs yesterday?",
    )
    record_user_turn(
        conversation=second,
        slack_user_id="U123",
        slack_ts="1710000000.001000",
        text="which apps had the most ad revenue?",
    )

    context = get_thread_context(
        team_id="T123",
        channel_id="C123",
        thread_ts="1710000000.000001",
    )

    assert context["last_user_question"] == "how many installs yesterday?"
    assert len(context["turns"]) == 1
