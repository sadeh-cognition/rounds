from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from analytics.ambiguity import (
    AmbiguityDecision,
    _build_ambiguity_messages,
    _parse_ambiguity_response,
    decide_ambiguity_with_llm,
)
from analytics.llm import AnalyticsLLMConfig


def test_ambiguity_prompt_delegates_decision_to_model() -> None:
    messages = _build_ambiguity_messages(
        text="which countries generate the most revenue?",
        conversation_context={"last_user_question": ""},
    )

    system_message = messages[0]["content"]
    assert "You decide whether" in system_message
    assert "return needs_clarification=true" in system_message
    assert "which countries generate the most revenue?" in messages[1]["content"]


def test_parse_ambiguity_response_from_structured_parsed_payload() -> None:
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    parsed=AmbiguityDecision(
                        needs_clarification=True,
                        question="Which revenue definition should I use?",
                        ambiguous_term="revenue",
                        possible_interpretations=["in-app", "ads", "total"],
                    ),
                    content="",
                )
            )
        ]
    )

    decision = _parse_ambiguity_response(response)

    assert decision.needs_clarification is True
    assert decision.question == "Which revenue definition should I use?"
    assert decision.possible_interpretations == ["in-app", "ads", "total"]


def test_parse_ambiguity_response_from_json_content() -> None:
    response = {
        "choices": [
            {
                "message": {
                    "content": (
                        '{"needs_clarification": false, "question": "", '
                        '"ambiguous_term": "", "possible_interpretations": []}'
                    )
                }
            }
        ]
    }

    decision = _parse_ambiguity_response(response)

    assert decision.needs_clarification is False
    assert decision.question == ""


@pytest.mark.skipif(
    os.environ.get("RUN_LIVE_LLM_TESTS") != "1",
    reason="Live LLM tests are gated by RUN_LIVE_LLM_TESTS=1.",
)
def test_live_llm_decides_ambiguity_for_business_term() -> None:
    model = os.environ.get("LITELLM_MODEL", "groq/llama-3.1-8b-instant")

    decision = decide_ambiguity_with_llm(
        text="which countries generate the most revenue?",
        conversation_context={"turns": []},
        config=AnalyticsLLMConfig(model_id=model, sql_repair_retries=2),
    )

    assert isinstance(decision.needs_clarification, bool)
    if decision.needs_clarification:
        assert decision.question
