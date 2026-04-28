from __future__ import annotations

from dataclasses import dataclass

from pydantic import Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from smolagents import LiteLLMModel, ToolCallingAgent

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


def build_litellm_model(config: AnalyticsLLMConfig | None = None) -> LiteLLMModel:
    """Create the smolagents LiteLLM model using only env/settings config."""
    resolved_config = config or get_analytics_llm_config()
    return LiteLLMModel(model_id=resolved_config.model_id)


def build_analytics_agent_runtime(
    config: AnalyticsLLMConfig | None = None,
    instructions: str | None = None,
) -> AnalyticsAgentRuntime:
    """Create the ToolCallingAgent runtime for portfolio analytics questions."""
    resolved_config = config or get_analytics_llm_config()
    model = build_litellm_model(resolved_config)
    agent = ToolCallingAgent(
        tools=[get_schema_context, get_today_date, run_readonly_sql],
        model=model,
        max_steps=10,
        instructions=instructions,
    )
    return AnalyticsAgentRuntime(agent=agent, config=resolved_config)


def _format_settings_error(exc: ValidationError) -> str:
    first_error = exc.errors()[0]
    message = str(first_error["msg"]).removeprefix("Value error, ")
    return message
