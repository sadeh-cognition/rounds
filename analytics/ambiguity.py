from __future__ import annotations

import json
from typing import Any

import litellm
from pydantic import BaseModel, Field, ValidationError, field_validator

from analytics.llm import AnalyticsLLMConfig
from analytics.schema import get_analytics_schema_context


class AmbiguityDecision(BaseModel):
    """Structured model decision for whether a user turn needs clarification."""

    needs_clarification: bool
    question: str = ""
    ambiguous_term: str = ""
    possible_interpretations: list[str] = Field(default_factory=list)

    @field_validator("question")
    @classmethod
    def require_free_text_question_when_needed(cls, value: str, info) -> str:
        needs_clarification = bool(info.data.get("needs_clarification"))
        if needs_clarification and not value.strip():
            raise ValueError("question is required when clarification is needed")
        return value.strip()

    @field_validator("ambiguous_term")
    @classmethod
    def strip_ambiguous_term(cls, value: str) -> str:
        return value.strip()


def decide_ambiguity_with_llm(
    *,
    text: str,
    conversation_context: dict[str, Any],
    config: AnalyticsLLMConfig,
) -> AmbiguityDecision:
    """Ask the configured LLM whether this turn needs clarification first."""
    response = litellm.completion(
        model=config.model_id,
        messages=_build_ambiguity_messages(
            text=text,
            conversation_context=conversation_context,
        ),
        response_format=AmbiguityDecision,
        temperature=0,
    )
    return _parse_ambiguity_response(response)


def _build_ambiguity_messages(
    *,
    text: str,
    conversation_context: dict[str, Any],
) -> list[dict[str, str]]:
    schema_context = get_analytics_schema_context(
        conversation_context=conversation_context,
    )
    return [
        {
            "role": "system",
            "content": (
                "You decide whether a Slack portfolio analytics question must be "
                "clarified before SQL is generated. Use the available schema, metric "
                "definitions, prior thread context, and ordinary business language. "
                "If the user's request can be answered with the schema and context, "
                "return needs_clarification=false. If an important business term, "
                "metric, entity, time period, grouping, or comparison target is unclear, "
                "return needs_clarification=true and write one concise free-text "
                "clarification question. Do not answer the analytics question."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "user_text": text,
                    "schema_context": schema_context,
                },
                default=str,
            ),
        },
    ]


def _parse_ambiguity_response(response: Any) -> AmbiguityDecision:
    parsed = _get_nested_attr(response, ("choices", 0, "message", "parsed"))
    if isinstance(parsed, AmbiguityDecision):
        return parsed
    if isinstance(parsed, dict):
        return AmbiguityDecision.model_validate(parsed)

    content = _get_nested_attr(response, ("choices", 0, "message", "content"))
    if not isinstance(content, str):
        raise ValueError("LLM ambiguity decision did not include text content.")

    try:
        return AmbiguityDecision.model_validate_json(content)
    except ValidationError:
        return AmbiguityDecision.model_validate(json.loads(content))


def _get_nested_attr(value: Any, path: tuple[str | int, ...]) -> Any:
    current = value
    for key in path:
        if isinstance(key, int):
            try:
                current = current[key]
            except (IndexError, TypeError):
                return None
            continue

        if isinstance(current, dict):
            current = current.get(key)
        else:
            current = getattr(current, key, None)
        if current is None:
            return None
    return current
