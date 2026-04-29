from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Literal

from loguru import logger

from pydantic import BaseModel, Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from smolagents import LiteLLMModel, ToolCallingAgent, tool

from analytics.agent_tools import get_schema_context, get_today_date, run_readonly_sql


class AnalyticsLLMConfigurationError(ValueError):
    """Raised when the analytics agent cannot be configured from environment."""


@dataclass(frozen=True)
class AnalyticsLLMConfig:
    model_id: str
    sql_repair_retries: int = 2


class AnalyticsLLMSettings(BaseSettings):
    """Environment-backed settings for the analytics LLM runtime."""

    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    litellm_model: str = Field(default="", validation_alias="LITELLM_MODEL")
    analytics_sql_repair_retries: int = Field(
        default=2,
        validation_alias="ANALYTICS_SQL_REPAIR_RETRIES",
    )

    @field_validator("litellm_model")
    @classmethod
    def require_litellm_model(cls, value: str) -> str:
        model_id = value.strip()
        if not model_id:
            raise ValueError(
                "LITELLM_MODEL must be configured for the analytics agent."
            )
        return model_id

    @field_validator("analytics_sql_repair_retries", mode="before")
    @classmethod
    def require_positive_sql_repair_retries(cls, value: int | str | float) -> int:
        try:
            retries = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "ANALYTICS_SQL_REPAIR_RETRIES must be a positive integer."
            ) from exc

        if retries <= 0:
            raise ValueError("ANALYTICS_SQL_REPAIR_RETRIES must be a positive integer.")
        return retries


@dataclass(frozen=True)
class AnalyticsAgentRuntime:
    agent: ToolCallingAgent
    config: AnalyticsLLMConfig


ResultPresentationFormat = Literal["plain_text", "detailed_table"]


class ResultPresentationDecision(BaseModel):
    presentation_format: ResultPresentationFormat
    rationale: str = ""


_analytics_llm_config: AnalyticsLLMConfig | None = None


def get_analytics_llm_config() -> AnalyticsLLMConfig:
    """Load the analytics LLM configuration from environment variables.

    `LITELLM_MODEL` must include the provider/model identifier expected by
    LiteLLM, for example `groq/llama-3.1-8b-instant`. Provider API keys are
    intentionally left in the process environment for LiteLLM to resolve.
    """
    try:
        env_settings = AnalyticsLLMSettings()
    except ValidationError as exc:
        raise AnalyticsLLMConfigurationError(_format_settings_error(exc)) from exc

    return AnalyticsLLMConfig(
        model_id=env_settings.litellm_model,
        sql_repair_retries=env_settings.analytics_sql_repair_retries,
    )


def configure_analytics_llm() -> AnalyticsLLMConfig:
    """Load and cache the analytics LLM configuration during app startup."""
    global _analytics_llm_config
    _analytics_llm_config = get_analytics_llm_config()
    logger.info(
        f"Analytics LLM config loaded model_id={_analytics_llm_config.model_id}, sql_repair_retries={_analytics_llm_config.sql_repair_retries}",
    )
    return _analytics_llm_config


def get_configured_analytics_llm_config() -> AnalyticsLLMConfig:
    """Return the startup-loaded analytics LLM configuration."""
    if _analytics_llm_config is None:
        raise AnalyticsLLMConfigurationError(
            "Analytics LLM configuration has not been loaded at app startup."
        )
    return _analytics_llm_config


def build_litellm_model(config: AnalyticsLLMConfig | None = None) -> LiteLLMModel:
    """Create the smolagents LiteLLM model using only env/settings config."""
    resolved_config = config or get_configured_analytics_llm_config()
    return LiteLLMModel(model_id=resolved_config.model_id)


@tool
def decide_result_presentation(
    question: str,
    columns_json: str = "[]",
    rows_json: str = "[]",
    row_count: int = 0,
) -> dict[str, str]:
    """Decide whether analytics results should be plain text or a detailed table.

    Args:
        question: The user's analytics question.
        columns_json: JSON array of result column names returned by SQL.
        rows_json: JSON array of result rows returned by SQL, preferably limited to
            a representative sample.
        row_count: Total number of rows in the SQL result.
    """
    columns = _safe_json_list(columns_json)
    rows = _safe_json_list(rows_json)
    decision = _ask_result_presentation_model(
        question=question,
        columns=columns,
        rows=rows,
        row_count=row_count,
    )
    return decision.model_dump()


def _ask_result_presentation_model(
    *,
    question: str,
    columns: list[Any],
    rows: list[Any],
    row_count: int,
) -> ResultPresentationDecision:
    model = build_litellm_model()
    message = model.generate(
        [
            {
                "role": "system",
                "content": (
                    "You choose the best display format for analytics query results. "
                    "Return JSON only. Use plain_text for scalar, single-row, or "
                    "short results that are easier to read in prose. Use "
                    "detailed_table for multi-row, grouped, ranked, comparative, "
                    "or wide results where rows and columns matter."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "question": question,
                        "columns": columns,
                        "sample_rows": rows[:10],
                        "row_count": row_count,
                        "allowed_presentation_formats": [
                            "plain_text",
                            "detailed_table",
                        ],
                        "required_json_schema": {
                            "presentation_format": "plain_text | detailed_table",
                            "rationale": "Brief reason for the decision.",
                        },
                    },
                    default=str,
                ),
            },
        ],
        response_format={"type": "json_object"},
    )
    return _parse_result_presentation_decision(message.content)


def _parse_result_presentation_decision(raw_content: Any) -> ResultPresentationDecision:
    if isinstance(raw_content, dict):
        return ResultPresentationDecision.model_validate(raw_content)

    if isinstance(raw_content, list):
        raw_content = "".join(
            str(part.get("text", part)) if isinstance(part, dict) else str(part)
            for part in raw_content
        )

    parsed = json.loads(str(raw_content).strip())
    return ResultPresentationDecision.model_validate(parsed)


def _safe_json_list(raw_json: str) -> list[Any]:
    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return parsed


def build_analytics_agent_runtime(
    config: AnalyticsLLMConfig | None = None,
    instructions: str | None = None,
) -> AnalyticsAgentRuntime:
    """Create the ToolCallingAgent runtime for portfolio analytics questions."""
    resolved_config = config or get_configured_analytics_llm_config()
    model = build_litellm_model(resolved_config)
    agent = ToolCallingAgent(
        tools=[
            get_schema_context,
            get_today_date,
            run_readonly_sql,
            decide_result_presentation,
        ],
        model=model,
        max_steps=10,
        instructions=instructions,
    )
    return AnalyticsAgentRuntime(agent=agent, config=resolved_config)


def _format_settings_error(exc: ValidationError) -> str:
    first_error = exc.errors()[0]
    message = str(first_error["msg"]).removeprefix("Value error, ")
    return message
